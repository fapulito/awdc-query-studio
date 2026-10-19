"""
Activity Tracker Module for User Activity Monitoring

This module tracks user activity including logins, messages, and logouts
for analytics purposes. It implements privacy-preserving hashing for user
identifiers and stores activity data in JSON Lines format.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6
"""

import os
import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)


class ActivityTracker:
    """
    Track user activity and generate analytics.
    
    This class provides methods to log user activities (login, message, logout)
    and retrieve statistics for individual users or globally. All user identifiers
    are hashed for privacy protection.
    
    Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6
    """
    
    def __init__(self, storage_dir: str = './analytics', retention_days: int = 90):
        """
        Initialize activity tracker with storage backend.
        
        Args:
            storage_dir: Directory for storing activity logs
            retention_days: Number of days to retain activity data (default: 90)
            
        Requirements: 8.5
        """
        self.storage_dir = Path(storage_dir)
        self.retention_days = retention_days
        
        # Create storage directory if it doesn't exist
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            logger.info(
                f"Activity tracker initialized",
                extra={'storage_dir': str(self.storage_dir), 'retention_days': retention_days}
            )
        except Exception as e:
            logger.error(f"Failed to create analytics directory: {str(e)}")
            raise
    
    def _hash_identifier(self, identifier: str) -> str:
        """
        Create privacy-preserving hash of user identifier.
        
        Uses SHA-256 hashing to anonymize user identifiers while maintaining
        the ability to track individual users across sessions.
        
        Args:
            identifier: User identifier (email, user_id, IP address, etc.)
            
        Returns:
            Hashed identifier string
            
        Requirements: 8.6
        """
        if not identifier:
            return "anonymous"
        
        # Use SHA-256 for hashing
        hash_obj = hashlib.sha256(identifier.encode('utf-8'))
        return hash_obj.hexdigest()
    
    def _get_log_file_path(self, date: Optional[datetime] = None) -> Path:
        """
        Get the log file path for a specific date.
        
        Args:
            date: Date for the log file (default: today)
            
        Returns:
            Path to the log file
            
        Requirements: 8.5
        """
        if date is None:
            date = datetime.utcnow()
        
        filename = f"activity_{date.strftime('%Y-%m-%d')}.jsonl"
        return self.storage_dir / filename
    
    def _write_event(self, event_data: Dict) -> bool:
        """
        Write an event to the activity log file.
        
        Uses JSON Lines format for efficient append operations and easy parsing.
        Implements error handling for storage failures.
        
        Args:
            event_data: Dictionary containing event information
            
        Returns:
            True if successful, False otherwise
            
        Requirements: 8.5
        """
        try:
            log_file = self._get_log_file_path()
            
            # Append event as JSON line
            with open(log_file, 'a', encoding='utf-8') as f:
                json.dump(event_data, f)
                f.write('\n')
            
            return True
            
        except Exception as e:
            logger.error(
                f"Failed to write activity event: {str(e)}",
                extra={'event_type': event_data.get('event_type'), 'error': str(e)}
            )
            return False
    
    def log_login(self, user_id: str, provider: str, timestamp: Optional[datetime] = None,
                  metadata: Optional[Dict] = None) -> bool:
        """
        Log user login event.
        
        Args:
            user_id: User identifier (will be hashed)
            provider: OAuth2 provider name (google, github, etc.)
            timestamp: Event timestamp (default: current time)
            metadata: Additional metadata (user_agent, ip_address, etc.)
            
        Returns:
            True if logged successfully, False otherwise
            
        Requirements: 8.1, 8.6
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        # Hash user identifier for privacy
        hashed_user_id = self._hash_identifier(user_id)
        
        event_data = {
            'event_type': 'login',
            'user_id': hashed_user_id,
            'provider': provider,
            'timestamp': timestamp.isoformat(),
            'metadata': metadata or {}
        }
        
        # Hash IP address if present in metadata
        if metadata and 'ip_address' in metadata:
            event_data['metadata']['ip_address'] = self._hash_identifier(metadata['ip_address'])
        
        success = self._write_event(event_data)
        
        if success:
            logger.info(
                f"Login event logged",
                extra={'provider': provider, 'hashed_user_id': hashed_user_id[:16]}
            )
        
        return success
    
    def log_message(self, user_id: str, session_id: str, timestamp: Optional[datetime] = None,
                    metadata: Optional[Dict] = None) -> bool:
        """
        Log message sent event (without content).
        
        IMPORTANT: This method NEVER logs message content, only that a message was sent.
        This ensures user privacy and compliance with data protection regulations.
        
        Args:
            user_id: User identifier (will be hashed)
            session_id: Session identifier
            timestamp: Event timestamp (default: current time)
            metadata: Additional metadata (user_agent, etc.)
            
        Returns:
            True if logged successfully, False otherwise
            
        Requirements: 8.2, 8.6
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        # Hash user identifier for privacy
        hashed_user_id = self._hash_identifier(user_id)
        
        event_data = {
            'event_type': 'message',
            'user_id': hashed_user_id,
            'session_id': session_id,
            'timestamp': timestamp.isoformat(),
            'metadata': metadata or {}
        }
        
        success = self._write_event(event_data)
        
        if success:
            logger.debug(
                f"Message event logged",
                extra={'session_id': session_id, 'hashed_user_id': hashed_user_id[:16]}
            )
        
        return success
    
    def log_logout(self, user_id: str, session_duration: int, timestamp: Optional[datetime] = None,
                   message_count: int = 0, metadata: Optional[Dict] = None) -> bool:
        """
        Log user logout event with session duration.
        
        Args:
            user_id: User identifier (will be hashed)
            session_duration: Session duration in seconds
            timestamp: Event timestamp (default: current time)
            message_count: Number of messages sent during session
            metadata: Additional metadata
            
        Returns:
            True if logged successfully, False otherwise
            
        Requirements: 8.3, 8.6
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        # Hash user identifier for privacy
        hashed_user_id = self._hash_identifier(user_id)
        
        event_data = {
            'event_type': 'logout',
            'user_id': hashed_user_id,
            'session_duration': session_duration,
            'message_count': message_count,
            'timestamp': timestamp.isoformat(),
            'metadata': metadata or {}
        }
        
        success = self._write_event(event_data)
        
        if success:
            logger.info(
                f"Logout event logged",
                extra={
                    'hashed_user_id': hashed_user_id[:16],
                    'session_duration': session_duration,
                    'message_count': message_count
                }
            )
        
        return success

    def _read_events(self, start_date: Optional[datetime] = None,
                     end_date: Optional[datetime] = None) -> List[Dict]:
        """
        Read events from log files within a date range.
        
        Args:
            start_date: Start date for filtering (default: 90 days ago)
            end_date: End date for filtering (default: today)
            
        Returns:
            List of event dictionaries
            
        Requirements: 8.4, 8.5
        """
        if end_date is None:
            end_date = datetime.utcnow()
        
        if start_date is None:
            start_date = end_date - timedelta(days=self.retention_days)
        
        events = []
        current_date = start_date.date()
        end = end_date.date()
        
        while current_date <= end:
            log_file = self._get_log_file_path(datetime.combine(current_date, datetime.min.time()))
            
            if log_file.exists():
                try:
                    with open(log_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    event = json.loads(line)
                                    event_time = datetime.fromisoformat(event['timestamp'])
                                    
                                    # Filter by time range
                                    if start_date <= event_time <= end_date:
                                        events.append(event)
                                except json.JSONDecodeError:
                                    logger.warning(f"Invalid JSON in log file: {log_file}")
                                    continue
                except Exception as e:
                    logger.error(f"Error reading log file {log_file}: {str(e)}")
            
            current_date += timedelta(days=1)
        
        return events
    
    def get_user_stats(self, user_id: str, start_date: Optional[datetime] = None,
                       end_date: Optional[datetime] = None) -> Dict:
        """
        Get statistics for a specific user.
        
        Args:
            user_id: User identifier (will be hashed for lookup)
            start_date: Start date for statistics (default: 90 days ago)
            end_date: End date for statistics (default: today)
            
        Returns:
            Dictionary containing user statistics
            
        Requirements: 8.4
        """
        hashed_user_id = self._hash_identifier(user_id)
        events = self._read_events(start_date, end_date)
        
        # Filter events for this user
        user_events = [e for e in events if e.get('user_id') == hashed_user_id]
        
        # Calculate statistics
        login_count = sum(1 for e in user_events if e['event_type'] == 'login')
        message_count = sum(1 for e in user_events if e['event_type'] == 'message')
        logout_events = [e for e in user_events if e['event_type'] == 'logout']
        
        total_session_duration = sum(e.get('session_duration', 0) for e in logout_events)
        avg_session_duration = total_session_duration / len(logout_events) if logout_events else 0
        
        # Get provider breakdown
        providers = {}
        for event in user_events:
            if event['event_type'] == 'login':
                provider = event.get('provider', 'unknown')
                providers[provider] = providers.get(provider, 0) + 1
        
        return {
            'user_id': hashed_user_id[:16],  # Truncated for display
            'login_count': login_count,
            'message_count': message_count,
            'session_count': len(logout_events),
            'total_session_duration': total_session_duration,
            'avg_session_duration': avg_session_duration,
            'providers': providers,
            'date_range': {
                'start': start_date.isoformat() if start_date else None,
                'end': end_date.isoformat() if end_date else None
            }
        }
    
    def get_global_stats(self, start_date: Optional[datetime] = None,
                        end_date: Optional[datetime] = None) -> Dict:
        """
        Get global usage statistics for date range.
        
        Args:
            start_date: Start date for statistics (default: 90 days ago)
            end_date: End date for statistics (default: today)
            
        Returns:
            Dictionary containing global statistics
            
        Requirements: 8.4
        """
        events = self._read_events(start_date, end_date)
        
        if not events:
            return {
                'total_users': 0,
                'total_sessions': 0,
                'total_messages': 0,
                'total_logins': 0,
                'avg_session_duration': 0,
                'active_users_today': 0,
                'peak_usage_hours': {},
                'provider_breakdown': {},
                'date_range': {
                    'start': start_date.isoformat() if start_date else None,
                    'end': end_date.isoformat() if end_date else None
                }
            }
        
        # Calculate unique users
        unique_users = set(e.get('user_id') for e in events if e.get('user_id'))
        
        # Count events by type
        login_events = [e for e in events if e['event_type'] == 'login']
        message_events = [e for e in events if e['event_type'] == 'message']
        logout_events = [e for e in events if e['event_type'] == 'logout']
        
        # Calculate session statistics
        total_session_duration = sum(e.get('session_duration', 0) for e in logout_events)
        avg_session_duration = total_session_duration / len(logout_events) if logout_events else 0
        
        # Calculate active users today
        today = datetime.utcnow().date()
        active_today = set()
        for event in events:
            event_date = datetime.fromisoformat(event['timestamp']).date()
            if event_date == today:
                active_today.add(event.get('user_id'))
        
        # Calculate peak usage hours
        hour_counts = {}
        for event in message_events:
            hour = datetime.fromisoformat(event['timestamp']).hour
            hour_counts[hour] = hour_counts.get(hour, 0) + 1
        
        # Get top 5 peak hours
        peak_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        peak_usage_hours = {f"{h:02d}:00": count for h, count in peak_hours}
        
        # Provider breakdown
        provider_breakdown = {}
        for event in login_events:
            provider = event.get('provider', 'unknown')
            provider_breakdown[provider] = provider_breakdown.get(provider, 0) + 1
        
        return {
            'total_users': len(unique_users),
            'total_sessions': len(logout_events),
            'total_messages': len(message_events),
            'total_logins': len(login_events),
            'avg_session_duration': round(avg_session_duration, 2),
            'active_users_today': len(active_today),
            'peak_usage_hours': peak_usage_hours,
            'provider_breakdown': provider_breakdown,
            'date_range': {
                'start': start_date.isoformat() if start_date else None,
                'end': end_date.isoformat() if end_date else None
            }
        }
    
    def cleanup_old_logs(self) -> int:
        """
        Remove log files older than retention period.
        
        Implements data retention policy by deleting files older than
        the configured retention_days.
        
        Returns:
            Number of files deleted
            
        Requirements: 8.5
        """
        cutoff_date = datetime.utcnow() - timedelta(days=self.retention_days)
        deleted_count = 0
        
        try:
            for log_file in self.storage_dir.glob('activity_*.jsonl'):
                # Extract date from filename
                try:
                    date_str = log_file.stem.replace('activity_', '')
                    file_date = datetime.strptime(date_str, '%Y-%m-%d')
                    
                    if file_date < cutoff_date:
                        log_file.unlink()
                        deleted_count += 1
                        logger.info(f"Deleted old activity log: {log_file.name}")
                except (ValueError, OSError) as e:
                    logger.warning(f"Error processing log file {log_file}: {str(e)}")
                    continue
            
            if deleted_count > 0:
                logger.info(
                    f"Cleaned up {deleted_count} old activity log(s)",
                    extra={'deleted_count': deleted_count, 'retention_days': self.retention_days}
                )
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error during log cleanup: {str(e)}")
            return deleted_count


# Global activity tracker instance
_activity_tracker = None


def get_activity_tracker() -> ActivityTracker:
    """
    Get or create the global activity tracker instance.
    
    Returns:
        ActivityTracker instance
    """
    global _activity_tracker
    
    if _activity_tracker is None:
        _activity_tracker = ActivityTracker()
    
    return _activity_tracker
