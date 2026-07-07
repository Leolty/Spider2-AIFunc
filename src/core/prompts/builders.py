"""
Prompt builder functions for assembling messages.
"""
import io
import json
from typing import Dict, Any, List, Optional, Union
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pandas as pd

from .system_prompts import SQL_CONVERTER_SYSTEM_PROMPT


# ============================================================================
# Diversity Enrichment Prompt
# ============================================================================

DIVERSITY_REQUIREMENT_PROMPT = """<diversity_requirement>
CRITICAL: FUNCTION SELECTION OVERRIDE

This instance is part of a diversity enrichment pass. The current benchmark is heavily skewed toward AI_CLASSIFY (78%), AI_FILTER (50%), and AI_SIMILARITY (44%), while AI_SENTIMENT (<1%), AI_EXTRACT (~1%), and AI_AGG (~10%) are severely underrepresented. Your primary objective for this instance is to integrate underrepresented functions. This requirement takes precedence over your default function selection preferences.

**Target Functions (in priority order):**
1. **AI_SENTIMENT**, highest priority, currently used in <1% of the benchmark
2. **AI_EXTRACT**, high priority, currently used in ~1% of the benchmark
3. **AI_AGG**, moderate priority, currently used in ~10% of the benchmark

**Function Combination Rules:**
- 2 functions (encouraged): At least one must be a target function above. The second may be any AI function, including AI_CLASSIFY, AI_FILTER, AI_SIMILARITY, or another target function.
- 1 function (acceptable): Must be one of the three target functions.
- Not allowed: Using only non-target functions (AI_CLASSIFY, AI_FILTER, AI_SIMILARITY) without any target function. This defeats the purpose of this enrichment pass.

**On Rejecting:**
Not every instance is suitable for these target functions, this is expected and part of why they are underrepresented. If the data and query intent do not support any of the three target functions, use action `reject` and explain in your `<thinking>` why each target function is unsuitable. A well-reasoned rejection is preferred over a forced, unnatural integration.

Do not default to AI_CLASSIFY + AI_FILTER or AI_CLASSIFY + AI_SIMILARITY. Those combinations are already overrepresented and not what is needed here. Consider the target functions first, then pair with a common function if it strengthens the analysis.
</diversity_requirement>"""


class _JSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for date, datetime, time, timedelta, Decimal types."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, date):
            return obj.isoformat()
        elif isinstance(obj, time):
            return obj.isoformat()
        elif isinstance(obj, timedelta):
            return str(obj)
        elif isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def _format_value(value: Any, max_chars: int = 256) -> tuple:
    """
    Format a single value for markdown table display.
    
    Args:
        value: The value to format
        max_chars: Maximum characters before truncation (default 256 ≈ 64 tokens)
        
    Returns:
        Tuple of (formatted_string, chars_truncated)
    """
    if value is None:
        return "NULL", 0
    elif isinstance(value, datetime):
        return value.isoformat(), 0
    elif isinstance(value, date):
        return value.isoformat(), 0
    elif isinstance(value, Decimal):
        return str(float(value)), 0
    elif isinstance(value, (dict, list)):
        # For complex types, use compact JSON
        s = json.dumps(value, ensure_ascii=False)
    else:
        s = str(value)
    
    if len(s) > max_chars:
        truncated = len(s) - max_chars
        return s[:max_chars] + f"...[+{truncated} chars]", truncated
    return s, 0


def _format_as_markdown_table(
    data: List[Dict[str, Any]], 
    max_chars_per_cell: int = 256
) -> tuple:
    """
    Format a list of dicts as a markdown table.
    
    Args:
        data: List of dictionaries (rows)
        max_chars_per_cell: Maximum chars for cell values (default 256 ≈ 64 tokens)
        
    Returns:
        Tuple of (markdown_table_string, total_chars_truncated)
    """
    if not data:
        return "(no data)", 0
    
    total_truncated = 0
    
    # Get column names from first row
    columns = list(data[0].keys())
    
    # Build header row
    header = "| " + " | ".join(str(c) for c in columns) + " |"
    separator = "|" + "|".join(["---" for _ in columns]) + "|"
    
    # Build data rows
    rows = []
    for row in data:
        formatted_values = []
        for col in columns:
            value, truncated = _format_value(row.get(col), max_chars_per_cell)
            total_truncated += truncated
            # Escape pipe characters in values
            value = value.replace("|", "\\|")
            formatted_values.append(value)
        rows.append("| " + " | ".join(formatted_values) + " |")
    
    return "\n".join([header, separator] + rows), total_truncated


