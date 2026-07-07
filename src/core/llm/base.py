"""
Base abstract class for all LLM clients.
Provides a unified interface for querying different LLM providers.
"""
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Union


class BaseLLMClient(ABC):
    """Abstract base class for all LLM clients."""
    
    @abstractmethod
    def query(
        self,
        messages: Union[str, List[Dict[str, str]]],
        max_tokens: int = 16384,
        temperature: Optional[float] = None,
        system: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Query the LLM with messages.
        
        Args:
            messages: Either:
                - List[Dict]: Standard format [{"role": "system/user/assistant", "content": "..."}]
                - str: Simple user message (use with system parameter)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (0-2), None to use model default
            system: Optional system prompt (only used when messages is str)
            **kwargs: Additional provider-specific parameters
            
        Returns:
            The LLM's response text
            
        Example:
            >>> # With messages list (recommended)
            >>> from src.core.prompts import build_messages
            >>> messages = build_messages(user_message="Hello", system_prompt="You are helpful")
            >>> response = client.query(messages)
            >>> 
            >>> # Simple string with system
            >>> response = client.query("Hello, what is 2+2?", system="You are helpful")
            >>> 
            >>> # Simple string (default system)
            >>> response = client.query("Hello, what is 2+2?")
        """
        pass
    
    @abstractmethod
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
        Query the LLM and return full response with metadata.
        
        Returns:
            Dictionary with 'content', 'usage', 'model', etc.
        """
        pass
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the current model name."""
        pass
    
    @property
    @abstractmethod
    def provider(self) -> str:
        """Return the provider name (e.g., 'azure_openai', 'aws_bedrock')."""
        pass

