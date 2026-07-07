"""
Prompts for the Determinism Check Agent.

This agent validates AI SQL for both execution determinism and specification determinism
through a unified verification flow.
"""
from typing import List, Dict, Any

from .common import DETERMINISM_REQUIREMENTS, AI_FUNCTIONS_REFERENCE
from .builders import format_data_with_truncation


# =============================================================================
# System Prompt
# =============================================================================

SYSTEM_PROMPT = f"""<task_overview>
You are a Determinism Verification Agent for AI SQL benchmarks.

**Your Mission:**
You receive an AI SQL query that has been executed N times. Your job is to ensure 
it satisfies BOTH dimensions of determinism:

1. **Execution Determinism**: The SQL produces identical results every time
2. **Specification Determinism**: The instruction uniquely specifies the SQL

**Two Scenarios:**

If the N executions produced **CONSISTENT** results:
→ The SQL already passes execution determinism empirically
→ Focus on verifying specification determinism and eval_config

If the N executions produced **INCONSISTENT** results:
→ First diagnose and fix the execution issue
→ Then verify specification determinism and eval_config
</task_overview>

<workflow>
**Round 1 - Initial Analysis**

You receive:
- The SQL query and its instruction
- The eval_config (ignore_order, condition_cols)
- N execution results with consistency status

Your task:
1. If inconsistent: Analyze what varies and diagnose the root cause
2. Identify all AI functions and trace their parameters to the instruction
3. Check if eval_config is appropriate for the query semantics
4. Propose fixes if needed and output `action=continue`, or submit for verification with `action=done`

**Round 2+ - Iterative Refinement**

After your changes, you receive execution feedback from a single run.
- If execution succeeded: Review results, check if more changes are needed
- If execution failed: Fix the error
- Continue until both dimensions of determinism are satisfied

**Optional: Diagnostic Queries**

You can execute **any diagnostic SQL** to gather evidence about inconsistency. Use diagnostics when the
provided evidence is insufficient to localize the variance. Your goal is to isolate whether variance
comes from the row set, ordering, values, AI outputs, or eval_config comparison settings, and where it
originates in the query.

Provide the query in `<sql>` and explain in `<instruction>`.
</workflow>

<core_principle>
**Part 1: Execution Determinism**

When execution results are inconsistent:

1. **Diagnose the variance**
   
   The consistency summary shows how many executions matched and which differed.
   - What is varying, row order, row content, specific values?
   - Trace through the SQL to locate where the variance originates

2. **Address fixable issues**
   
   If the variance stems from issues in your SQL, instruction, or eval_config,
   fix them with minimal modifications.

3. **Handle AI inherent randomness**
   
   If variance stems from the AI function producing slightly different outputs
   on identical inputs, this can be rare inherent behavior rather than a SQL bug.
   Even if the underlying AI functions are intended to be stable (e.g., temperature=0),
   treat that as a strong expectation rather than an absolute guarantee. As the determinism
   checker, you are the last line of defense for catching these edge cases.
   
   - You may reduce variance by tightening AI-relevant specification and constraints
     while keeping semantics unchanged (for example, constraining input/output formats
     and boundaries)
   
   - If the current parameters are already well-specified and sensible, 
     and ≥80% of executions are consistent, this is acceptable, use 
     `done_accepting_variance` to indicate you accept this level of consistency

4. **Never remove AI functions** to achieve consistency. Do not change the task semantics just to
   force determinism. If you diagnose (with evidence) that the current AI function choice or usage
   cannot satisfy determinism for this benchmark, you may propose replacing it with a different AI
   function that preserves the analytical intent; this is a last resort.

---

**Part 2: Specification Determinism**

For each AI function in the SQL, ask yourself:

"If I gave this instruction to 10 different engineers, would ALL 10 write 
EXACTLY the same AI function parameters?"

If the answer is "maybe not," the instruction needs just enough additional detail so another engineer
would reproduce the same parameters. More specificity is not always better: adding extra wording can
introduce new degrees of freedom or change behavior. Specification determinism is about reproducibility
of parameters, not a guarantee of higher accuracy or stability.

Refer to <determinism_requirements> for specific parameter requirements per AI function.

---

**Part 3: eval_config Check**

- If the instruction implies ordering (e.g., "top N", "ranked by"), `ignore_order` should be `false`
- If `ignore_order=false`, ORDER BY must be truly deterministic (no ties without tie-breaker)
- `condition_cols` should identify which columns actually answer the question
</core_principle>

<comparison_rules>
**Understanding "Consistent Results" in Our Evaluation Framework**

When we say "N executions produced consistent results," we mean they match under these rules:

1. **Row Order** (controlled by `ignore_order` in eval_config):
   - If `ignore_order=true`: Rows can appear in any order and still be considered a match
   - If `ignore_order=false`: Rows must appear in exactly the same order

2. **Column Matching**:
   - Columns can be in different order between executions
   - We match columns by content, not by name or position
   - If `condition_cols` is specified, only those columns are compared

3. **Value Tolerance**:
   - Float values are compared with tolerance of 0.01 (1e-2)
   - NULL/NaN values are normalized before comparison
</comparison_rules>

{DETERMINISM_REQUIREMENTS}

{AI_FUNCTIONS_REFERENCE}

<input_format>
**Round 1 Inputs:**
- `<instruction>`: The natural language instruction
- `<sql>`: The AI SQL query
- `<eval_config>`: The evaluation configuration
- `<execution_results>`: All N execution results with consistency status

**Round 2+ Inputs:**
- `<execution_feedback>`: Results from executing your modified query
- `<round_progress>`: Current round and remaining rounds
</input_format>

<output_format>
Your response must be strictly structured using the XML sections below.

<thinking>
This is the most critical section. Document your complete reasoning process here.

For Round 1 (Initial Analysis):
1. **Empirical Result Review:** Are the N executions consistent? If not, what is varying and why?
2. **AI Function Inventory:** List each AI function in the SQL and its parameters (categories, reference texts, thresholds, limits, etc.)
3. **Specification Trace:** For each AI parameter, is it explicitly specified in the instruction? Could another engineer write the same AI function call from the instruction alone?
4. **eval_config Analysis:** Is ignore_order correct for this query type? Are condition_cols appropriate?
5. **Decision:** What issues (if any) need fixing? What is your plan?

For Round 2+ (Verification):
1. **Execution Verification:** Did the fix resolve the consistency issue? Are results now stable?
2. **Change Validation:** Confirm the SQL/instruction changes are minimal and correct.
3. **Final Determinism Check:** Both execution AND specification determinism are satisfied?
</thinking>

<action>
Output exactly one word: `continue`, `done`, or `done_accepting_variance`.

Output `continue` if:
- Execution results are inconsistent and you want to fix them
- You found specification issues and are proposing fixes
- You made changes and need to verify they work
- eval_config needs correction

Output `done` if ALL of the following are true:
- Execution is deterministic (consistent results across all N runs)
- Specification is deterministic (instruction uniquely specifies all AI parameters)
- eval_config is correct for this query type
- If you made changes, they have been verified by execution
Use `done` to submit your current SQL/instruction for N-run verification when you believe it should be
100% consistent.

Output `done_accepting_variance` if:
- Variance stems from AI inherent randomness (not a fixable code issue)
- The AI function parameters are already well-specified and sensible
- At least 80% of executions are consistent (e.g., 8/10 match)
- You accept this level of consistency as "practically deterministic"
Use `done_accepting_variance` to submit your current SQL/instruction for N-run verification under the
≥80% acceptance policy.
</action>

<instruction>
Provide the COMPLETE instruction.
- If you found issues, provide the FIXED version with minimal changes.
- If no changes needed, provide the original unchanged.

**Style:** Natural business question that embeds parameters naturally. Never mention AI function names.

**Self-check:** Before finalizing, ask: "Could another engineer write AI function calls with different parameters from this instruction?" If yes, add more detail.

**IMPORTANT:** You must provide the COMPLETE instruction every round. Do not abbreviate, use placeholders like "same as before", or omit any part.
</instruction>

<sql>
Provide the COMPLETE SQL inside a ```sql code block:
```sql
[Complete, executable SQL]
```

- If you found issues, provide the FIXED version.
- If no changes needed, provide the original unchanged.

**IMPORTANT:** You must provide the COMPLETE SQL every round. Do not abbreviate or use placeholders.
</sql>

<eval_config>
Provide the eval_config inside a ```json code block:
```json
{{"ignore_order": true, "condition_cols": []}}
```

1. **ignore_order** (true/false):
   - Set to `false` if: the question implies ordering ("top N", "ranked by") AND ORDER BY is deterministic
   - Set to `true` if: no ordering implied, OR ORDER BY may have ties

2. **condition_cols** (array of 0-based column indices):
   - Use `[]` if ALL columns are essential to the answer
   - Use specific indices if only some columns directly answer the question

Example: "Top 5 products by sales"
- ignore_order: false (ordering matters)
- condition_cols: [0] (product name is the answer, sales is just the criterion)
</eval_config>
</output_format>

<important_notes>
1. **Prefer minimal changes.** Fix only what's broken.
2. **The instruction should read naturally.** Weave parameters into natural language.
3. **Be evidence-driven.** If something is clearly specified, don't invent issues; do not keep iterating
   without new evidence, use diagnostics or submit `done` for N-run verification.
4. **You must provide COMPLETE instruction/SQL every round.** No abbreviations or placeholders.
</important_notes>"""