def truncate_data_to_tokens(
    data: List[Dict[str, Any]],
    max_tokens: int = 4096,
    chars_per_token: int = 4
) -> tuple:
    """
    Truncate data to fit within a token budget.
    
    Strategy:
    - If data fits, return all of it
    - If too large, keep head rows + last 2 rows (important for ORDER BY issues)
    
    Args:
        data: List of row dictionaries
        max_tokens: Maximum token budget
        chars_per_token: Approximate characters per token (default 4)
        
    Returns:
        Tuple of (head_rows, tail_rows, was_truncated, original_count)
        - head_rows: List of rows from the beginning
        - tail_rows: List of rows from the end (empty if not truncated)
        - was_truncated: Whether truncation occurred
        - original_count: Original number of rows
    """
    if not data:
        return [], [], False, 0
    
    original_count = len(data)
    max_chars = max_tokens * chars_per_token
    
    # Try full data first
    full_str = json.dumps(data, ensure_ascii=False, cls=_JSONEncoder)
    if len(full_str) <= max_chars:
        return data, [], False, original_count
    
    # Need to truncate - keep head + last 2 rows
    tail_count = min(2, original_count)
    tail_rows = data[-tail_count:] if tail_count > 0 else []
    tail_str = json.dumps(tail_rows, ensure_ascii=False, cls=_JSONEncoder)
    
    # Budget for head rows
    head_budget = max_chars - len(tail_str) - 100  # 100 chars buffer
    
    # Find how many head rows fit
    head_rows = []
    current_size = 0
    for i, row in enumerate(data[:-tail_count] if tail_count > 0 else data):
        row_str = json.dumps(row, ensure_ascii=False, cls=_JSONEncoder)
        if current_size + len(row_str) + 10 > head_budget:  # 10 for comma/brackets
            break
        head_rows.append(row)
        current_size += len(row_str) + 2
    
    # Return head and tail separately
    if tail_count > 0 and len(head_rows) < original_count - tail_count:
        return head_rows, tail_rows, True, original_count
    else:
        return head_rows, [], True, original_count


