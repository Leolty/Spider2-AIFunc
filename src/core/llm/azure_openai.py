"""
Azure OpenAI client implementation.
"""
import os
import time
import random
from typing import Optional, List, Dict, Any, Union
from openai import AzureOpenAI, RateLimitError, APIError, APIConnectionError, APITimeoutError
from .base import BaseLLMClient

# Errors that should NOT be retried (permanent errors)
NON_RETRYABLE_STATUS_CODES = {
    400,  # Bad Request - malformed request
    401,  # Unauthorized - bad API key
    403,  # Forbidden - no permission
    404,  # Not Found - wrong endpoint/model
    422,  # Unprocessable Entity - invalid request content
}


def retry_with_exponential_backoff(
    max_retries: int = 5,
    initial_delay: float = 10.0,
    max_delay: float = 120.0,
    exponential_base: float = 2.0,
    jitter: bool = True
):
    """
    Decorator for retrying a function with exponential backoff on transient errors.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            num_retries = 0
            delay = initial_delay
            
            while True:
                try:
                    return func(*args, **kwargs)
                    
                except RateLimitError as e:
                    num_retries += 1
                    if num_retries > max_retries:
                        print(f"[Retry] Max retries ({max_retries}) exceeded. Raising error.")
                        raise
                    
                    delay = min(delay * exponential_base, max_delay)
                    if jitter:
                        delay = delay * (0.5 + random.random())
                    
                    print(f"[Retry] Rate limit (429). Waiting {delay:.1f}s before retry {num_retries}/{max_retries}...")
                    time.sleep(delay)
                
                except (APIConnectionError, APITimeoutError) as e:
                    num_retries += 1
                    if num_retries > max_retries:
                        print(f"[Retry] Max retries ({max_retries}) exceeded. Raising error.")
                        raise
                    
                    delay = min(delay * exponential_base, max_delay)
                    if jitter:
                        delay = delay * (0.5 + random.random())
                    
                    error_type = type(e).__name__
                    print(f"[Retry] {error_type}. Waiting {delay:.1f}s before retry {num_retries}/{max_retries}...")
                    time.sleep(delay)
                    
                except APIError as e:
                    status_code = getattr(e, 'status_code', None)
                    
                    if status_code in NON_RETRYABLE_STATUS_CODES:
                        raise
                    
                    num_retries += 1
                    if num_retries > max_retries:
                        print(f"[Retry] Max retries ({max_retries}) exceeded. Raising error.")
                        raise
                    
                    delay = min(delay * exponential_base, max_delay)
                    if jitter:
                        delay = delay * (0.5 + random.random())
                    
                    print(f"[Retry] API error ({status_code}). Waiting {delay:.1f}s before retry {num_retries}/{max_retries}...")
                    time.sleep(delay)
                    
                except Exception as e:
                    error_str = str(e).lower()
                    is_transient = any(keyword in error_str for keyword in [
                        'timeout', 'timed out', 'connection', 'network', 
                        'temporary', 'unavailable', 'overloaded', 'capacity',
                        'reset by peer', 'broken pipe', 'eof'
                    ])
                    
                    if not is_transient:
                        raise
                    
                    num_retries += 1
                    if num_retries > max_retries:
                        print(f"[Retry] Max retries ({max_retries}) exceeded. Raising error.")
                        raise
                    
                    delay = min(delay * exponential_base, max_delay)
                    if jitter:
                        delay = delay * (0.5 + random.random())
                    
                    print(f"[Retry] Transient error: {type(e).__name__}. Waiting {delay:.1f}s before retry {num_retries}/{max_retries}...")
                    time.sleep(delay)
                    
        return wrapper
    return decorator


class AzureOpenAIClient(BaseLLMClient):
    """Client for Azure OpenAI models (GPT-4, GPT-5, etc.)."""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        api_version: Optional[str] = None,
        model_name: str = "gpt-5",
        deployment: Optional[str] = None,
    ):
        """
        Initialize Azure OpenAI client.
        
        Args:
            api_key: Azure OpenAI API key (defaults to env var AZURE_OPENAI_API_KEY or OPENAI_API_KEY)
            endpoint: Azure OpenAI endpoint URL (defaults to env var AZURE_OPENAI_ENDPOINT)
            api_version: API version (defaults to env var AZURE_OPENAI_API_VERSION or "2024-12-01-preview")
            model_name: Model name (e.g., "gpt-4", "gpt-5")
            deployment: Deployment name (defaults to model_name if not provided)
        """
        # Get API key from parameter or environment
        self.api_key = api_key or os.getenv('AZURE_OPENAI_API_KEY') or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError(
                "Azure OpenAI API key must be provided via parameter or "
                "AZURE_OPENAI_API_KEY/OPENAI_API_KEY environment variable"
            )
        
        # Get endpoint from parameter or environment
        self.endpoint = endpoint or os.getenv('AZURE_OPENAI_ENDPOINT')
        
        # Get API version from parameter or environment
        self.api_version = api_version or os.getenv('AZURE_OPENAI_API_VERSION', 
                                                     '2024-12-01-preview')
        
        self._model_name = model_name
        self.deployment = deployment or model_name
        
        # Initialize Azure OpenAI client
        self.client = AzureOpenAI(
            api_version=self.api_version,
            azure_endpoint=self.endpoint,
            api_key=self.api_key,
        )
    
    def query(
        self,
        messages: Union[str, List[Dict[str, str]]],
        max_tokens: int = 16384,
        temperature: Optional[float] = None,
        system: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Query Azure OpenAI with messages.
        
        Note: GPT-5 doesn't support temperature/top_p parameters.
        """
        # Build messages list
        if isinstance(messages, str):
            # Simple string: convert to user message with optional system
            messages_list = []
            if system:
                messages_list.append({"role": "system", "content": system})
            messages_list.append({"role": "user", "content": messages})
        elif isinstance(messages, list):
            # Already in correct format
            messages_list = messages
        else:
            raise ValueError(f"messages must be str or List[Dict], got {type(messages)}")
        
        # Build parameters
        params = {
            "messages": messages_list,
            "max_completion_tokens": max_tokens,
            "model": self.deployment
        }
        
        # Only add temperature for non-GPT-5 models
        if temperature is not None and "gpt-5" not in self._model_name.lower():
            params["temperature"] = temperature
            if "top_p" in kwargs:
                params["top_p"] = kwargs.pop("top_p")
        
        # Add any additional kwargs
        params.update(kwargs)
        
        return self._call_api_with_retry(params)
    
    @retry_with_exponential_backoff(max_retries=5, initial_delay=10.0, max_delay=120.0)
    def _call_api_with_retry(self, params: dict) -> str:
        """Call the API with retry logic for rate limits."""
        response = self.client.chat.completions.create(**params)
        return response.choices[0].message.content
    
    def query_with_metadata(
        self,
        user_message: str,
        system_message: str = "You are a helpful assistant.",
        conversation_history: Optional[List[Dict[str, str]]] = None,
        max_tokens: int = 16384,
        temperature: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Query Azure OpenAI and return full response with metadata.
        """
        messages = [{"role": "system", "content": system_message}]
        
        if conversation_history:
            messages.extend(conversation_history)
        
        messages.append({"role": "user", "content": user_message})
        
        # Build parameters
        params = {
            "messages": messages,
            "max_completion_tokens": max_tokens,
            "model": self.deployment
        }
        
        # Only add temperature for non-GPT-5 models
        if temperature is not None and "gpt-5" not in self._model_name.lower():
            params["temperature"] = temperature
            if "top_p" in kwargs:
                params["top_p"] = kwargs.pop("top_p")
        
        # Add any additional kwargs
        params.update(kwargs)
        
        response = self._call_api_with_retry_full(params)
        
        return {
            'content': response.choices[0].message.content,
            'role': response.choices[0].message.role,
            'finish_reason': response.choices[0].finish_reason,
            'usage': {
                'prompt_tokens': response.usage.prompt_tokens,
                'completion_tokens': response.usage.completion_tokens,
                'total_tokens': response.usage.total_tokens
            },
            'model': response.model,
            'created': response.created,
            'provider': self.provider
        }
    
    @retry_with_exponential_backoff(max_retries=5, initial_delay=10.0, max_delay=120.0)
    def _call_api_with_retry_full(self, params: dict):
        """Call the API with retry logic. Returns full response."""
        return self.client.chat.completions.create(**params)
    
    @property
    def model_name(self) -> str:
        """Return the current model name."""
        return self._model_name
    
    @property
    def provider(self) -> str:
        """Return the provider name."""
        return "azure_openai"


def quick_query(
    prompt: str,
    system_message: str = "You are a helpful assistant.",
    **kwargs
) -> str:
    """
    Quick query function for simple use cases.
    
    Args:
        prompt: The user prompt
        system_message: System message
        **kwargs: Additional parameters for query()
        
    Returns:
        The LLM's response
    """
    client = AzureOpenAIClient()
    return client.query(prompt, system=system_message, **kwargs)


if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python azure_openai.py '<your prompt>'")
        print("Make sure AZURE_OPENAI_API_KEY or OPENAI_API_KEY is set in environment")
        sys.exit(1)
    
    prompt = sys.argv[1]
    response = quick_query(prompt)
    print(response)
