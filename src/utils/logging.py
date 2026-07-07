"""
Simple logging utilities for cleaner console output.
"""
import sys
from datetime import datetime
from typing import Optional


class Logger:
    """Simple logger with emoji indicators."""
    
    def __init__(self, name: Optional[str] = None, verbose: bool = True):
        """
        Initialize logger.
        
        Args:
            name: Logger name (optional)
            verbose: Whether to print debug messages
        """
        self.name = name
        self.verbose = verbose
    
    def _format_message(self, emoji: str, level: str, message: str) -> str:
        """Format log message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{timestamp}]"
        if self.name:
            prefix += f" [{self.name}]"
        return f"{prefix} {emoji} {message}"
    
    def info(self, message: str):
        """Log info message."""
        print(self._format_message("ℹ️", "INFO", message))
    
    def success(self, message: str):
        """Log success message."""
        print(self._format_message("✅", "SUCCESS", message))
    
    def warning(self, message: str):
        """Log warning message."""
        print(self._format_message("⚠️", "WARNING", message))
    
    def error(self, message: str):
        """Log error message."""
        print(self._format_message("❌", "ERROR", message), file=sys.stderr)
    
    def debug(self, message: str):
        """Log debug message (only if verbose)."""
        if self.verbose:
            print(self._format_message("🔍", "DEBUG", message))
    
    def step(self, step_num: int, total_steps: int, message: str):
        """Log step progress."""
        print(self._format_message("📍", "STEP", f"[{step_num}/{total_steps}] {message}"))
    
    def section(self, title: str):
        """Print section header."""
        print()
        print("=" * 70)
        print(f"  {title}")
        print("=" * 70)


# Global default logger
_default_logger = Logger()


def info(message: str):
    """Log info message using default logger."""
    _default_logger.info(message)


def success(message: str):
    """Log success message using default logger."""
    _default_logger.success(message)


def warning(message: str):
    """Log warning message using default logger."""
    _default_logger.warning(message)


def error(message: str):
    """Log error message using default logger."""
    _default_logger.error(message)


def debug(message: str):
    """Log debug message using default logger."""
    _default_logger.debug(message)


def step(step_num: int, total_steps: int, message: str):
    """Log step progress using default logger."""
    _default_logger.step(step_num, total_steps, message)


def section(title: str):
    """Print section header using default logger."""
    _default_logger.section(title)


if __name__ == "__main__":
    # Test logging
    logger = Logger("TestLogger")
    
    logger.section("Testing Logger")
    logger.info("This is an info message")
    logger.success("This is a success message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    logger.debug("This is a debug message")
    logger.step(1, 3, "First step")
    logger.step(2, 3, "Second step")
    logger.step(3, 3, "Final step")



