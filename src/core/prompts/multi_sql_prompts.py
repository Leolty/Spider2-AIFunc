"""
Prompts for the MultiSQLAgent that handles multiple gold SQLs.

This agent receives N gold SQLs for the same instruction, analyzes why they differ,
and produces one unambiguous AI instruction + SQL.
"""
from typing import Dict, Any, List, Optional

from .builders import format_data_with_truncation, DIVERSITY_REQUIREMENT_PROMPT
from .system_prompts import AGENT_SYSTEM_PROMPT


# =============================================================================
# Additional Section for Multiple Gold SQLs
# =============================================================================

MULTI_SQL_SECTION = """<multiple_gold_sqls>
**Understanding Multiple Gold SQL Solutions**

You may receive MULTIPLE gold SQL solutions for the same instruction. Each gold SQL represents a different interpretation of the original instruction - this means the original instruction is ambiguous.

**Why this matters:**
- The original instruction can be understood in multiple ways
- Each gold SQL is one valid interpretation, but they produce different results
- Some gold SQLs may even have their own issues or be suboptimal
- Your job is to create an AI instruction that eliminates this ambiguity

**Your Goal: Specification Determinism**

Your final AI instruction must be "specification deterministic" - meaning:
- Given your AI instruction, any competent person writing SQL should arrive at the SAME result
- There should be only ONE correct way to interpret your instruction
- No room for ambiguity in filtering, aggregation, ordering, or any other aspect

**How to approach this:**

1. In your <thinking>, analyze WHY these gold SQLs differ:
   - What aspect of the original instruction is ambiguous?
   - What different interpretations do the gold SQLs represent?
   - Which interpretation makes the most sense given the context?

2. Choose one interpretation and make it EXPLICIT in your AI instruction, e.g.:
   - "top-selling" → specify "highest quantity sold" or "highest revenue"
   - "average price" → specify "per product" or "per category"
   - Date output → specify a format like "YYYY-MM-DD" vs "Mon DD, YYYY"
   - Percentage output → specify "0.15" vs "15%"
   - ... (based on your analysis of why the results differ)

3. Your final AI SQL should implement this unambiguous instruction with AI enhancements.

**If there is only one gold SQL:** Simply proceed with the standard AI enhancement workflow - no disambiguation needed.
</multiple_gold_sqls>"""


# =============================================================================
# Additional Thinking Requirements for Multi-SQL Mode
# =============================================================================

# Round 1: Insert Ambiguity Analysis after Intent Analysis, before Integration Strategy
MULTI_SQL_ROUND1_ADDITION = """2.  **Ambiguity Analysis (if multiple gold SQLs provided):**
    - Compare the gold SQLs: What specific aspects differ between them? (e.g., join logic, time calculation, filtering criteria, aggregation scope)
    - Root cause: What aspect of the original instruction is ambiguous that led to these different interpretations?
    - Anchor selection: Choose ONE gold SQL as your reference implementation. State which one (a/b/c) and explain why this interpretation is more reasonable.
    - Disambiguation plan: What EXACT phrase will you add to your instruction to eliminate this ambiguity? The phrase should make the chosen interpretation explicit.
"""

# Round 2+: Add Ambiguity Verification check
MULTI_SQL_ROUND2_ADDITION = """6.  **Ambiguity Verification (if multiple gold SQLs were provided, required before considering `done`):**
    - Confirm that your instruction contains the disambiguating phrase you planned in Round 1.
    - Verify that your instruction explicitly excludes the interpretations from the other gold SQLs. For example, if Gold SQL A outputs dates as "YYYY-MM-DD" and Gold SQL B outputs "Mon DD, YYYY", your instruction should specify the exact format so only one is valid.
"""

# Done condition: Add ambiguity resolution check
MULTI_SQL_DONE_CONDITION = """- (If multiple gold SQLs were provided) Your instruction explicitly resolves the original ambiguity, another engineer reading it would arrive at only ONE possible interpretation, not any of the other gold SQL interpretations"""


# =============================================================================
# Complete System Prompt for MultiSQLAgent
# =============================================================================

