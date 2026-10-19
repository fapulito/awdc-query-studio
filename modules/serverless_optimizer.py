"""
Serverless Optimization Module
Provides utilities for optimizing cold starts and connection caching
Requirements: 2.4, 2.5
"""

import os
import time
import logging
from typing import Optional, Callable, Any, Dict
from functools import wraps

logger = logging.getLogger(__name__)


class ConnectionCache:
    """
    Cache for database and service connections to reduce cold start time
    Implements connection reuse across serverless function invocations
    """
    
    def __init__(self, ttl: int = 300):
        """
        Initialize connection cache
        
        Args:
            ttl: Time-to-live for cached connections in seconds (default: 5 minutes)
        """
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._ttl = ttl
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get a cached connection
        
        Args:
            key: Cache key
            
        Returns:
            Cached connection or None if not found or expired
        """
        if key not in self._cache:
            return None
        
        entry = self._cache[key]
        age = time.time() - entry['timestamp']
        
        if age > self._ttl:
            logger.debug(f"Cache entry '{key}' expired (age: {age:.1f}s)")
            del self._cache[key]
            return None
        
        logger.debug(f"Cache hit for '{key}' (age: {age:.1f}s)")
        return entry['connection']
    
    def set(self, key: str, connection: Any) -> None:
        """
        Store a connection in cache
        
        Args:
            key: Cache key
            connection: Connection object to cache
        """
        self._cache[key] = {
            'connection': connection,
            'timestamp': time.time()
        }
        logger.debug(f"Cached connection '{key}'")
    
    def invalidate(self, key: str) -> None:
        """
        Invalidate a cached connection
        
        Args:
            key: Cache key to invalidate
        """
        if key in self._cache:
            del self._cache[key]
            logger.debug(f"Invalidated cache entry '{key}'")
    
    def clear(self) -> None:
        """Clear all cached connections"""
        self._cache.clear()
        logger.debug("Cleared all cache entries")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics
        
        Returns:
            Dictionary with cache statistics
        """
        current_time = time.time()
        entries = []
        
        for key, entry in self._cache.items():
            age = current_time - entry['timestamp']
            entries.append({
                'key': key,
                'age_seconds': age,
                'expired': age > self._ttl
            })
        
        return {
            'total_entries': len(self._cache),
            'ttl_seconds': self._ttl,
            'entries': entries
        }


# Global connection cache instance
_connection_cache = ConnectionCache(ttl=int(os.getenv('CONNECTION_CACHE_TTL', 300)))


def get_connection_cache() -> ConnectionCache:
    """
    Get the global connection cache instance
    
    Returns:
        ConnectionCache instance
    """
    return _connection_cache


def lazy_import(module_name: str, attribute: Optional[str] = None):
    """
    Lazy import decorator to defer heavy imports until needed
    Reduces cold start time by avoiding unnecessary imports
    
    Args:
        module_name: Name of module to import
        attribute: Optional attribute to import from module
        
    Returns:
        Decorator function
    """
    def decorator(func: Callable) -> Callable:
        _imported = {}
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            if 'module' not in _imported:
                logger.debug(f"Lazy importing {module_name}")
                start_time = time.time()
                
                module = __import__(module_name, fromlist=[attribute] if attribute else [])
                if attribute:
                    _imported['module'] = getattr(module, attribute)
                else:
                    _imported['module'] = module
                
                import_time = (time.time() - start_time) * 1000
                logger.debug(f"Imported {module_name} in {import_time:.2f}ms")
            
            return func(*args, **kwargs, _lazy_module=_imported['module'])
        
        return wrapper
    return decorator


