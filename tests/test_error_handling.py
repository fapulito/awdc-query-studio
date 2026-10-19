"""
Test Error Handling and Logging

Simple tests to verify error handling and logging functionality.
"""

import os
import sys
import logging
from modules.error_handler import (
    ChatbotError, MCPConnectionError, MCPToolExecutionError,
    DatabaseError, PDFProcessingError, LLMAPIError, TimeoutError,
    ValidationError, format_error_response, get_user_friendly_message,
    sanitize_for_logging
)
from modules.logging_config import (
    SensitiveDataFilter, setup_logging, get_logger
)


def test_custom_exceptions():
    """Test custom exception classes"""
    print("Testing custom exceptions...")
    
    # Test MCPConnectionError
    try:
        raise MCPConnectionError("test_server", "Connection refused")
    except MCPConnectionError as e:
        assert e.code == "MCP_CONNECTION_ERROR"
        assert "test_server" in e.message
        print("✓ MCPConnectionError works")
    
    # Test DatabaseError
    try:
        raise DatabaseError("Query failed", query="SELECT * FROM test")
    except DatabaseError as e:
        assert e.code == "DATABASE_ERROR"
        assert "Query failed" in e.message
        print("✓ DatabaseError works")
    
    # Test LLMAPIError
    try:
        raise LLMAPIError("Rate limit exceeded", model="gpt-4")
    except LLMAPIError as e:
        assert e.code == "LLM_API_ERROR"
        assert "Rate limit" in e.message
        print("✓ LLMAPIError works")
    
    # Test TimeoutError
    try:
        raise TimeoutError("database_query", 5)
    except TimeoutError as e:
        assert e.code == "TIMEOUT_ERROR"
        assert "5 seconds" in e.message
        print("✓ TimeoutError works")
    
    # Test ValidationError
    try:
        raise ValidationError("email", "Invalid format")
    except ValidationError as e:
        assert e.code == "VALIDATION_ERROR"
        assert "email" in e.message
        print("✓ ValidationError works")


def test_error_formatting():
    """Test error response formatting"""
    print("\nTesting error formatting...")
    
    # Test with custom error
    error = DatabaseError("Connection failed", details={"host": "localhost"})
    response = format_error_response(error, include_details=True)
    
    assert response["error"] is True
    assert response["code"] == "DATABASE_ERROR"
    assert "Connection failed" in response["message"]
    assert "details" in response
    print("✓ Error formatting works")
    
    # Test user-friendly messages
    error = LLMAPIError("API timeout")
    message = get_user_friendly_message(error)
    assert "AI service" in message
    assert "temporarily unavailable" in message
    print("✓ User-friendly messages work")


def test_sensitive_data_filtering():
    """Test sensitive data sanitization"""
    print("\nTesting sensitive data filtering...")
    
    # Test dictionary sanitization
    data = {
        "username": "test_user",
        "password": "secret123",
        "api_key": "sk-1234567890",
        "message": "Hello world"
    }
    
    sanitized = sanitize_for_logging(data)
    assert sanitized["username"] == "test_user"
    assert sanitized["password"] == "***REDACTED***"
    assert sanitized["api_key"] == "***REDACTED***"
    assert sanitized["message"] == "Hello world"
    print("✓ Sensitive data filtering works")
    
    # Test nested sanitization
    nested_data = {
        "config": {
            "database": {
                "host": "localhost",
                "password": "db_secret"
            }
        }
    }
    
    sanitized_nested = sanitize_for_logging(nested_data)
    assert sanitized_nested["config"]["database"]["host"] == "localhost"
    assert sanitized_nested["config"]["database"]["password"] == "***REDACTED***"
    print("✓ Nested data sanitization works")


def test_logging_configuration():
    """Test logging configuration"""
    print("\nTesting logging configuration...")
    
    # Setup logging
    setup_logging(environment='development', log_level='DEBUG')
    
    # Get logger
    logger = get_logger(__name__)
    assert logger is not None
    assert logger.level == logging.DEBUG
    print("✓ Logging configuration works")
    
    # Test logging with sensitive data filter
    logger.info("Testing log with password=secret123")
    print("✓ Logging with filter works (check output above)")


def test_sensitive_data_filter():
    """Test SensitiveDataFilter"""
    print("\nTesting SensitiveDataFilter...")
    
    filter_obj = SensitiveDataFilter()
    
    # Create a log record
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="User logged in with password=secret123 and api_key=sk-1234",
        args=(),
        exc_info=None
    )
    
    # Apply filter
    filter_obj.filter(record)
    
    # Check that sensitive data is redacted
    assert "***REDACTED***" in record.msg
    assert "secret123" not in record.msg
    assert "sk-1234" not in record.msg
    print("✓ SensitiveDataFilter works")


def main():
    """Run all tests"""
    print("=" * 60)
    print("Error Handling and Logging Tests")
    print("=" * 60)
    
    try:
        test_custom_exceptions()
        test_error_formatting()
        test_sensitive_data_filtering()
        test_logging_configuration()
        test_sensitive_data_filter()
        
        print("\n" + "=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)
        return 0
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {str(e)}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
