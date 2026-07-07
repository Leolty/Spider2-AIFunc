"""
SQL Agent that generates AI-enhanced SQL with iterative debugging.

The agent's job is to generate AI SQL, execute it, and fix any errors.
"""
from typing import Dict, Any, List, Optional
from pathlib import Path

from src.core import (
    database,
    prompts,
    LLMResponseParser,
    SnowflakeExecutor
)


class SQLGenerationAgent:
    """
    Agent that generates AI-enhanced SQL with iterative debugging capability.
    
    The agent:
    1. Generates AI-enhanced SQL from original SQL
    2. Executes the generated SQL
    3. If failed: Sees the error and fixes it
    4. If succeeded: Checks if results are reasonable
    5. Repeats until satisfied or max rounds reached
    """
    
    def __init__(self, llm_client, max_rounds: int = 5, verbose: bool = False, temperature: float = 0.7):
        """
        Initialize the SQL generation agent.
        
        Args:
            llm_client: LLM client for querying
            max_rounds: Maximum number of generation/debug rounds
            verbose: If True, print detailed progress logs
            temperature: LLM temperature for response generation (default: 0.7)
        """
        self.llm_client = llm_client
        self.max_rounds = max_rounds
        self.verbose = verbose
        self.temperature = temperature
        
        # For debugging: save info from last run
        self.messages = None  # Full conversation history from last generate()
        self.rounds = None  # All rounds data from last generate()
        self.last_response = None  # Most recent LLM response
        self.last_parsed = None  # Most recent parsed response
        
        # History of all generate() calls
        self.history = []  # List of all results from generate()
    
    def generate(
        self,
        instruction: str,
        sql_query: str,
        result: Dict[str, Any],
        schema_content: str,
        db_id: str,
        external_knowledge: Optional[str] = None,
        diversity_hint: bool = False
    ) -> Dict[str, Any]:
        """
        Generate AI-enhanced SQL with iterative debugging.
        
        Args:
            instruction: Original natural language instruction
            sql_query: Original SQL query
            result: Original execution result
            schema_content: Database schema
            db_id: Database ID
            external_knowledge: Optional external knowledge
            diversity_hint: If True, include diversity requirement to encourage
                underrepresented AI functions (AI_SENTIMENT, AI_EXTRACT, AI_AGG)
            
        Returns:
            Dict with:
            - rounds: List of all rounds (each with action, sql, execution, etc.)
            - final_status: 'done', 'max_rounds_reached', 'rejected', 'error', etc.
            - final_sql: The final SQL query
            - final_instruction: The final instruction
        """
        result_data = {
            'rounds': [],
            'final_status': 'pending'
        }
        
        # Round 1: Initial generation
        user_input = prompts.format_sql_conversion_input(
            instruction=instruction,
            sql_query=sql_query,
            result=result,
            schema_content=schema_content,
            db_id=db_id,
            external_knowledge=external_knowledge,
            diversity_hint=diversity_hint
        )
        
        # Initialize conversation
        messages = prompts.build_messages(
            user_message=user_input,
            system_prompt=prompts.AGENT_SYSTEM_PROMPT
        )
        
        # Iterative generation/debug loop
        for round_num in range(1, self.max_rounds + 1):
            if self.verbose:
                print(f"     [Round {round_num}] 🔄 Starting...")
            
            round_info = {'round': round_num}
            
            try:
                # Query LLM
                if self.verbose:
                    print(f"     [Round {round_num}] 💬 Querying LLM...")
                response = self.llm_client.query(messages, max_tokens=16384, temperature=self.temperature)
                round_info['llm_response'] = response
                if self.verbose:
                    print(f"     [Round {round_num}] ✅ LLM responded ({len(response)} chars)")
                
                # Save for debugging
                self.last_response = response
                
                # Parse response
                if self.verbose:
                    print(f"     [Round {round_num}] 📝 Parsing response...")
                parsed = LLMResponseParser.parse_agent_response(response)
                round_info.update({
                    'parse_status': parsed['parse_status'],
                    'action': parsed['action'],
                    'thinking': parsed['thinking'],
                    'instruction': parsed['instruction'],
                    'sql': parsed['sql'],
                    'eval_config': parsed.get('eval_config')
                })
                
                # Save for debugging
                self.last_parsed = parsed
                
                if self.verbose:
                    print(f"     [Round {round_num}] ✅ Parsed: action={parsed['action']}, status={parsed['parse_status']}")
                
                # Handle reject action first (diversity mode) - reject may omit <sql>
                if parsed['action'] == 'reject':
                    if self.verbose:
                        print(f"     [Round {round_num}] REJECTED - target functions not suitable")
                    messages.append({"role": "assistant", "content": response})
                    result_data['rounds'].append(round_info)
                    result_data['final_status'] = 'rejected'
                    result_data['reject_reason'] = parsed.get('thinking')
                    break
                
                # Check parse status
                if parsed['parse_status'] != 'success':
                    if parsed['parse_status'] == 'truncated_sql':
                        # SQL was truncated due to output length limit - give feedback to retry
                        if self.verbose:
                            print(f"     [Round {round_num}] SQL truncated (too long) - asking LLM to rewrite...")
                        
                        result_data['rounds'].append(round_info)
                        
                        # Generate truncation feedback
                        truncation_feedback = f"""<round_progress>
Round {round_num} of {self.max_rounds} ({self.max_rounds - round_num} remaining)
</round_progress>

<execution_feedback>
Status: SQL_TRUNCATED
Error: Your SQL output was truncated because it exceeded the output length limit. The query is incomplete and cannot be executed.

Please either:
1. Rewrite your SQL to be more concise (but it MUST match the instruction)
2. Adjust your instruction (and SQL) to avoid super long SQLs
</execution_feedback>"""
                        
                        messages.append({"role": "assistant", "content": response})
                        messages.append({"role": "user", "content": truncation_feedback})
                        continue  # Don't break, let LLM retry
                    else:
                        # Other parse errors - break
                        if self.verbose:
                            print(f"     [Round {round_num}] Parse error: {parsed['parse_status']}")
                        # Save the response even if parsing failed
                        messages.append({"role": "assistant", "content": response})
                        result_data['rounds'].append(round_info)
                        result_data['final_status'] = f'parse_error_round_{round_num}'
                        break
                
                # Execute the generated SQL (always execute, even when agent says done)
                if self.verbose:
                    if parsed['action'] == 'done':
                        print(f"     [Round {round_num}] Agent says DONE - verifying SQL...")
                    print(f"     [Round {round_num}] Executing SQL...")
                
                exec_result = self._execute_sql(parsed['sql'])
                round_info['execution'] = exec_result
                
                if self.verbose:
                    if exec_result['status'] == 'success':
                        print(f"     [Round {round_num}] ✅ Execution SUCCESS: {exec_result['num_rows']} rows, {exec_result['execution_time']:.1f}s")
                    else:
                        error_msg = exec_result.get('error', '')[:60]
                        print(f"     [Round {round_num}] ❌ Execution FAILED: {error_msg}...")
                
                # If agent said done AND execution succeeded, we're truly done
                if parsed['action'] == 'done' and exec_result['status'] == 'success':
                    if self.verbose:
                        print(f"     [Round {round_num}] ✅ Verified DONE!")
                    messages.append({"role": "assistant", "content": response})
                    result_data['rounds'].append(round_info)
                    result_data['final_status'] = 'done'
                    result_data['final_sql'] = parsed['sql']
                    result_data['final_instruction'] = parsed['instruction']
                    result_data['final_eval_config'] = parsed.get('eval_config')
                    break
                
                # If agent said done BUT execution failed, continue iterating
                if parsed['action'] == 'done' and exec_result['status'] != 'success':
                    if self.verbose:
                        print(f"     [Round {round_num}] ⚠️  Agent said done but SQL failed! Continuing...")
                
                result_data['rounds'].append(round_info)
                
                # Generate feedback for next round (include round progress)
                feedback = prompts.format_execution_feedback(
                    exec_result,
                    current_round=round_num,
                    max_rounds=self.max_rounds
                )
                
                # Update conversation
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": feedback})
                
            except Exception as e:
                if self.verbose:
                    print(f"     [Round {round_num}] 💥 Exception: {str(e)}")
                # Save the response if we got one before the exception
                if 'llm_response' in round_info:
                    messages.append({"role": "assistant", "content": round_info['llm_response']})
                round_info['error'] = str(e)
                result_data['rounds'].append(round_info)
                result_data['final_status'] = f'error_round_{round_num}'
                break
        
        # If loop ended without done/error, max rounds reached
        if result_data['final_status'] == 'pending':
            if self.verbose:
                print(f"     ⏸️  Max rounds ({self.max_rounds}) reached")
            result_data['final_status'] = 'max_rounds_reached'
            # Use last successful SQL if available
            for round_info in reversed(result_data['rounds']):
                if (round_info.get('sql') and 
                    round_info.get('execution', {}).get('status') == 'success'):
                    result_data['final_sql'] = round_info['sql']
                    result_data['final_instruction'] = round_info['instruction']
                    break
        
        # Save for debugging (current run)
        self.messages = messages
        self.rounds = result_data['rounds']
        
        # Save to history (all runs)
        self.history.append({
            'instruction': instruction,
            'sql_query': sql_query,
            'db_id': db_id,
            'result': result_data,
            'messages': messages
        })
        
        return result_data
    
    def get_history_summary(self) -> str:
        """
        Get a summary of all generate() calls.
        
        Returns:
            Formatted summary string
        """
        if not self.history:
            return "No history yet"
        
        summary = f"Total runs: {len(self.history)}\n\n"
        for i, run in enumerate(self.history, 1):
            summary += f"Run {i}:\n"
            summary += f"  DB: {run['db_id']}\n"
            summary += f"  Instruction: {run['instruction'][:80]}...\n"
            summary += f"  Status: {run['result']['final_status']}\n"
            summary += f"  Rounds: {len(run['result']['rounds'])}\n"
            summary += "\n"
        
        return summary
    
    def _execute_sql(self, sql: str) -> Dict[str, Any]:
        """
        Execute SQL and return formatted result.
        
        Returns:
            Dict with status, num_rows, data (as CSV string), error, etc.
        """
        import pandas as pd
        
        try:
            with SnowflakeExecutor() as executor:
                # let's double the timeout for the SQL query
                exec_result = executor.execute(sql, timeout=240)
                
                if exec_result.status == 'success':
                    # Convert List[Dict] to CSV string to avoid type serialization issues
                    data_csv = ""
                    if exec_result.data:
                        df = pd.DataFrame(exec_result.data)
                        data_csv = df.to_csv(index=False)
                    
                    return {
                        'status': 'success',
                        'num_rows': exec_result.num_rows,
                        'num_columns': exec_result.num_columns,
                        'execution_time': exec_result.execution_time,
                        'data': data_csv
                    }
                else:
                    return {
                        'status': 'failed',
                        'error': exec_result.error
                    }
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e)
            }

