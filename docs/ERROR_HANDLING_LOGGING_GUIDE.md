# Error Handling and Logging Implementation Guide

This document describes the comprehensive error handling and logging system implemented for the Flask Chatbot MCP application.

## Overview

The application now includes:
- Custom exception classes for different error types
- Centralized error handling with user-friendly messages
- Comprehensive logging with sensitive data filtering
- Request/response logging with timing information
- Environment-specific logging configuration

## Custom Exception Classes

### Base Exception
- `ChatbotError`: Base exception for all application errors

### Specific Exceptions
- `MCPConnectionError`: MCP server connection failures
- `MCPToolExecutionError`: MCP tool execution failures
- `DatabaseError`: Database query errors
- `PDFProcessingError`: PDF processing failures
- `LLMAPIError`: LLM API failures
- `TimeoutError`: Operation timeouts
- `ValidationError`: Input validation failures

### Usage Example
```python
from modules.error_handler import DatabaseError

try:
    # Database operation
    result = query_database(view_name)
except Exception as e:
    raise DatabaseError(
        "Query failed",
        query=query_string,
        details={"view": view_name}
    )
```

## Error Response Format

All errors are formatted consistently:
```json
{
  "error": true,
  "message": "User-friendly error message",
  "code": "ERROR_CODE",
  "timestamp": "2025-10-31T14:30:00Z",
  "details": {...},  // Only in development
  "traceback": "..."  // Only in development
}
```

## User-Friendly Messages

The system automatically converts technical errors into user-friendly messages:
- MCP connection errors → "Some data sources are temporarily unavailable"
- Database errors → "Unable to retrieve data from the database"
- LLM API errors → "The AI service is temporarily unavailable"
- Timeout errors → "The request took too long to process"

## Logging Configuration

### Environment Variables

Add to your `.env` file:
```bash
# Logging Configuration
LOG_LEVEL=INFO              # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FILE=./logs/chatbot.log # Optional file logging
LOG_JSON=false              # Enable JSON-formatted logs
```

### Log Levels by Environment
- **Development**: DEBUG level, includes detailed information
- **Production**: INFO level, excludes sensitive details

### Sensitive Data Filtering

The logging system automatically redacts sensitive information:
- Passwords
- API keys
- Tokens
- Credentials
- Authorization headers

Example:
```python
logger.info("User config: password=secret123")
# Logged as: "User config: password=***REDACTED***"
```

## Request/Response Logging

Every HTTP request is automatically logged with:
- Request ID (UUID)
- Session ID
- HTTP method and path
- Status code
- Duration in milliseconds
- Error information (if applicable)

Example log output:
```
2025-10-31 14:30:00 - app - INFO - Request completed: POST /api/chat - Status: 200, Duration: 1234.56ms
```

## Error Recovery Strategies

### Retry with Exponential Backoff
```python
from modules.error_handler import ErrorRecoveryStrategy

result = ErrorRecoveryStrategy.retry_with_backoff(
    func=my_function,
    max_retries=3,
    initial_delay=1.0,
    backoff_factor=2.0
)
```

### Fallback on Error
```python
result = ErrorRecoveryStrategy.fallback_on_error(
    primary_func=primary_operation,
    fallback_func=fallback_operation
)
```

### Circuit Breaker
```python
result = ErrorRecoveryStrategy.circuit_breaker(
    func=my_function,
    failure_threshold=5,
    timeout=60
)
```

## Error Handling Decorators

### MCP Error Handling
```python
from modules.error_handler import handle_mcp_errors

@handle_mcp_errors
def connect_to_server():
    # MCP connection logic
    pass
```

### Database Error Handling
```python
from modules.error_handler import handle_database_errors

@handle_database_errors
def query_database():
    # Database query logic
    pass
```

### PDF Error Handling
```python
from modules.error_handler import handle_pdf_errors

@handle_pdf_errors
def process_pdf():
    # PDF processing logic
    pass
```

## Implementation Details

### Files Added
1. `modules/error_handler.py` - Custom exceptions and error handling utilities
2. `modules/logging_config.py` - Logging configuration and filters
3. `test_error_handling.py` - Test suite for error handling

### Files Modified
1. `app.py` - Added error handlers and request/response logging
2. `modules/mcp_client.py` - Enhanced with error handling
3. `modules/llm_service.py` - Enhanced with error handling
4. `modules/oracle_mcp_server.py` - Enhanced with error handling
5. `modules/pdf_mcp_server.py` - Enhanced with error handling
6. `.env.example` - Added logging configuration options

## Testing

Run the error handling tests:
```bash
python test_error_handling.py
```

This verifies:
- Custom exception classes work correctly
- Error formatting produces correct output
- Sensitive data is properly filtered
- Logging configuration works
- User-friendly messages are generated

## Best Practices

1. **Always use custom exceptions** for application errors
2. **Log errors with context** using `log_error_with_context()`
3. **Never log sensitive data** - the filter will catch most cases, but be careful
4. **Use appropriate log levels**:
   - DEBUG: Detailed diagnostic information
   - INFO: General informational messages
   - WARNING: Warning messages for recoverable issues
   - ERROR: Error messages for failures
   - CRITICAL: Critical errors requiring immediate attention
5. **Include request_id** in logs for request tracing
6. **Use error recovery strategies** for transient failures

## Monitoring and Debugging

### View Logs
```bash
# Console logs (stdout)
# Automatically displayed when running the application

# File logs (if configured)
tail -f ./logs/chatbot.log
```

### Search Logs
```bash
# Find errors
grep "ERROR" ./logs/chatbot.log

# Find specific request
grep "request_id=abc-123" ./logs/chatbot.log

# Find slow requests (>1000ms)
grep "Duration: [0-9][0-9][0-9][0-9]" ./logs/chatbot.log
```

### Production Monitoring

In production, consider:
- Centralized logging (e.g., ELK stack, CloudWatch)
- Log aggregation and analysis
- Alert on error rates
- Monitor request durations
- Track error patterns

## Troubleshooting

### Issue: Logs not appearing
- Check `LOG_LEVEL` environment variable
- Verify logging is configured in `app.py`
- Check file permissions for `LOG_FILE`

### Issue: Sensitive data in logs
- Verify `SensitiveDataFilter` is applied
- Add custom patterns to `SENSITIVE_PATTERNS`
- Review log output in development

### Issue: Too many logs
- Increase `LOG_LEVEL` to WARNING or ERROR
- Adjust third-party logger levels
- Use log rotation to manage file size

## Requirements Satisfied

This implementation satisfies the following requirements:

### Task 8.1 - Comprehensive Error Handling
- ✓ MCP server connection failure handling with graceful degradation
- ✓ Database query error handling with user-friendly messages
- ✓ PDF processing error handling with partial results
- ✓ LLM API failure handling with retry logic
- ✓ Timeout handling for Vercel serverless limits

### Task 8.2 - Logging System
- ✓ Logging configuration for different environments
- ✓ Request/response logging for debugging
- ✓ Error logging with stack traces
- ✓ Sensitive data filtering to prevent credential leaks

### Requirements Coverage
- Requirement 1.4: Error message display
- Requirement 3.4: MCP server failure handling
- Requirement 4.4: Database error handling
- Requirement 6.2: No sensitive data logging
- Requirement 6.5: Clear error messages
- Requirement 7.4: LLM API error handling