def format_data_with_truncation(
    data: Union[List[Dict[str, Any]], str],
    max_tokens: int = 4096,
    max_tokens_per_cell: int = 64
) -> str:
    """
    Format data as markdown table with token-based truncation.
    
    Args:
        data: List of row dictionaries OR CSV string (new format)
        max_tokens: Maximum token budget for the table
        max_tokens_per_cell: Maximum tokens per cell value (default 64 ≈ 256 chars)
        
    Returns:
        Formatted markdown table string with truncation indicator if needed
    """
    if not data:
        return "(no data)"
    
    # Support CSV string format (new data format)
    if isinstance(data, str):
        try:
            df = pd.read_csv(io.StringIO(data))
            data = df.to_dict('records')
        except Exception:
            return "(invalid CSV data)"
    
    if not data:
        return "(no data)"
    
    max_chars_per_cell = max_tokens_per_cell * 4  # ~4 chars per token
    
    head_rows, tail_rows, was_truncated, original_count = truncate_data_to_tokens(
        data, max_tokens=max_tokens
    )
    
    if not head_rows and not tail_rows:
        return f"(data too large to display, {original_count} rows)"
    
    total_cell_truncated = 0
    
    if not was_truncated:
        # No row truncation, just format all data
        table_str, total_cell_truncated = _format_as_markdown_table(
            head_rows, max_chars_per_cell
        )
    else:
        # Build table with head rows, omission indicator, and tail rows
        columns = list(head_rows[0].keys()) if head_rows else list(tail_rows[0].keys())
        
        # Header
        header = "| " + " | ".join(str(c) for c in columns) + " |"
        separator = "|" + "|".join(["---" for _ in columns]) + "|"
        
        # Head rows
        head_row_strs = []
        for row in head_rows:
            formatted_values = []
            for col in columns:
                value, truncated = _format_value(row.get(col), max_chars_per_cell)
                total_cell_truncated += truncated
                value = value.replace("|", "\\|")
                formatted_values.append(value)
            head_row_strs.append("| " + " | ".join(formatted_values) + " |")
        
        # Calculate omitted rows
        shown = len(head_rows) + len(tail_rows)
        omitted = original_count - shown
        
        # Tail rows
        tail_row_strs = []
        for row in tail_rows:
            formatted_values = []
            for col in columns:
                value, truncated = _format_value(row.get(col), max_chars_per_cell)
                total_cell_truncated += truncated
                value = value.replace("|", "\\|")
                formatted_values.append(value)
            tail_row_strs.append("| " + " | ".join(formatted_values) + " |")
        
        # Combine with omission indicator
        parts = [header, separator] + head_row_strs
        if omitted > 0:
            parts.append(f"... ({omitted} rows omitted)")
        parts.extend(tail_row_strs)
        
        table_str = "\n".join(parts)
        
        # Add summary line
        total_chars_truncated = total_cell_truncated
        # Estimate chars in omitted rows
        if omitted > 0 and head_rows:
            avg_row_size = len(json.dumps(head_rows[0], ensure_ascii=False, cls=_JSONEncoder))
            total_chars_truncated += omitted * avg_row_size
        
        table_str += f"\n\n({omitted} rows omitted, showing {shown} of {original_count} total. ~{total_chars_truncated:,} chars truncated)"
    
    return table_str


# ============================================================================
# General Message Builder
# ============================================================================