def cached_connection(cache_key: str, ttl: Optional[int] = None):
    """
    Decorator for caching connections across function invocations
    
    Args:
        cache_key: Key to use for caching
        ttl: Optional TTL override for this connection
        
    Returns:
        Decorator function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache = get_connection_cache()
            
            # Try to get from cache
            cached = cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Using cached connection for '{cache_key}'")
                return cached
            
            # Create new connection
            logger.debug(f"Creating new connection for '{cache_key}'")
            start_time = time.time()
            
            connection = func(*args, **kwargs)
            
            connection_time = (time.time() - start_time) * 1000
            logger.debug(f"Connection created in {connection_time:.2f}ms")
            
            # Cache the connection
            cache.set(cache_key, connection)
            
            return connection
        
        return wrapper
    return decorator


def optimize_cold_start(func: Callable) -> Callable:
    """
    Decorator to optimize function for cold start performance
    Tracks execution time and logs performance metrics
    
    Args:
        func: Function to optimize
        
    Returns:
        Wrapped function
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        
        try:
            result = func(*args, **kwargs)
            execution_time = (time.time() - start_time) * 1000
            
            logger.info(
                f"Cold start optimization: {func.__name__} completed in {execution_time:.2f}ms",
                extra={
                    'function': func.__name__,
                    'execution_time_ms': execution_time
                }
            )
            
            return result
            
        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            logger.error(
                f"Cold start optimization: {func.__name__} failed after {execution_time:.2f}ms",
                extra={
                    'function': func.__name__,
                    'execution_time_ms': execution_time,
                    'error': str(e)
                }
            )
            raise
    
    return wrapper


def ensure_no_filesystem_persistence(path: str) -> str:
    """
    Ensure file operations use /tmp directory for serverless compatibility
    Vercel and other serverless platforms have read-only filesystems except /tmp
    
    Args:
        path: Original file path
        
    Returns:
        Modified path using /tmp if not already
        
    Requirements: 2.5
    """
    # If running in serverless environment and path is not in /tmp
    is_serverless = os.getenv('VERCEL') or os.getenv('AWS_LAMBDA_FUNCTION_NAME')
    
    if is_serverless and not path.startswith('/tmp'):
        # Extract filename
        filename = os.path.basename(path)
        new_path = os.path.join('/tmp', filename)
        
        logger.debug(f"Redirecting filesystem path from {path} to {new_path}")
        return new_path
    
    return path


def get_cold_start_metrics() -> Dict[str, Any]:
    """
    Get cold start performance metrics
    
    Returns:
        Dictionary with performance metrics
    """
    cache = get_connection_cache()
    cache_stats = cache.get_stats()
    
    return {
        'connection_cache': cache_stats,
        'environment': {
            'is_vercel': bool(os.getenv('VERCEL')),
            'is_lambda': bool(os.getenv('AWS_LAMBDA_FUNCTION_NAME')),
            'python_version': os.sys.version
        }
    }


def warmup_connections():
    """
    Warmup function to pre-initialize connections
    Can be called during application startup or by a warmup endpoint
    
    Requirements: 2.4
    """
    logger.info("Starting connection warmup")
    start_time = time.time()
    
    warmup_results = {
        'started_at': start_time,
        'connections': []
    }
    
    # Warmup database connection if configured
    if os.getenv('ORACLE_CONNECTION_STRING'):
        try:
            from modules.oracle_mcp_server import OracleMCPServer
            oracle_server = OracleMCPServer()
            warmup_results['connections'].append({
                'type': 'oracle',
                'status': 'success'
            })
            logger.info("Oracle connection warmed up")
        except Exception as e:
            warmup_results['connections'].append({
                'type': 'oracle',
                'status': 'failed',
                'error': str(e)
            })
            logger.warning(f"Oracle warmup failed: {str(e)}")
    
    # Warmup PDF server
    try:
        from modules.pdf_mcp_server import PDFMCPServer
        pdf_server = PDFMCPServer()
        warmup_results['connections'].append({
            'type': 'pdf',
            'status': 'success'
        })
        logger.info("PDF server warmed up")
    except Exception as e:
        warmup_results['connections'].append({
            'type': 'pdf',
            'status': 'failed',
            'error': str(e)
        })
        logger.warning(f"PDF warmup failed: {str(e)}")
    
    warmup_time = (time.time() - start_time) * 1000
    warmup_results['duration_ms'] = warmup_time
    
    logger.info(f"Connection warmup completed in {warmup_time:.2f}ms")
    
    return warmup_results