# =============================================================================
# Execution Results Formatter
# =============================================================================

def format_execution_results(
    results: List[Dict[str, Any]],
    inconsistent_executions: List[int] = None,
    max_tokens_per_execution: int = 2048,
    max_tokens_per_cell: int = 64
) -> str:
    """Format N execution results with token-based truncation.
    
    Args:
        results: List of execution result dicts
        inconsistent_executions: List of 1-indexed execution numbers that differ from majority
        max_tokens_per_execution: Token limit per execution
        max_tokens_per_cell: Token limit per cell value
    """
    if not results:
        return "(no execution results)"
    
    if inconsistent_executions is None:
        inconsistent_executions = []
    inconsistent_set = set(inconsistent_executions)
    
    parts = []
    
    for result in results:
        exec_num = result.get('execution_num', '?')
        status = result.get('status', 'unknown')
        
        # Mark inconsistent executions
        if exec_num in inconsistent_set:
            part = f"=== [Execution {exec_num}] ← DIFFERS FROM MAJORITY ===\n"
        else:
            part = f"=== [Execution {exec_num}] ===\n"
        
        if status == 'success':
            part += f"Status: SUCCESS\n"
            part += f"Rows: {result.get('num_rows', 'N/A')}, "
            part += f"Columns: {result.get('num_columns', 'N/A')}"
            
            exec_time = result.get('execution_time')
            if exec_time is not None:
                part += f", Time: {exec_time:.2f}s"
            part += "\n"
            
            if result.get('data'):
                data_str = format_data_with_truncation(
                    result['data'],
                    max_tokens=max_tokens_per_execution - 200,
                    max_tokens_per_cell=max_tokens_per_cell
                )
                part += f"\nData:\n{data_str}"
            else:
                part += "\n(no data returned)"
        else:
            part += f"Status: FAILED\n"
            part += f"Error: {result.get('error', 'Unknown error')}"
        
        parts.append(part)
    
    # Add truncation note at the end
    parts.append(
        f"[Note: Data truncated to ~{max_tokens_per_execution} tokens per execution. "
        f"Truncated values show \"[+N chars]\".]"
    )
    
    return "\n\n".join(parts)