# Build the multi-SQL system prompt by inserting additional requirements
MULTI_SQL_AGENT_SYSTEM_PROMPT = (
    AGENT_SYSTEM_PROMPT
    # 1. Insert multi-SQL overview section AFTER task_overview (not nested inside)
    .replace(
        "</task_overview>",
        f"</task_overview>\n\n{MULTI_SQL_SECTION}"
    )
    # 2. Insert Ambiguity Analysis in Round 1 (after Intent Analysis, before Integration Strategy)
    .replace(
        "2.  **Integration Strategy:** Propose",
        f"{MULTI_SQL_ROUND1_ADDITION}3.  **Integration Strategy:** Based on your anchored gold SQL (or the single gold SQL if only one is provided), propose"
    )
    # 3. Renumber Determinism Audit from 3 to 4
    .replace(
        "3.  **Determinism Audit:**",
        "4.  **Determinism Audit:**"
    )
    # 4. Insert Ambiguity Verification in Round 2+ (after Performance & AI-Cost Audit)
    .replace(
        "</thinking>",
        f"{MULTI_SQL_ROUND2_ADDITION}</thinking>"
    )
    # 5. Add done condition for ambiguity resolution
    .replace(
        "- AI integration is structurally embedded, not artificially appended",
        f"- AI integration is structurally embedded, not artificially appended\n{MULTI_SQL_DONE_CONDITION}"
    )
    # 6. Update input_format to reflect multiple gold SQLs
    .replace(
        "- `<gold_sql>`: The original SQL query (traditional SQL without AI functions) that was executed\n- `<execution_result>`: Execution results from the original query",
        "- `<gold_sqls>`: One or more gold SQL queries, each representing a valid interpretation of the instruction\n- `<execution_result>`: Execution results for each gold SQL"
    )
    )


# =============================================================================
# Input Formatter for Multiple Gold SQLs
# =============================================================================

def format_multi_sql_input(
    instruction: str,
    gold_sqls: List[str],
    execution_results: List[Dict[str, Any]],
    schema_content: str,
    db_id: str,
    external_knowledge: Optional[str] = None,
    diversity_hint: bool = False
) -> str:
    """
    Format inputs with multiple gold SQLs for the MultiSQLAgent.
    
    Args:
        instruction: Original natural language instruction
        gold_sqls: List of gold SQL queries
        execution_results: List of execution results for each SQL
        schema_content: Formatted database schema
        db_id: Database ID
        external_knowledge: Optional external knowledge content
        diversity_hint: If True, prepend diversity requirement to encourage
            underrepresented AI functions (AI_SENTIMENT, AI_EXTRACT, AI_AGG)
        
    Returns:
        Formatted user message string for the agent
    """
    execution_results = execution_results or []

    # Format each gold SQL with its result
    sql_sections = []
    num_sqls = len(gold_sqls)
    version_labels = 'abcdefghijklmnopqrstuvwxyz'
    
    for i, sql in enumerate(gold_sqls):
        result = execution_results[i] if i < len(execution_results) else {}
        # Format the execution result
        status = result.get('status', 'unknown')
        if status == 'success':
            num_rows = result.get('num_rows', 0)
            num_columns = result.get('num_columns', 0)
            exec_time = result.get('execution_time', 0)
            
            result_summary = f"Status: SUCCESS | Rows: {num_rows} | Columns: {num_columns} | Time: {exec_time:.2f}s"
            
            # Format sample data if available
            data = result.get('data')
            if data:
                data_table = format_data_with_truncation(
                    data,
                    max_tokens=1024,  # Smaller budget per SQL since we have multiple
                    max_tokens_per_cell=32
                )
                result_summary += f"\n\nSample Data:\n{data_table}"
        elif result:
            error = result.get('error', 'Unknown error')
            result_summary = f"Status: FAILED | Error: {error}"
        else:
            result_summary = "No execution result provided."
        
        # Use <gold_sql> for single SQL, <gold_sql_a/b/c> for multiple
        if num_sqls == 1:
            tag_name = "gold_sql"
        else:
            version = version_labels[i] if i < len(version_labels) else str(i)
            tag_name = f"gold_sql_{version}"
        
        section = f"""<{tag_name}>
```sql
{sql}
```

**Execution Result:**
{result_summary}
</{tag_name}>"""
        
        sql_sections.append(section)
    
    # Combine all SQL sections
    all_sqls = "\n\n".join(sql_sections)
    
    # Format external knowledge if provided
    knowledge_section = ""
    if external_knowledge:
        knowledge_section = f"""
<external_knowledge>
The following domain-specific knowledge may be relevant:

{external_knowledge}
</external_knowledge>

"""
    
    # Build diversity section if enabled
    diversity_section = f"{DIVERSITY_REQUIREMENT_PROMPT}\n\n" if diversity_hint else ""
    
    # Build complete user message
    if num_sqls > 1:
        sqls_intro = f"You are given {num_sqls} gold SQL solutions for this instruction. Each represents a different interpretation - analyze why they differ and create an unambiguous AI instruction."
    else:
        sqls_intro = "You are given 1 gold SQL solution for this instruction."
    
    user_message = f"""{diversity_section}<original_instruction>
{instruction}
</original_instruction>

<gold_sqls>
{sqls_intro}

{all_sqls}
</gold_sqls>

<database_schema>
{schema_content}
</database_schema>
{knowledge_section}"""
    
    return user_message.strip()
