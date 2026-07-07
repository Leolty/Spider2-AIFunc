"""
AWS Bedrock Claude client implementation.
"""
import os
import json
import time
import random
from typing import Optional, List, Dict, Any, Union
from .base import BaseLLMClient


# AWS errors that should NOT be retried (permanent errors)
NON_RETRYABLE_ERROR_CODES = {
    'ValidationException',      # Bad request format
    'AccessDeniedException',    # No permission
    'ResourceNotFoundException', # Model not found
    'InvalidRequestException',  # Invalid request
}

# AWS errors that SHOULD be retried (transient errors)
RETRYABLE_ERROR_CODES = {
    'ThrottlingException',
    'TooManyRequestsException', 
    'ServiceQuotaExceededException',
    'ModelStreamErrorException',
    'InternalServerException',
    'ServiceUnavailableException',
    'ModelTimeoutException',
    'ModelErrorException',  # Sometimes transient
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
    - Throttling/rate limit errors
    - Server errors (5xx equivalent)
    - Timeout errors
    - Connection errors
    
    Does NOT retry on:
    - ValidationException (bad request)
    - AccessDeniedException (permission)
    - ResourceNotFoundException (wrong model)
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError
            
            num_retries = 0
            delay = initial_delay
            
            while True:
                try:
                    return func(*args, **kwargs)
                    
                except ClientError as e:
                    error_code = e.response.get('Error', {}).get('Code', '')
                    
                    # Don't retry permanent errors
                    if error_code in NON_RETRYABLE_ERROR_CODES:
                        raise
                    
                    # Retry known transient errors
                    if error_code in RETRYABLE_ERROR_CODES:
                        num_retries += 1
                        if num_retries > max_retries:
                            print(f"[Retry] Max retries ({max_retries}) exceeded. Raising error.")
                            raise
                        
                        delay = min(delay * exponential_base, max_delay)
                        if jitter:
                            delay = delay * (0.5 + random.random())
                        
                        print(f"[Retry] {error_code}. Waiting {delay:.1f}s before retry {num_retries}/{max_retries}...")
                        time.sleep(delay)
                        continue
                    
                    # For unknown errors, check if it looks transient
                    error_msg = str(e).lower()
                    is_transient = any(kw in error_msg for kw in ['timeout', 'unavailable', 'capacity', 'overload'])
                    if is_transient:
                        num_retries += 1
                        if num_retries > max_retries:
                            raise
                        delay = min(delay * exponential_base, max_delay)
                        if jitter:
                            delay = delay * (0.5 + random.random())
                        print(f"[Retry] Unknown transient error ({error_code}). Waiting {delay:.1f}s before retry {num_retries}/{max_retries}...")
                        time.sleep(delay)
                        continue
                    
                    raise
                
                except (EndpointConnectionError, ReadTimeoutError) as e:
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
                    
                except Exception as e:
                    # Catch-all for other transient errors
                    error_str = str(e).lower()
                    is_transient = any(keyword in error_str for keyword in [
                        'throttl', 'rate', '429', 'timeout', 'timed out', 
                        'connection', 'network', 'temporary', 'unavailable', 
                        'overloaded', 'capacity', 'reset by peer', 'broken pipe'
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


class AWSBedrockClient(BaseLLMClient):
    """Client for AWS Bedrock Claude models."""
    
    def __init__(
        self,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        region: Optional[str] = None,
        model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
    ):
        """
        Initialize AWS Bedrock Claude client.
        
        Args:
            access_key: AWS access key (defaults to env var AWS_ACCESS_KEY)
            secret_key: AWS secret key (defaults to env var AWS_SECRET_KEY)
            region: AWS region (defaults to env var AWS_REGION or "us-east-1")
            model_id: Bedrock model ID (e.g., "anthropic.claude-3-5-sonnet-20241022-v2:0")
        """
        # Import boto3 only when this client is used
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "boto3 is required for AWS Bedrock. Install it with: pip install boto3"
            )
        
        # Get credentials from parameters or environment
        self.access_key = access_key or os.getenv('AWS_ACCESS_KEY')
        self.secret_key = secret_key or os.getenv('AWS_SECRET_KEY')
        self.region = region or os.getenv('AWS_REGION', 'us-east-1')
        self._model_id = model_id
        
        if not self.access_key or not self.secret_key:
            raise ValueError(
                "AWS credentials must be provided via parameters or "
                "AWS_ACCESS_KEY/AWS_SECRET_KEY environment variables"
            )
        
        # Initialize Bedrock runtime client
        self.bedrock = boto3.client(
            service_name='bedrock-runtime',
            region_name=self.region,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key
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
        Query AWS Bedrock Claude with messages.
        """
        # Build messages list and extract system
        if isinstance(messages, str):
            # Simple string: convert to user message
            messages_list = [{"role": "user", "content": messages}]
            system_msg = system or "You are a helpful assistant."
        elif isinstance(messages, list):
            # Extract system message if present (Claude uses separate system parameter)
            system_msg = system  # Use provided system if any
            messages_list = []
            for msg in messages:
                if msg.get("role") == "system":
                    # Extract system from messages list for Claude
                    if system_msg is None:
                        system_msg = msg.get("content")
                else:
                    messages_list.append(msg)
            if system_msg is None:
                system_msg = "You are a helpful assistant."
        else:
            raise ValueError(f"messages must be str or List[Dict], got {type(messages)}")
        
        # Build request body for Claude
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": messages_list,
            "system": system_msg
        }
        
        # Add temperature if provided
        if temperature is not None:
            body["temperature"] = temperature
        
        # Add any additional parameters
        if "top_p" in kwargs:
            body["top_p"] = kwargs.pop("top_p")
        if "top_k" in kwargs:
            body["top_k"] = kwargs.pop("top_k")
        
        # Invoke the model with retry
        response_body = self._invoke_model_with_retry(body)
        
        # Extract content from Claude's response format
        content = response_body.get('content', [])
        if content and len(content) > 0:
            return content[0].get('text', '')
        
        return ""
    
    @retry_with_exponential_backoff(max_retries=5, initial_delay=10.0, max_delay=120.0)
    def _invoke_model_with_retry(self, body: dict) -> dict:
        """Invoke the model with retry logic for throttling errors."""
        response = self.bedrock.invoke_model(
            modelId=self._model_id,
            body=json.dumps(body)
        )
        return json.loads(response['body'].read())
    
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
        Query AWS Bedrock Claude and return full response with metadata.
        """
        messages = []
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})
        
        # Build request body for Claude
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": messages,
            "system": system_message
        }
        
        # Add temperature if provided
        if temperature is not None:
            body["temperature"] = temperature
        
        # Add any additional parameters
        if "top_p" in kwargs:
            body["top_p"] = kwargs.pop("top_p")
        if "top_k" in kwargs:
            body["top_k"] = kwargs.pop("top_k")
        
        # Invoke the model with retry
        response_body = self._invoke_model_with_retry(body)
        
        # Extract content
        content = response_body.get('content', [])
        text_content = content[0].get('text', '') if content else ''
        
        return {
            'content': text_content,
            'role': 'assistant',
            'finish_reason': response_body.get('stop_reason', 'unknown'),
            'usage': {
                'prompt_tokens': response_body.get('usage', {}).get('input_tokens', 0),
                'completion_tokens': response_body.get('usage', {}).get('output_tokens', 0),
                'total_tokens': (
                    response_body.get('usage', {}).get('input_tokens', 0) + 
                    response_body.get('usage', {}).get('output_tokens', 0)
                )
            },
            'model': self._model_id,
            'provider': self.provider,
            'raw_response': response_body
        }
    
    @property
    def model_name(self) -> str:
        """Return the current model ID."""
        return self._model_id
    
    @property
    def provider(self) -> str:
        """Return the provider name."""
        return "aws_bedrock"


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
    client = AWSBedrockClient()
    return client.query(prompt, system=system_message, **kwargs)


if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python aws_bedrock.py '<your prompt>'")
        print("Make sure AWS_ACCESS_KEY and AWS_SECRET_KEY are set in environment")
        sys.exit(1)
    
    prompt = sys.argv[1]
    response = quick_query(prompt)
    print(response)