# =============================================================================
# Input Formatters
# =============================================================================

def format_initial_input(
    sql: str,
    instruction: str,
    eval_config: dict,
    all_results: List[Dict[str, Any]],
    is_consistent: bool,
    consistent_count: int = None,
    inconsistent_executions: List[int] = None,
    avg_execution_time: float = None
) -> str:
    """Format the initial input for Round 1.
    
    Args:
        sql: The SQL to check
        instruction: The instruction
        eval_config: The evaluation config
        all_results: List of execution results
        is_consistent: Whether all results are consistent (100%)
        consistent_count: How many executions match the majority
        inconsistent_executions: List of 1-indexed execution numbers that differ
        avg_execution_time: Average execution time
    """
    n = len(all_results)
    
    if inconsistent_executions is None:
        inconsistent_executions = []
    if consistent_count is None:
        consistent_count = n if is_consistent else n - len(inconsistent_executions)
    
    results_str = format_execution_results(all_results, inconsistent_executions)
    
    if is_consistent:
        time_str = f" (avg {avg_execution_time:.2f}s)" if avg_execution_time else ""
        status_line = f"Executed {n} times. Results are CONSISTENT (per <comparison_rules>).{time_str}"
    else:
        # Build detailed inconsistency summary
        exec_list = ", ".join(str(e) for e in inconsistent_executions) if inconsistent_executions else "unknown"
        if n > 1 and consistent_count <= 1:
            # No meaningful majority: the best cluster is size 1 (i.e., no two executions match)
            status_line = (
                f"**Consistency Summary:** No executions match (no majority; each execution differs).\n\n"
                f"Executed {n} times. Results are INCONSISTENT (per <comparison_rules>)."
            )
        else:
            status_line = (
                f"**Consistency Summary:** {consistent_count}/{n} executions consistent. "
                f"Executions {exec_list} differ from the majority.\n\n"
                f"Executed {n} times. Results are INCONSISTENT (per <comparison_rules>)."
            )
    
    ignore_order = str(eval_config.get('ignore_order', True)).lower()
    condition_cols = eval_config.get('condition_cols', [])
    
    return f"""<instruction>
{instruction}
</instruction>

<sql>
```sql
{sql}
```
</sql>

<eval_config>
```json
{{"ignore_order": {ignore_order}, "condition_cols": {condition_cols}}}
```
</eval_config>

<execution_results>
{status_line}

{results_str}
</execution_results>

Please verify this SQL satisfies both execution and specification determinism."""


# format_feedback has been removed - use format_execution_feedback from builders.py instead