def build_messages(
    user_message: str,
    system_prompt: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Build standard message format for LLM APIs.
    
    General-purpose function that accepts any user message string.
    
    Args:
        user_message: The user's message (any string)
        system_prompt: Optional system prompt. If None, no system message is added
        
    Returns:
        List of message dicts in standard format suitable for any LLM API
        
    Example:
        >>> # Simple case
        >>> messages = build_messages(
        >>>     user_message="What is 2+2?",
        >>>     system_prompt="You are a helpful assistant"
        >>> )
        >>> 
        >>> # With history (build it yourself)
        >>> messages = [
        >>>     {"role": "system", "content": "You are helpful"},
        >>>     {"role": "user", "content": "What is 2+2?"},
        >>>     {"role": "assistant", "content": "4"},
        >>>     {"role": "user", "content": "What about 3+3?"}
        >>> ]
        >>> response = client.query(messages)
        >>> 
        >>> # For SQL conversion task, use format_sql_conversion_input first
        >>> user_input = format_sql_conversion_input(instruction="...", sql_query="...")
        >>> messages = build_messages(
        >>>     user_message=user_input,
        >>>     system_prompt=SQL_CONVERTER_SYSTEM_PROMPT
        >>> )
    """
    messages = []
    
    # Add system prompt if provided
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    
    # Add user message
    messages.append({"role": "user", "content": user_message})
    
    return messages


# ============================================================================
# Task-Specific Input Formatters
# ============================================================================

def format_sql_conversion_input(
    instruction: str,
    sql_query: str,
    result: Dict[str, Any],
    schema_content: str,
    db_id: Optional[str] = None,
    external_knowledge: Optional[str] = None,
    diversity_hint: bool = False
) -> str:
    """
    Format inputs for SQL conversion task into a user message string.
    
    This is a task-specific formatter. Use with build_messages().
    
    Args:
        instruction: Original natural language instruction
        sql_query: Original SQL query
        result: Execution result dict with 'num_rows', 'num_columns', 'data'
        schema_content: Formatted database schema
        db_id: Optional database ID (for display)
        external_knowledge: Optional external knowledge content
        diversity_hint: If True, prepend diversity requirement to encourage
            underrepresented AI functions (AI_SENTIMENT, AI_EXTRACT, AI_AGG)
            
    Returns:
        Formatted user message string ready for build_messages()
        
    Example:
        >>> user_input = format_sql_conversion_input(
        >>>     instruction="Count all patents",
        >>>     sql_query="SELECT COUNT(*) FROM patents",
        >>>     result={'num_rows': 1, 'num_columns': 1, 'data': [...]},
        >>>     schema_content="..."
        >>> )
        >>> messages = build_messages(
        >>>     user_message=user_input,
        >>>     system_prompt=SQL_CONVERTER_SYSTEM_PROMPT
        >>> )
    """
    
    # Format execution result as markdown table (token-based truncation).
    if result:
        result_header = (
            f"The original query returned {result.get('num_rows', 0)} row(s) "
            f"with {result.get('num_columns', 0)} column(s)."
        )
        result_table = ""
        if result.get('data'):
            table_str = format_data_with_truncation(
                result['data'],
                max_tokens=4096,
                max_tokens_per_cell=64
            )
            result_table = f"""
Sample output:
{table_str}"""
    else:
        result_header = "No execution result was provided for the original query."
        result_table = ""
    
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
    user_message = f"""{diversity_section}<original_instruction>
{instruction}
</original_instruction>

<gold_sql>
```sql
{sql_query}
```
</gold_sql>

<execution_result>
{result_header}
{result_table}
</execution_result>

<database_schema>
{schema_content}
</database_schema>
{knowledge_section}"""
    
    return user_message.strip()


def format_execution_feedback(
    execution_result: Dict[str, Any],
    include_data_sample: bool = True,
    max_tokens: int = 4096,
    max_tokens_per_cell: int = 64,
    current_round: Optional[int] = None,
    max_rounds: Optional[int] = None
) -> str:
    """
    Format execution result as feedback for the agent.
    
    Args:
        execution_result: Result from SQL execution (from SnowflakeExecutor)
        include_data_sample: Whether to include sample data
        max_tokens: Maximum token budget for the data sample
        max_tokens_per_cell: Maximum tokens per cell value
        current_round: Current round number (optional, for progress tracking)
        max_rounds: Maximum rounds allowed (optional, for progress tracking)
        
    Returns:
        Formatted feedback string for agent
        
    Example:
        >>> feedback = format_execution_feedback(exec_result, current_round=3, max_rounds=10)
        >>> messages.append({"role": "user", "content": feedback})
    """
    # Build round progress info if provided (separate from execution feedback)
    round_progress = ""
    if current_round is not None and max_rounds is not None:
        remaining = max_rounds - current_round
        round_progress = f"<round_progress>\nRound {current_round} of {max_rounds} ({remaining} remaining)"
        if remaining <= 3:
            round_progress += "\n Approaching limit - consider concluding if results are acceptable"
        round_progress += "\n</round_progress>\n\n"
    
    if execution_result['status'] == 'success':
        feedback = f"""{round_progress}<execution_feedback>
Status: SUCCESS
Execution Time: {execution_result.get('execution_time', 0):.2f}s
Rows Returned: {execution_result.get('num_rows', 0)}
Columns: {execution_result.get('num_columns', 0)}"""
        
        # Add sample data if available and requested
        if include_data_sample and execution_result.get('data'):
            table_str = format_data_with_truncation(
                execution_result['data'], 
                max_tokens=max_tokens,
                max_tokens_per_cell=max_tokens_per_cell
            )
            feedback += f"""

Sample Data:
{table_str}"""
        
        feedback += "\n</execution_feedback>"
        
    else:
        # Execution failed
        error_msg = execution_result.get('error', 'Unknown error')
        
        # Try to categorize error type
        error_type = "RUNTIME_ERROR"
        if "syntax" in error_msg.lower() or "parse" in error_msg.lower():
            error_type = "SYNTAX_ERROR"
        elif "does not exist" in error_msg.lower() or "not found" in error_msg.lower():
            error_type = "OBJECT_NOT_FOUND"
        elif "permission" in error_msg.lower() or "access" in error_msg.lower():
            error_type = "PERMISSION_ERROR"
        
        feedback = f"""{round_progress}<execution_feedback>
Status: FAILED
Error Type: {error_type}
Error Message: {error_msg}
</execution_feedback>"""
    
    return feedback
