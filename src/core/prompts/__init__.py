"""
Prompt templates and message builders.

Main API:
    - build_messages(): General-purpose message builder (accepts any string)
    - format_sql_conversion_input(): Task-specific formatter for SQL conversion

Example 1: Simple usage
    >>> from src.core.prompts import build_messages
    >>> 
    >>> messages = build_messages(
    >>>     user_message="What is 2+2?",
    >>>     system_prompt="You are a helpful assistant"
    >>> )

Example 2: With history (build it yourself)
    >>> messages = [
    >>>     {"role": "system", "content": "You are helpful"},
    >>>     {"role": "user", "content": "What is 2+2?"},
    >>>     {"role": "assistant", "content": "4"},
    >>>     {"role": "user", "content": "What about 3+3?"}
    >>> ]
    >>> response = client.query(messages)

Example 3: SQL conversion task
    >>> from src.core.prompts import (
    >>>     build_messages,
    >>>     format_sql_conversion_input,
    >>>     SQL_CONVERTER_SYSTEM_PROMPT
    >>> )
    >>> 
    >>> # Format task-specific input
    >>> user_input = format_sql_conversion_input(
    >>>     instruction="Count all patents",
    >>>     sql_query="SELECT COUNT(*) FROM patents",
    >>>     result={'num_rows': 1, 'num_columns': 1, 'data': [...]},
    >>>     schema_content="..."
    >>> )
    >>> 
    >>> # Build messages
    >>> messages = build_messages(
    >>>     user_message=user_input,
    >>>     system_prompt=SQL_CONVERTER_SYSTEM_PROMPT
    >>> )
    >>> 
    >>> # Use with any LLM API
    >>> response = llm_client.query(
    >>>     system_message=messages[0]['content'],
    >>>     user_message=messages[1]['content']
    >>> )
"""

# Main API
from .builders import (
    build_messages,
    format_sql_conversion_input,
    format_execution_feedback,
    truncate_data_to_tokens,
    format_data_with_truncation,
)

# System prompt constants
from .system_prompts import SQL_CONVERTER_SYSTEM_PROMPT, AGENT_SYSTEM_PROMPT

# Common components (can be reused to build custom system prompts)
from .common import (
    AI_FUNCTIONS_REFERENCE,
    DETERMINISM_REQUIREMENTS,
    MODIFICATION_APPROACHES,
)

# Determinism check prompts
from .determinism_prompts import (
    SYSTEM_PROMPT as DETERMINISM_SYSTEM_PROMPT,
    format_initial_input as format_determinism_input,
    format_execution_results,
)

# Multi-SQL agent prompts
from .multi_sql_prompts import (
    MULTI_SQL_AGENT_SYSTEM_PROMPT,
    MULTI_SQL_SECTION,
    format_multi_sql_input,
)


__all__ = [
    # Main API
    "build_messages",
    "format_sql_conversion_input",
    "format_execution_feedback",
    "truncate_data_to_tokens",
    "format_data_with_truncation",
    
    # System prompts
    "SQL_CONVERTER_SYSTEM_PROMPT",
    "AGENT_SYSTEM_PROMPT",
    
    # Common components
    "AI_FUNCTIONS_REFERENCE",
    "DETERMINISM_REQUIREMENTS",
    "MODIFICATION_APPROACHES",
    
    # Determinism check prompts
    "DETERMINISM_SYSTEM_PROMPT",
    "format_determinism_input",
    "format_execution_results",
    
    # Multi-SQL agent prompts
    "MULTI_SQL_AGENT_SYSTEM_PROMPT",
    "MULTI_SQL_SECTION",
    "format_multi_sql_input",
]

