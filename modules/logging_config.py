"""
Logging Configuration Module

Provides centralized logging configuration for different environments
with request/response logging, error logging, and sensitive data filtering.

Requirements: 6.2, 6.5
"""

import os
import logging
import logging.handlers
import sys
from typing import Optional, Dict, Any
from datetime import datetime
from pathlib import Path
import json


class SensitiveDataFilter(logging.Filter):
    """
    Filter to redact sensitive information from log records.
    Prevents credentials, API keys, and other sensitive data from being logged.
    """
    
    SENSITIVE_PATTERNS = [
        'password', 'passwd', 'pwd', 'secret', 'api_key', 'apikey',
        'token', 'auth', 'authorization', 'credential', 'private_key',
        'access_key', 'secret_key'
    ]
    
    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter log record to redact sensitive information.
        
        Args:
            record: Log record to filter
            
        Returns:
            True to allow the record to be logged
        """
        # Sanitize the message
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            record.msg = self._sanitize_string(record.msg)
        
        # Sanitize arguments
        if hasattr(record, 'args') and record.args:
            if isinstance(record.args, dict):
                record.args = self._sanitize_dict(record.args)
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(self._sanitize_value(arg) for arg in record.args)
        
        return True
    
    def _sanitize_string(self, text: str) -> str:
        """Sanitize a string by redacting sensitive patterns."""
        import re
        
        # Pattern to match key=value or key: value
        for pattern in self.SENSITIVE_PATTERNS:
            # Match key=value format
            text = re.sub(
                rf'{pattern}\s*=\s*["\']?[^"\'\s]+["\']?',
                f'{pattern}=***REDACTED***',
                text,
                flags=re.IGNORECASE
            )
            # Match key: value format
            text = re.sub(
                rf'{pattern}\s*:\s*["\']?[^"\'\s,}}]+["\']?',
                f'{pattern}: ***REDACTED***',
                text,
                flags=re.IGNORECASE
            )
        
        return text
    
    def _sanitize_dict(self, data: Dict) -> Dict:
        """Sanitize a dictionary by redacting sensitive keys."""
        sanitized = {}
        for key, value in data.items():
            key_lower = str(key).lower()
            if any(pattern in key_lower for pattern in self.SENSITIVE_PATTERNS):
                sanitized[key] = '***REDACTED***'
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_dict(value)
            elif isinstance(value, (list, tuple)):
                sanitized[key] = [self._sanitize_value(v) for v in value]
            else:
                sanitized[key] = value
        return sanitized
    
    def _sanitize_value(self, value: Any) -> Any:
        """Sanitize a value recursively."""
        if isinstance(value, dict):
            return self._sanitize_dict(value)
        elif isinstance(value, str):
            return self._sanitize_string(value)
        elif isinstance(value, (list, tuple)):
            return [self._sanitize_value(v) for v in value]
        else:
            return value


class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.
    Outputs log records as JSON for easier parsing and analysis.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.
        
        Args:
            record: Log record to format
            
        Returns:
            JSON-formatted log string
        """
        log_data = {
            'timestamp': datetime.utcfromtimestamp(record.created).isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        # Add extra fields
        if hasattr(record, 'request_id'):
            log_data['request_id'] = record.request_id
        
        if hasattr(record, 'user_id'):
            log_data['user_id'] = record.user_id
        
        if hasattr(record, 'session_id'):
            log_data['session_id'] = record.session_id
        
        return json.dumps(log_data)


class RequestResponseLogger:
    """
    Logger for HTTP request and response information.
    Provides structured logging of API interactions.
    """
    
    def __init__(self, logger_name: str = 'request_response'):
        """
        Initialize request/response logger.
        
        Args:
            logger_name: Name of the logger
        """
        self.logger = logging.getLogger(logger_name)
    
    def log_request(
        self,
        method: str,
        path: str,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> None:
        """
        Log incoming HTTP request.
        
        Args:
            method: HTTP method
            path: Request path
            request_id: Optional request ID
            session_id: Optional session ID
            user_agent: Optional user agent string
            ip_address: Optional client IP address
        """
        log_data = {
            'type': 'request',
            'method': method,
            'path': path,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        if request_id:
            log_data['request_id'] = request_id
        if session_id:
            log_data['session_id'] = session_id
        if user_agent:
            log_data['user_agent'] = user_agent
        if ip_address:
            log_data['ip_address'] = ip_address
        
        self.logger.info(f"Request: {method} {path}", extra=log_data)
    
    def log_response(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        error: Optional[str] = None
    ) -> None:
        """
        Log HTTP response.
        
        Args:
            method: HTTP method
            path: Request path
            status_code: HTTP status code
            duration_ms: Request duration in milliseconds
            request_id: Optional request ID
            session_id: Optional session ID
            error: Optional error message
        """
        log_data = {
            'type': 'response',
            'method': method,
            'path': path,
            'status_code': status_code,
            'duration_ms': duration_ms,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        if request_id:
            log_data['request_id'] = request_id
        if session_id:
            log_data['session_id'] = session_id
        if error:
            log_data['error'] = error
        
        level = logging.ERROR if status_code >= 500 else logging.WARNING if status_code >= 400 else logging.INFO
        self.logger.log(
            level,
            f"Response: {method} {path} - {status_code} ({duration_ms:.2f}ms)",
            extra=log_data
        )


def setup_logging(
    environment: str = 'development',
    log_level: Optional[str] = None,
    log_file: Optional[str] = None,
    enable_json_logging: bool = False
) -> None:
    """
    Configure logging for the application.
    
    Args:
        environment: Environment name ('development', 'production', etc.)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional path to log file
        enable_json_logging: Whether to use JSON formatting
    """
    # Determine log level
    if log_level is None:
        log_level = 'DEBUG' if environment == 'development' else 'INFO'
    
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Create formatters
    if enable_json_logging:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(SensitiveDataFilter())
    root_logger.addHandler(console_handler)
    
    # File handler (if specified)
    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Use rotating file handler to prevent log files from growing too large
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,  # 10 MB
                backupCount=5
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            file_handler.addFilter(SensitiveDataFilter())
            root_logger.addHandler(file_handler)
            
            logging.info(f"File logging enabled: {log_file}")
        except Exception as e:
            logging.error(f"Failed to setup file logging: {str(e)}")
    
    # Set levels for third-party loggers to reduce noise
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('openai').setLevel(logging.WARNING)
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    
    logging.info(f"Logging configured: environment={environment}, level={log_level}")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the specified name.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def configure_from_env() -> None:
    """
    Configure logging from environment variables.
    
    Environment variables:
    - FLASK_ENV: Environment name (development, production)
    - LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - LOG_FILE: Path to log file
    - LOG_JSON: Enable JSON logging (true/false)
    """
    environment = os.getenv('FLASK_ENV', 'development')
    log_level = os.getenv('LOG_LEVEL')
    log_file = os.getenv('LOG_FILE')
    enable_json = os.getenv('LOG_JSON', 'false').lower() == 'true'
    
    setup_logging(
        environment=environment,
        log_level=log_level,
        log_file=log_file,
        enable_json_logging=enable_json
    )


# Context manager for request logging
class RequestLoggingContext:
    """
    Context manager for logging request/response with timing.
    """
    
    def __init__(
        self,
        method: str,
        path: str,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None
    ):
        """
        Initialize request logging context.
        
        Args:
            method: HTTP method
            path: Request path
            request_id: Optional request ID
            session_id: Optional session ID
        """
        self.method = method
        self.path = path
        self.request_id = request_id
        self.session_id = session_id
        self.logger = RequestResponseLogger()
        self.start_time = None
        self.status_code = None
        self.error = None
    
    def __enter__(self):
        """Enter context - log request start."""
        import time
        self.start_time = time.time()
        self.logger.log_request(
            method=self.method,
            path=self.path,
            request_id=self.request_id,
            session_id=self.session_id
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context - log request completion."""
        import time
        duration_ms = (time.time() - self.start_time) * 1000
        
        if exc_type is not None:
            self.error = str(exc_val)
            self.status_code = 500
        
        if self.status_code is None:
            self.status_code = 200
        
        self.logger.log_response(
            method=self.method,
            path=self.path,
            status_code=self.status_code,
            duration_ms=duration_ms,
            request_id=self.request_id,
            session_id=self.session_id,
            error=self.error
        )
    
    def set_status(self, status_code: int):
        """Set response status code."""
        self.status_code = status_code
    
    def set_error(self, error: str):
        """Set error message."""
        self.error = error
