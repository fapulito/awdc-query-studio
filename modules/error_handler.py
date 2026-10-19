"""
Error Handling Module

Provides centralized error handling, custom exceptions, and error response formatting
for the Flask chatbot application with MCP integration.

Requirements: 1.4, 3.4, 4.4, 7.4
"""

import logging
import traceback
from typing import Dict, Any, Optional, Tuple
from functools import wraps
from datetime import datetime

logger = logging.getLogger(__name__)


# Custom Exception Classes

class ChatbotError(Exception):
    """Base exception for chatbot application errors"""
    def __init__(self, message: str, code: str = "CHATBOT_ERROR", details: Optional[Dict] = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class MCPConnectionError(ChatbotError):
    """Exception for MCP server connection failures"""
    def __init__(self, server_name: str, message: str, details: Optional[Dict] = None):
        super().__init__(
            message=f"MCP server '{server_name}' connection failed: {message}",
            code="MCP_CONNECTION_ERROR",
            details={**(details or {}), "server_name": server_name}
        )


class MCPToolExecutionError(ChatbotError):
    """Exception for MCP tool execution failures"""
    def __init__(self, tool_name: str, message: str, details: Optional[Dict] = None):
        super().__init__(
            message=f"Tool '{tool_name}' execution failed: {message}",
            code="MCP_TOOL_ERROR",
            details={**(details or {}), "tool_name": tool_name}
        )


class DatabaseError(ChatbotError):
    """Exception for database query errors"""
    def __init__(self, message: str, query: Optional[str] = None, details: Optional[Dict] = None):
        super().__init__(
            message=f"Database error: {message}",
            code="DATABASE_ERROR",
            details={**(details or {}), "query": query if query else "N/A"}
        )


class PDFProcessingError(ChatbotError):
    """Exception for PDF processing failures"""
    def __init__(self, filename: str, message: str, details: Optional[Dict] = None):
        super().__init__(
            message=f"PDF processing failed for '{filename}': {message}",
            code="PDF_PROCESSING_ERROR",
            details={**(details or {}), "filename": filename}
        )


class LLMAPIError(ChatbotError):
    """Exception for LLM API failures"""
    def __init__(self, message: str, model: Optional[str] = None, details: Optional[Dict] = None):
        super().__init__(
            message=f"LLM API error: {message}",
            code="LLM_API_ERROR",
            details={**(details or {}), "model": model if model else "N/A"}
        )


class TimeoutError(ChatbotError):
    """Exception for operation timeouts"""
    def __init__(self, operation: str, timeout_seconds: int, details: Optional[Dict] = None):
        super().__init__(
            message=f"Operation '{operation}' timed out after {timeout_seconds} seconds",
            code="TIMEOUT_ERROR",
            details={**(details or {}), "operation": operation, "timeout": timeout_seconds}
        )


class ValidationError(ChatbotError):
    """Exception for input validation failures"""
    def __init__(self, field: str, message: str, details: Optional[Dict] = None):
        super().__init__(
            message=f"Validation error for '{field}': {message}",
            code="VALIDATION_ERROR",
            details={**(details or {}), "field": field}
        )


# Error Response Formatting

def format_error_response(
    error: Exception,
    include_details: bool = False,
    include_traceback: bool = False
) -> Dict[str, Any]:
    """
    Format an exception into a standardized error response.
    
    Args:
        error: The exception to format
        include_details: Whether to include detailed error information
        include_traceback: Whether to include stack trace (development only)
        
    Returns:
        Dictionary containing formatted error response
    """
    response = {
        "error": True,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Handle custom chatbot errors
    if isinstance(error, ChatbotError):
        response["message"] = error.message
        response["code"] = error.code
        
        if include_details and error.details:
            response["details"] = error.details
    else:
        # Handle generic exceptions
        response["message"] = str(error) if str(error) else "An unexpected error occurred"
        response["code"] = "INTERNAL_ERROR"
    
    # Add traceback for debugging (development only)
    if include_traceback:
        response["traceback"] = traceback.format_exc()
    
    return response


def get_user_friendly_message(error: Exception) -> str:
    """
    Get a user-friendly error message for display.
    
    Args:
        error: The exception
        
    Returns:
        User-friendly error message string
    """
    if isinstance(error, MCPConnectionError):
        return "Some data sources are temporarily unavailable. Please try again later."
    
    elif isinstance(error, MCPToolExecutionError):
        return "Unable to retrieve the requested information. Please try rephrasing your question."
    
    elif isinstance(error, DatabaseError):
        return "Unable to retrieve data from the database. Please try again later."
    
    elif isinstance(error, PDFProcessingError):
        return "Unable to process the requested document. Some documents may be temporarily unavailable."
    
    elif isinstance(error, LLMAPIError):
        return "The AI service is temporarily unavailable. Please try again in a moment."
    
    elif isinstance(error, TimeoutError):
        return "The request took too long to process. Please try a simpler query or try again later."
    
    elif isinstance(error, ValidationError):
        return f"Invalid input: {error.message}"
    
    else:
        return "An unexpected error occurred. Please try again later."


# Error Handling Decorators

def handle_mcp_errors(func):
    """
    Decorator to handle MCP-related errors with retry logic and graceful degradation.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except MCPConnectionError as e:
            logger.error(f"MCP connection error in {func.__name__}: {e.message}", exc_info=True)
            # Return degraded mode response
            return {
                "error": True,
                "message": get_user_friendly_message(e),
                "code": e.code,
                "degraded_mode": True
            }
        except MCPToolExecutionError as e:
            logger.error(f"MCP tool execution error in {func.__name__}: {e.message}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {str(e)}", exc_info=True)
            raise ChatbotError(f"MCP operation failed: {str(e)}", code="MCP_ERROR")
    
    return wrapper


def handle_database_errors(func):
    """
    Decorator to handle database-related errors with user-friendly messages.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except DatabaseError as e:
            logger.error(f"Database error in {func.__name__}: {e.message}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected database error in {func.__name__}: {str(e)}", exc_info=True)
            raise DatabaseError(str(e))
    
    return wrapper


def handle_pdf_errors(func):
    """
    Decorator to handle PDF processing errors gracefully.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except PDFProcessingError as e:
            logger.error(f"PDF processing error in {func.__name__}: {e.message}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected PDF error in {func.__name__}: {str(e)}", exc_info=True)
            raise PDFProcessingError("unknown", str(e))
    
    return wrapper


def handle_llm_errors(func):
    """
    Decorator to handle LLM API errors with retry logic.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except LLMAPIError as e:
            logger.error(f"LLM API error in {func.__name__}: {e.message}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected LLM error in {func.__name__}: {str(e)}", exc_info=True)
            raise LLMAPIError(str(e))
    
    return wrapper


def handle_timeout(timeout_seconds: int, operation_name: str):
    """
    Decorator factory to handle operation timeouts.
    
    Args:
        timeout_seconds: Maximum allowed execution time
        operation_name: Name of the operation for error messages
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            import signal
            
            def timeout_handler(signum, frame):
                raise TimeoutError(operation_name, timeout_seconds)
            
            # Set timeout alarm (Unix-like systems only)
            try:
                old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(timeout_seconds)
                
                try:
                    result = func(*args, **kwargs)
                finally:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
                
                return result
            except AttributeError:
                # Windows doesn't support SIGALRM, just execute normally
                logger.warning(f"Timeout handling not available on this platform for {operation_name}")
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


# Error Recovery Strategies

class ErrorRecoveryStrategy:
    """
    Provides strategies for recovering from various error conditions.
    """
    
    @staticmethod
    def retry_with_backoff(
        func,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        backoff_factor: float = 2.0,
        exceptions: Tuple = (Exception,)
    ):
        """
        Retry a function with exponential backoff.
        
        Args:
            func: Function to retry
            max_retries: Maximum number of retry attempts
            initial_delay: Initial delay in seconds
            backoff_factor: Multiplier for delay after each retry
            exceptions: Tuple of exceptions to catch and retry
            
        Returns:
            Function result if successful
            
        Raises:
            Last exception if all retries fail
        """
        import time
        
        last_exception = None
        delay = initial_delay
        
        for attempt in range(max_retries):
            try:
                return func()
            except exceptions as e:
                last_exception = e
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed: {str(e)}. "
                    f"Retrying in {delay}s..."
                )
                
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    delay *= backoff_factor
        
        logger.error(f"All {max_retries} retry attempts failed")
        raise last_exception
    
    @staticmethod
    def fallback_on_error(primary_func, fallback_func, exceptions: Tuple = (Exception,)):
        """
        Execute primary function, fall back to alternative on error.
        
        Args:
            primary_func: Primary function to execute
            fallback_func: Fallback function if primary fails
            exceptions: Tuple of exceptions to catch
            
        Returns:
            Result from primary or fallback function
        """
        try:
            return primary_func()
        except exceptions as e:
            logger.warning(f"Primary function failed: {str(e)}. Using fallback.")
            return fallback_func()
    
    @staticmethod
    def circuit_breaker(
        func,
        failure_threshold: int = 5,
        timeout: int = 60,
        exceptions: Tuple = (Exception,)
    ):
        """
        Implement circuit breaker pattern to prevent cascading failures.
        
        Args:
            func: Function to protect with circuit breaker
            failure_threshold: Number of failures before opening circuit
            timeout: Seconds to wait before attempting to close circuit
            exceptions: Tuple of exceptions to count as failures
            
        Returns:
            Function result if circuit is closed
            
        Raises:
            ChatbotError if circuit is open
        """
        # This is a simplified implementation
        # In production, use a proper circuit breaker library
        
        if not hasattr(circuit_breaker, 'failures'):
            circuit_breaker.failures = {}
            circuit_breaker.last_failure_time = {}
        
        func_name = func.__name__
        
        # Check if circuit is open
        if func_name in circuit_breaker.failures:
            if circuit_breaker.failures[func_name] >= failure_threshold:
                import time
                time_since_failure = time.time() - circuit_breaker.last_failure_time.get(func_name, 0)
                
                if time_since_failure < timeout:
                    raise ChatbotError(
                        f"Circuit breaker open for {func_name}",
                        code="CIRCUIT_BREAKER_OPEN"
                    )
                else:
                    # Attempt to close circuit
                    logger.info(f"Attempting to close circuit for {func_name}")
                    circuit_breaker.failures[func_name] = 0
        
        try:
            result = func()
            # Success - reset failure count
            circuit_breaker.failures[func_name] = 0
            return result
        except exceptions as e:
            # Failure - increment counter
            import time
            circuit_breaker.failures[func_name] = circuit_breaker.failures.get(func_name, 0) + 1
            circuit_breaker.last_failure_time[func_name] = time.time()
            
            logger.warning(
                f"Circuit breaker failure {circuit_breaker.failures[func_name]}/{failure_threshold} "
                f"for {func_name}"
            )
            raise


# Logging Helpers

def log_error_with_context(
    error: Exception,
    context: Dict[str, Any],
    level: int = logging.ERROR
):
    """
    Log an error with additional context information.
    
    Args:
        error: The exception to log
        context: Dictionary of contextual information
        level: Logging level
    """
    error_info = {
        "error_type": type(error).__name__,
        "error_message": str(error),
        "context": context
    }
    
    if isinstance(error, ChatbotError):
        error_info["error_code"] = error.code
        error_info["error_details"] = error.details
    
    logger.log(level, f"Error occurred: {error_info}", exc_info=True)


def sanitize_for_logging(data: Any) -> Any:
    """
    Sanitize data to remove sensitive information before logging.
    
    Args:
        data: Data to sanitize
        
    Returns:
        Sanitized data safe for logging
    """
    if isinstance(data, dict):
        sanitized = {}
        sensitive_keys = {
            'password', 'api_key', 'secret', 'token', 'credential',
            'authorization', 'auth', 'passwd', 'pwd'
        }
        
        for key, value in data.items():
            key_lower = key.lower()
            if any(sensitive in key_lower for sensitive in sensitive_keys):
                sanitized[key] = "***REDACTED***"
            elif isinstance(value, (dict, list)):
                sanitized[key] = sanitize_for_logging(value)
            else:
                sanitized[key] = value
        
        return sanitized
    
    elif isinstance(data, list):
        return [sanitize_for_logging(item) for item in data]
    
    else:
        return data
