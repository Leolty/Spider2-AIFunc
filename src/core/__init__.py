"""
Core reusable components for AI SQL Builder.

This module provides all the essential building blocks:
- paths: Automatic project path detection
- prompts: Prompt template storage
- llm: LLM clients (OpenAI-compatible APIs, AWS Bedrock, legacy Azure OpenAI)
- database: Database schema operations
- parser: LLM response parsing
- sql_executor: Snowflake SQL execution

Example usage:
    from src.core import paths, LLMFactory, build_messages
    
    # Use auto-detected paths
    print(f"Project root: {paths.PROJECT_ROOT}")
    
    # Create LLM client from environment
    llm = LLMFactory.create_from_env()
    
    # Build a prompt
    messages = build_messages(user_message="Hello", system_prompt="You are helpful")
"""

# Auto-detected paths
from . import paths

# Prompt templates and assembly
from .prompts import (
    build_messages,
    format_sql_conversion_input,
    SQL_CONVERTER_SYSTEM_PROMPT,
    AI_FUNCTIONS_REFERENCE,
    DETERMINISM_REQUIREMENTS
)

# LLM clients are loaded lazily (see __getattr__ below), so code that only needs SQL
# execution, comparison, or prompts (for example the evaluator) does not require the LLM
# SDKs (openai, boto3) to be installed.

# Database operations
from .database import (
    DatabaseMapper,
    SchemaLoader,
    SchemaFormatter,
    load_external_knowledge
)

# Response parsing
from .parser import LLMResponseParser

# SQL execution
from .sql_executor import (
    SnowflakeExecutor,
    ExecutionResult,
    execute_sql_simple
)

# Result comparison (for evaluation and determinism checking)
from .comparison import (
    compare_pandas_table,
    check_execution_consistency,
    EvalConfig,
    ConsistencyResult
)

_LAZY_LLM = {
    "BaseLLMClient",
    "OpenAICompatibleClient",
    "AzureOpenAIClient",
    "AWSBedrockClient",
    "LLMFactory",
}


def __getattr__(name):
    """Lazily import the LLM clients so importing src.core does not require the LLM SDKs."""
    if name in _LAZY_LLM:
        from . import llm
        return getattr(llm, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Paths module
    'paths',
    
    # Prompts
    'build_messages',
    'format_sql_conversion_input',
    'SQL_CONVERTER_SYSTEM_PROMPT',
    'AI_FUNCTIONS_REFERENCE',
    'DETERMINISM_REQUIREMENTS',
    
    # LLM
    'BaseLLMClient',
    'OpenAICompatibleClient',
    'AzureOpenAIClient',
    'AWSBedrockClient',
    'LLMFactory',
    
    # Database
    'DatabaseMapper',
    'SchemaLoader',
    'SchemaFormatter',
    'load_external_knowledge',
    
    # Parsing
    'LLMResponseParser',
    
    # SQL execution
    'SnowflakeExecutor',
    'ExecutionResult',
    'execute_sql_simple',
    
    # Comparison
    'compare_pandas_table',
    'check_execution_consistency',
    'EvalConfig',
    'ConsistencyResult',
]
