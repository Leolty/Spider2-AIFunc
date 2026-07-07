"""
LLM Factory for creating appropriate LLM clients based on configuration.
"""
import os
from typing import Optional, Dict, Any
from .base import BaseLLMClient
from .azure_openai import AzureOpenAIClient
from .aws_bedrock import AWSBedrockClient
from .openai_client import OpenAICompatibleClient


class LLMFactory:
    """Factory for creating LLM clients based on provider configuration."""
    
    # Default models for each provider
    DEFAULT_MODELS = {
        "azure_openai": "gpt-5",
        "aws_bedrock": "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "openai": "gpt-4o",
    }
    
    @staticmethod
    def create_client(provider: str, **config) -> BaseLLMClient:
        """
        Create an LLM client for the specified provider.
        
        Args:
            provider: Provider name ("openai", "aws_bedrock", or "azure_openai")
            **config: Provider-specific configuration parameters
            
        Returns:
            An initialized LLM client
            
        Raises:
            ValueError: If provider is unknown
            
        Examples:
            # OpenAI or any OpenAI-compatible API
            client = LLMFactory.create_client(
                "openai",
                api_key="your-key",
                base_url="https://api.openai.com/v1",
                model_name="gpt-4o"
            )

            # AWS Bedrock
            client = LLMFactory.create_client(
                "aws_bedrock",
                access_key="your-access-key",
                secret_key="your-secret-key",
                model_id="anthropic.claude-3-5-sonnet-20241022-v2:0"
            )
            
            # Snowflake Cortex through the OpenAI-compatible API path
            client = LLMFactory.create_client(
                "openai",
                api_key="your-key",
                base_url="https://<your-account>.snowflakecomputing.com/api/v2/cortex/v1",
                model_name="claude-sonnet-4-5"
            )
        """
        provider = provider.lower()
        
        if provider == "azure_openai":
            return AzureOpenAIClient(**config)
        elif provider == "aws_bedrock":
            return AWSBedrockClient(**config)
        elif provider == "openai":
            # Set default model if not provided
            if 'model_name' not in config:
                config['model_name'] = LLMFactory.DEFAULT_MODELS['openai']
            return OpenAICompatibleClient(provider_name="openai", **config)
        else:
            raise ValueError(
                f"Unknown provider: {provider}. "
                f"Supported providers: openai, aws_bedrock, azure_openai"
            )
    
    @staticmethod
    def create_from_env() -> BaseLLMClient:
        """
        Create an LLM client automatically from environment variables.
        
        Reads the LLM_PROVIDER environment variable to determine which provider to use,
        then reads provider-specific configuration from environment variables.
        
        Environment Variables:
            LLM_PROVIDER: "openai", "aws_bedrock", or "azure_openai" (default: "openai")

            For OpenAI-compatible APIs (OpenAI, OpenRouter, Snowflake Cortex, Ollama, vLLM):
            - OPENAI_API_KEY
            - OPENAI_BASE_URL (optional, default OpenAI endpoint if unset)
            - OPENAI_MODEL (optional, default: "gpt-4o")
            
            For AWS Bedrock:
            - AWS_ACCESS_KEY
            - AWS_SECRET_KEY
            - AWS_REGION (optional, default: "us-east-1")
            - AWS_BEDROCK_MODEL (optional, default: "anthropic.claude-3-5-sonnet-20241022-v2:0")
            
            Azure OpenAI is still supported by code for existing users:
            - AZURE_OPENAI_API_KEY or OPENAI_API_KEY
            - AZURE_OPENAI_ENDPOINT
            - AZURE_OPENAI_API_VERSION (optional)
            - AZURE_OPENAI_MODEL (optional, default: "gpt-5")
        
        Returns:
            An initialized LLM client
            
        Raises:
            ValueError: If required environment variables are missing
            
        Example:
            # For Snowflake Cortex:
            export LLM_PROVIDER=openai
            export OPENAI_API_KEY=your-snowflake-pat
            export OPENAI_BASE_URL=https://<your-account>.snowflakecomputing.com/api/v2/cortex/v1
            export OPENAI_MODEL=claude-sonnet-4-5
            
            client = LLMFactory.create_from_env()
            response = client.query("What is 2+2?")
        """
        provider = os.getenv('LLM_PROVIDER', 'openai').lower()
        
        if provider == "azure_openai":
            config = {
                'api_key': os.getenv('AZURE_OPENAI_API_KEY') or os.getenv('OPENAI_API_KEY'),
                'endpoint': os.getenv('AZURE_OPENAI_ENDPOINT'),
                'api_version': os.getenv('AZURE_OPENAI_API_VERSION'),
                'model_name': os.getenv('AZURE_OPENAI_MODEL', 
                                       LLMFactory.DEFAULT_MODELS['azure_openai']),
            }
            # Remove None values
            config = {k: v for k, v in config.items() if v is not None}
            return AzureOpenAIClient(**config)
            
        elif provider == "aws_bedrock":
            config = {
                'access_key': os.getenv('AWS_ACCESS_KEY'),
                'secret_key': os.getenv('AWS_SECRET_KEY'),
                'region': os.getenv('AWS_REGION'),
                'model_id': os.getenv('AWS_BEDROCK_MODEL', 
                                     LLMFactory.DEFAULT_MODELS['aws_bedrock']),
            }
            # Remove None values (except model_id which has a default)
            config = {k: v for k, v in config.items() if v is not None}
            return AWSBedrockClient(**config)
        
        elif provider == "openai":
            config = {
                'api_key': os.getenv('OPENAI_API_KEY'),
                'base_url': os.getenv('OPENAI_BASE_URL'),
                'model_name': os.getenv('OPENAI_MODEL',
                                       LLMFactory.DEFAULT_MODELS['openai']),
            }
            config = {k: v for k, v in config.items() if v is not None}
            return OpenAICompatibleClient(provider_name="openai", **config)
            
        else:
            raise ValueError(
                f"Unknown LLM_PROVIDER: {provider}. "
                f"Supported: openai, aws_bedrock, azure_openai"
            )
    
    @staticmethod
    def get_available_providers() -> Dict[str, str]:
        """
        Get a list of available providers and their default models.
        
        Returns:
            Dictionary mapping provider names to default models
        """
        return LLMFactory.DEFAULT_MODELS.copy()


if __name__ == "__main__":
    # Test factory
    print("🏭 LLM Factory")
    print("=" * 60)
    
    providers = LLMFactory.get_available_providers()
    print(f"Available providers: {len(providers)}")
    for provider, model in providers.items():
        print(f"  • {provider}: {model}")
    
    print()
    print("Testing environment-based client creation...")
    
    try:
        client = LLMFactory.create_from_env()
        print(f"✅ Created {client.provider} client")
        print(f"   Model: {client.model_name}")
    except Exception as e:
        print(f"⚠️  Could not create client: {e}")
        print("   Make sure environment variables are set correctly")
