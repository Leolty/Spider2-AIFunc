"""
OpenAI-compatible client implementation.

Supports any OpenAI-compatible API including:
- OpenAI API
- Snowflake Cortex
- Ollama
- vLLM
- Together AI
- etc.
"""
import os
import time
import random
from typing import Optional, List, Dict, Any, Union
from openai import OpenAI, RateLimitError, APIError, APIConnectionError, APITimeoutError
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
    
    Retries on:
    - Rate limit errors (429)
    - Server errors (5xx)
    - Connection errors (network issues)
    - Timeout errors
    
    Does NOT retry on:
    - 400 Bad Request
    - 401 Unauthorized  
    - 403 Forbidden
    - 404 Not Found
    - 422 Unprocessable Entity
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
                    # Network/timeout errors - always retry
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
                    
                    # Don't retry permanent errors
                    if status_code in NON_RETRYABLE_STATUS_CODES:
                        raise
                    
                    # Retry on 5xx or unknown errors
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
                    # Catch-all for other transient errors (e.g., JSON decode errors from partial response)
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


class OpenAICompatibleClient(BaseLLMClient):
    """Client for OpenAI-compatible APIs."""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: str = "gpt-4o",
        provider_name: str = "openai",
    ):
        """
        Initialize OpenAI-compatible client.
        
        Args:
            api_key: API key (defaults to env var OPENAI_API_KEY)
            base_url: Base URL for the API (None for standard OpenAI)
            model_name: Model name (e.g., "gpt-4o", "claude-sonnet-4-5")
            provider_name: Provider identifier for logging/tracking
        """
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError(
                "API key must be provided via parameter or OPENAI_API_KEY environment variable"
            )
        
        self.base_url = base_url
        self._model_name = model_name
        self._provider_name = provider_name
        
        # Initialize OpenAI client
        client_kwargs = {"api_key": self.api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        
        self.client = OpenAI(**client_kwargs)
    
    def query(
        self,
        messages: Union[str, List[Dict[str, str]]],
        max_tokens: int = 16384,
        temperature: Optional[float] = None,
        system: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Query the OpenAI-compatible API with messages.
        """
        # Build messages list
        if isinstance(messages, str):
            messages_list = []
            if system:
                messages_list.append({"role": "system", "content": system})
            messages_list.append({"role": "user", "content": messages})
        elif isinstance(messages, list):
            messages_list = messages
        else:
            raise ValueError(f"messages must be str or List[Dict], got {type(messages)}")
        
        # Build parameters
        params = {
            "messages": messages_list,
            "max_completion_tokens": max_tokens,
            "model": self._model_name
        }
        
        # Add temperature if provided
        if temperature is not None:
            params["temperature"] = temperature
        
        # Add any additional kwargs
        if "top_p" in kwargs:
            params["top_p"] = kwargs.pop("top_p")
        
        params.update(kwargs)
        
        # Call with retry wrapper
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
        Query the API and return full response with metadata.
        """
        messages = [{"role": "system", "content": system_message}]
        
        if conversation_history:
            messages.extend(conversation_history)
        
        messages.append({"role": "user", "content": user_message})
        
        # Build parameters
        params = {
            "messages": messages,
            "max_completion_tokens": max_tokens,
            "model": self._model_name
        }
        
        if temperature is not None:
            params["temperature"] = temperature
        
        if "top_p" in kwargs:
            params["top_p"] = kwargs.pop("top_p")
        
        params.update(kwargs)
        
        # Call with retry wrapper
        response = self._call_api_with_retry_full(params)
        
        # Handle usage - some providers may not return all fields
        usage = {}
        if response.usage:
            usage = {
                'prompt_tokens': getattr(response.usage, 'prompt_tokens', 0),
                'completion_tokens': getattr(response.usage, 'completion_tokens', 0),
                'total_tokens': getattr(response.usage, 'total_tokens', 0)
            }
        
        return {
            'content': response.choices[0].message.content,
            'role': response.choices[0].message.role,
            'finish_reason': response.choices[0].finish_reason,
            'usage': usage,
            'model': response.model,
            'created': response.created,
            'provider': self.provider
        }
    
    @retry_with_exponential_backoff(max_retries=5, initial_delay=10.0, max_delay=120.0)
    def _call_api_with_retry_full(self, params: dict):
        """Call the API with retry logic for rate limits. Returns full response."""
        return self.client.chat.completions.create(**params)
    
    @property
    def model_name(self) -> str:
        """Return the current model name."""
        return self._model_name
    
    @property
    def provider(self) -> str:
        """Return the provider name."""
        return self._provider_name


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python openai_client.py '<your prompt>'")
        print("Make sure OPENAI_API_KEY is set in environment")
        sys.exit(1)
    
    prompt = sys.argv[1]
    client = OpenAICompatibleClient()
    response = client.query(prompt)
    print(response)
