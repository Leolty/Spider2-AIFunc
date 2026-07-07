"""
Determinism Check Agent for AI SQL validation.

This agent validates AI SQL for determinism through a unified verification flow:
1. Execute SQL N times to check empirical consistency
2. Use LLM to verify/fix both execution and specification determinism
"""
import re
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from src.core.comparison import (
    check_execution_consistency,
    execution_result_to_dataframe,
    EvalConfig,
    ConsistencyResult
)
from src.core.prompts.determinism_prompts import (
    SYSTEM_PROMPT,
    format_initial_input,
)
from src.core.prompts import format_execution_feedback
from src.core.sql_executor import SnowflakeExecutor


@dataclass
class CheckResult:
    """Result of determinism check."""
    status: str  # "pass", "fixed", "failed"
    is_deterministic: bool
    
    # Output (may be same as input or fixed)
    final_sql: str
    final_instruction: str
    eval_config: Dict[str, Any]
    
    # Tracking
    rounds: List[Dict[str, Any]] = field(default_factory=list)
    issues_found: List[str] = field(default_factory=list)
    
    # For debugging
    messages: List[Dict[str, str]] = field(default_factory=list)
    empirical_result: Optional[ConsistencyResult] = None


class DeterminismCheckAgent:
    """
    Agent that validates AI SQL determinism through empirical testing and LLM verification.
    
    Workflow:
    1. Execute SQL N times to check empirical consistency
    2. Run unified verification flow (handles both consistent and inconsistent cases)
    """
    
    def __init__(
        self,
        llm_client,
        num_executions: int = 5,
        max_rounds: int = 10,
        verbose: bool = False,
        temperature: float = 0.7,
        timeout: int = 240,
        max_failures: int = 2
    ):
        self.llm_client = llm_client
        self.num_executions = num_executions
        self.max_rounds = max_rounds
        self.verbose = verbose
        self.temperature = temperature
        self.timeout = timeout
        self.max_failures = max_failures
        self.last_response = None
    
    def check(
        self,
        sql: str,
        instruction: str,
        eval_config: Dict[str, Any]
    ) -> CheckResult:
        """Check and optionally fix SQL for determinism."""
        if self.verbose:
            print(f"  🔍 Checking determinism (executing {self.num_executions}x)...")
        
        # Step 1: Empirical check
        config = EvalConfig.from_dict(eval_config)
        consistency, exec_times, all_results = self._execute_n_times(sql, config)
        
        if self.verbose:
            icon = "✅" if consistency.is_consistent else "❌"
            status = "consistent" if consistency.is_consistent else "inconsistent"
            print(f"  {icon} Empirical check: {status}")
        
        # Step 2: Unified verification flow
        return self._run_verification(
            sql, instruction, eval_config,
            consistency, exec_times, all_results
        )
    
    def _execute_n_times(self, sql: str, config: EvalConfig) -> tuple:
        """Execute SQL N times and check consistency.
        
        Tolerates up to `max_failures` failed executions (timeout, error).
        Will attempt up to `num_executions + max_failures` total runs to get
        `num_executions` successful results.
        
        Returns early if:
        - We get `num_executions` successes, OR
        - Failures exceed `max_failures`
        """
        dataframes = []
        exec_times = []
        all_results = []
        
        success_count = 0
        failure_count = 0
        max_attempts = self.num_executions + self.max_failures
        attempt = 0
        
        with SnowflakeExecutor() as executor:
            # Progress indicator
            try:
                from tqdm import tqdm  # type: ignore
                pbar = tqdm(
                    total=self.num_executions,
                    desc=f"Executing SQL (target {self.num_executions} successes)",
                    disable=not self.verbose or self.num_executions <= 1
                )
            except Exception:
                pbar = None
            
            while success_count < self.num_executions and attempt < max_attempts:
                attempt += 1
                
                if self.verbose and pbar is None:
                    print(f"     [Attempt {attempt}] Executing... (successes: {success_count}, failures: {failure_count})")
                
                result = executor.execute(sql, timeout=self.timeout)
                
                if result.status != 'success':
                    failure_count += 1
                    all_results.append({
                        'execution_num': attempt,
                        'status': 'failed',
                        'error': result.error
                    })
                    
                    if self.verbose:
                        if pbar:
                            pbar.set_postfix({"failures": failure_count})
                        else:
                            print(f"     [Attempt {attempt}] ❌ Failed: {str(result.error)[:50]}...")
                    
                    # Check if we've exceeded max failures
                    if failure_count > self.max_failures:
                        if pbar:
                            pbar.close()
                        if self.verbose:
                            print(f"     ⚠️  Too many failures ({failure_count} > {self.max_failures}), stopping early")
                        
                        # Return what we have so far
                        if dataframes:
                            consistency = check_execution_consistency(
                                dataframes,
                                ignore_order=config.ignore_order,
                                condition_cols=config.condition_cols
                            )
                            consistency.failure_count = failure_count
                        else:
                            consistency = ConsistencyResult(
                                is_consistent=False,
                                execution_count=0,
                                failure_count=failure_count
                            )
                        return consistency, exec_times, all_results
                    
                    continue  # Try next attempt
                
                # Success
                success_count += 1
                df = execution_result_to_dataframe(result.data)
                if df is not None:
                    dataframes.append(df)
                exec_times.append(result.execution_time or 0.0)
                
                all_results.append({
                    'execution_num': attempt,
                    'status': 'success',
                    'num_rows': result.num_rows,
                    'num_columns': result.num_columns,
                    'execution_time': result.execution_time,
                    'data': result.data
                })
                
                if pbar:
                    pbar.update(1)
                    pbar.set_postfix({"failures": failure_count})
            
            if pbar:
                pbar.close()
        
        if not dataframes:
            return ConsistencyResult(
                is_consistent=False,
                execution_count=0,
                failure_count=failure_count
            ), exec_times, all_results
        
        consistency = check_execution_consistency(
            dataframes,
            ignore_order=config.ignore_order,
            condition_cols=config.condition_cols
        )
        consistency.failure_count = failure_count
        
        return consistency, exec_times, all_results
    
    def _run_verification(
        self,
        sql: str,
        instruction: str,
        eval_config: Dict[str, Any],
        consistency: ConsistencyResult,
        exec_times: List[float],
        all_results: List[Dict[str, Any]]
    ) -> CheckResult:
        """Unified verification flow for both consistent and inconsistent cases."""
        if self.verbose:
            mode = "consistent" if consistency.is_consistent else "inconsistent"
            print(f"  📝 Running verification ({mode}, max {self.max_rounds} rounds)...")
        
        # Track if Round 1 was consistent - only re-verify on done if it wasn't
        round1_was_consistent = consistency.is_consistent
        
        # Initialize result
        result = CheckResult(
            status="pending",
            is_deterministic=consistency.is_consistent,
            final_sql=sql,
            final_instruction=instruction,
            eval_config=eval_config,
            empirical_result=consistency,
            rounds=[]
        )
        
        # Build initial messages
        avg_time = sum(exec_times) / len(exec_times) if exec_times else None
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": format_initial_input(
                sql=sql,
                instruction=instruction,
                eval_config=eval_config,
                all_results=all_results,
                is_consistent=consistency.is_consistent,
                consistent_count=consistency.consistent_count,
                inconsistent_executions=consistency.inconsistent_executions,
                avg_execution_time=avg_time
            )}
        ]
        
        current_sql = sql
        current_instruction = instruction
        current_eval_config = eval_config.copy()
        
        # Iterative loop
        for round_num in range(1, self.max_rounds + 1):
            if self.verbose:
                print(f"     [Round {round_num}] 💬 Querying LLM...")
            
            round_info = {"round": round_num}
            
            # Query LLM
            response = self.llm_client.query(
                messages, max_tokens=16384, temperature=self.temperature
            )
            messages.append({"role": "assistant", "content": response})
            round_info['llm_response'] = response
            self.last_response = response
            
            # Parse response
            parsed = self._parse_response(response)
            round_info['action'] = parsed.get('action')
            round_info['thinking'] = parsed.get('thinking')
            
            if self.verbose:
                print(f"     [Round {round_num}] ✅ Action: {parsed.get('action')}")
            
            # Check if done or done_accepting_variance
            action = parsed.get('action')
            if action in ['done', 'done_accepting_variance']:
                # Update current values from this response
                if parsed.get('instruction'):
                    current_instruction = parsed['instruction']
                if parsed.get('sql'):
                    current_sql = parsed['sql']
                if parsed.get('eval_config'):
                    current_eval_config = parsed['eval_config']
                
                # If Round 1 was inconsistent, verify the fix
                if not round1_was_consistent:
                    verify_result = self._verify_final_consistency(
                        current_sql, current_eval_config, action, round_num
                    )
                    
                    if verify_result['passed']:
                        # Verification passed, finalize
                        return self._finalize_result(
                            result, messages, round_info, parsed,
                            current_sql, current_instruction, current_eval_config,
                            sql, instruction, eval_config,
                            accepting_variance=(action == 'done_accepting_variance')
                        )
                    else:
                        # Verification failed, add feedback and continue
                        if self.verbose:
                            print(f"     [Round {round_num}] ⚠️  Final verification: {verify_result['message']}")
                        
                        result.rounds.append(round_info)
                        messages.append({"role": "user", "content": verify_result['feedback']})
                        continue
                else:
                    # Round 1 was consistent, no need to re-verify
                    return self._finalize_result(
                        result, messages, round_info, parsed,
                        current_sql, current_instruction, current_eval_config,
                        sql, instruction, eval_config,
                        accepting_variance=(action == 'done_accepting_variance')
                    )
            
            # Update current values
            if parsed.get('instruction'):
                current_instruction = parsed['instruction']
            if parsed.get('sql'):
                current_sql = parsed['sql']
            if parsed.get('eval_config'):
                current_eval_config = parsed['eval_config']
            
            # Execute and get feedback
            if self.verbose:
                print(f"     [Round {round_num}] ❄️  Executing SQL...")
            
            exec_result = self._execute_sql(current_sql)
            round_info['execution'] = exec_result
            
            if self.verbose:
                if exec_result['status'] == 'success':
                    print(f"     [Round {round_num}] ✅ {exec_result.get('num_rows', 0)} rows")
                else:
                    print(f"     [Round {round_num}] ❌ {exec_result.get('error', '')[:50]}...")
            
            result.rounds.append(round_info)
            
            # Add feedback for next round
            messages.append({"role": "user", "content": format_execution_feedback(
                execution_result=exec_result,
                current_round=round_num,
                max_rounds=self.max_rounds
            )})
        
        # Max rounds reached
        if self.verbose:
            print(f"  ⏸️  Max rounds ({self.max_rounds}) reached")

        # If we reached max rounds without passing a `done` verification, treat as failure.
        if not result.is_deterministic:
            result.status = "failed"
        else:
            result.status = "fixed" if (current_sql != sql or current_instruction != instruction) else "pass"

        result.final_sql = current_sql
        result.final_instruction = current_instruction
        result.eval_config = current_eval_config
        result.messages = messages
        result.issues_found.append(f"Completed after {self.max_rounds} rounds")
        
        return result
    
    def _verify_final_consistency(
        self,
        sql: str,
        eval_config: Dict[str, Any],
        action: str,
        round_num: int
    ) -> Dict[str, Any]:
        """Verify consistency after LLM says done/done_accepting_variance.
        
        Args:
            sql: The SQL to verify
            eval_config: The eval config to use
            action: 'done' (requires 100%) or 'done_accepting_variance' (requires ≥80%)
            round_num: Current round number for feedback
            
        Returns:
            Dict with 'passed', 'message', and 'feedback' (if not passed)
        """
        if self.verbose:
            print(f"     [Round {round_num}] 🔍 Final verification ({self.num_executions}x)...")
        
        # Execute N times
        config = EvalConfig.from_dict(eval_config)
        consistency, exec_times, all_results = self._execute_n_times(sql, config)
        
        n = consistency.execution_count
        consistent_count = consistency.consistent_count
        ratio = consistent_count / n if n > 0 else 0
        
        if action == 'done':
            # Expect 100% consistency
            if consistency.is_consistent:
                if self.verbose:
                    print(f"     [Round {round_num}] ✅ Final verification: {n}/{n} consistent")
                return {'passed': True, 'message': f'{n}/{n} consistent'}
            else:
                inconsistent_list = ", ".join(str(e) for e in consistency.inconsistent_executions)
                feedback = f"""<final_verification>
Round {round_num} of {self.max_rounds}

Your SQL was re-executed {n} times for final verification.

Result: {consistent_count}/{n} executions consistent ({ratio:.0%}).
Executions {inconsistent_list} differ from the majority.

You indicated `done` (expecting 100% consistency), but results are not fully consistent.

Options:
- Fix the remaining inconsistency and try `done` again
- If this is AI inherent randomness, use `done_accepting_variance` to accept ≥80% consistency
</final_verification>"""
                return {
                    'passed': False,
                    'message': f'{consistent_count}/{n} consistent (expected 100%)',
                    'feedback': feedback
                }
        
        elif action == 'done_accepting_variance':
            # Expect ≥80% consistency
            threshold = 0.8
            if ratio >= threshold:
                if self.verbose:
                    print(f"     [Round {round_num}] ✅ Final verification: {consistent_count}/{n} consistent ({ratio:.0%} ≥ 80%)")
                return {'passed': True, 'message': f'{consistent_count}/{n} consistent ({ratio:.0%})'}
            else:
                inconsistent_list = ", ".join(str(e) for e in consistency.inconsistent_executions)
                feedback = f"""<final_verification>
Round {round_num} of {self.max_rounds}

Your SQL was re-executed {n} times for final verification.

Result: {consistent_count}/{n} executions consistent ({ratio:.0%}).
Executions {inconsistent_list} differ from the majority.

You indicated `done_accepting_variance` (accepting ≥80% consistency), but only {ratio:.0%} matched.

Please investigate further or try to reduce variance before accepting.
</final_verification>"""
                return {
                    'passed': False,
                    'message': f'{consistent_count}/{n} consistent ({ratio:.0%}, below 80% threshold)',
                    'feedback': feedback
                }
        
        return {'passed': False, 'message': 'Unknown action', 'feedback': 'Unknown action'}
    
    def _finalize_result(
        self,
        result: CheckResult,
        messages: List[Dict],
        round_info: Dict,
        parsed: Dict,
        current_sql: str,
        current_instruction: str,
        current_eval_config: Dict,
        original_sql: str,
        original_instruction: str,
        original_eval_config: Dict,
        accepting_variance: bool = False
    ) -> CheckResult:
        """Finalize result when agent says 'done' or 'done_accepting_variance'."""
        result.rounds.append(round_info)
        result.messages = messages
        result.final_sql = current_sql
        result.final_instruction = current_instruction
        result.eval_config = current_eval_config
        result.is_deterministic = True
        
        # Determine status and track changes
        changes = []
        if current_sql != original_sql:
            changes.append("SQL updated")
        if current_instruction != original_instruction:
            changes.append("Instruction updated for specification determinism")
        if current_eval_config != original_eval_config:
            changes.append("eval_config corrected")
        if accepting_variance:
            changes.append("Accepted with AI variance (≥80% consistent)")
        
        result.status = "fixed" if changes else "pass"
        result.issues_found = changes
        
        if self.verbose:
            status_msg = result.status
            if accepting_variance:
                status_msg += " (accepting variance)"
            print(f"     ✅ Verification complete! Status: {status_msg}")
        
        return result
    
    def _execute_sql(self, sql: str) -> Dict[str, Any]:
        """Execute SQL and return formatted result."""
        import pandas as pd
        
        try:
            with SnowflakeExecutor() as executor:
                result = executor.execute(sql, timeout=self.timeout)
                
                if result.status == 'success':
                    # Convert List[Dict] to CSV string to avoid type serialization issues
                    data_csv = ""
                    if result.data:
                        df = pd.DataFrame(result.data[:10])  # Keep the limit of 10 rows
                        data_csv = df.to_csv(index=False)
                    
                    return {
                        'status': 'success',
                        'num_rows': result.num_rows,
                        'num_columns': result.num_columns,
                        'execution_time': result.execution_time,
                        'data': data_csv
                    }
                else:
                    return {'status': 'failed', 'error': result.error}
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
    
    def _parse_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM response."""
        result = {
            'action': 'continue',
            'thinking': None,
            'instruction': None,
            'sql': None,
            'eval_config': None
        }
        
        # Extract thinking
        match = re.search(r'<thinking>(.*?)</thinking>', response, re.DOTALL)
        if match:
            result['thinking'] = match.group(1).strip()
        
        # Extract action
        match = re.search(r'<action>(.*?)</action>', response, re.DOTALL)
        if match:
            action = match.group(1).strip().lower()
            # Handle underscores and variations
            action = action.replace(' ', '_')
            valid_actions = ['continue', 'done', 'done_accepting_variance']
            result['action'] = action if action in valid_actions else 'continue'
        
        # Extract instruction
        match = re.search(r'<instruction>(.*?)</instruction>', response, re.DOTALL)
        if match:
            result['instruction'] = match.group(1).strip()
        
        # Extract SQL
        match = re.search(r'<sql>\s*```sql\s*(.*?)\s*```\s*</sql>', response, re.DOTALL)
        if match:
            result['sql'] = match.group(1).strip()
        
        # Extract eval_config
        match = re.search(r'<eval_config>\s*```json\s*(.*?)\s*```\s*</eval_config>', response, re.DOTALL)
        if match:
            try:
                result['eval_config'] = json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass
        
        return result
