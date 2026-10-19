"""
Session and Conversation Management Module
Handles session state, conversation history, and session lifecycle
Requirements: 1.3, 1.5, 6.3
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from flask import session

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """Represents a single message in the conversation"""
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: str
    tool_calls: Optional[List[Dict]] = None
    
    def to_dict(self) -> Dict:
        """Convert message to dictionary"""
        return asdict(self)


@dataclass
class ChatSession:
    """Represents a chat session with conversation history"""
    session_id: str
    messages: List[Message]
    created_at: str
    last_activity: str
    
    def to_dict(self) -> Dict:
        """Convert session to dictionary"""
        return {
            'session_id': self.session_id,
            'messages': [msg.to_dict() for msg in self.messages],
            'created_at': self.created_at,
            'last_activity': self.last_activity
        }


class SessionManager:
    """
    Manages chat sessions and conversation history
    Provides session isolation and cleanup functionality
    """
    
    def __init__(self, max_history: int = None, session_timeout: int = None):
        """
        Initialize session manager
        
        Args:
            max_history: Maximum number of messages to keep in history
            session_timeout: Session timeout in seconds
        """
        self.max_history = max_history or int(os.getenv('MAX_CONVERSATION_HISTORY', 50))
        self.session_timeout = session_timeout or int(os.getenv('SESSION_TIMEOUT', 1800))
        logger.info(f"SessionManager initialized with max_history={self.max_history}, timeout={self.session_timeout}s")
    
    def initialize_session(self) -> str:
        """
        Initialize a new session or return existing session ID
        
        Returns:
            Session ID
        """
        if 'session_id' not in session:
            session_id = os.urandom(16).hex()
            session['session_id'] = session_id
            session['created_at'] = datetime.utcnow().isoformat()
            session['conversation_history'] = []
            session.permanent = True
            logger.info(f"New session initialized: {session_id}")
        else:
            session_id = session['session_id']
            logger.debug(f"Existing session found: {session_id}")
        
        # Update last activity
        session['last_activity'] = datetime.utcnow().isoformat()
        
        return session_id
    
    def get_session_id(self) -> Optional[str]:
        """
        Get current session ID
        
        Returns:
            Session ID or None if no session exists
        """
        return session.get('session_id')
    
    def is_session_valid(self) -> bool:
        """
        Check if current session is valid and not expired
        
        Returns:
            True if session is valid, False otherwise
        """
        if 'session_id' not in session or 'last_activity' not in session:
            return False
        
        try:
            last_activity = datetime.fromisoformat(session['last_activity'])
            time_since_activity = datetime.utcnow() - last_activity
            
            if time_since_activity.total_seconds() > self.session_timeout:
                logger.info(f"Session {session['session_id']} expired")
                return False
            
            return True
        except (ValueError, TypeError) as e:
            logger.error(f"Error checking session validity: {str(e)}")
            return False
    
    def add_message(self, role: str, content: str, tool_calls: Optional[List[Dict]] = None) -> Message:
        """
        Add a message to the conversation history
        
        Args:
            role: Message role ('user' or 'assistant')
            content: Message content
            tool_calls: Optional list of tool calls made
            
        Returns:
            Created Message object
        """
        if not self.is_session_valid():
            self.initialize_session()
        
        message = Message(
            role=role,
            content=content,
            timestamp=datetime.utcnow().isoformat(),
            tool_calls=tool_calls
        )
        
        # Get current history
        history = session.get('conversation_history', [])
        history.append(message.to_dict())
        
        # Limit history size
        if len(history) > self.max_history:
            removed_count = len(history) - self.max_history
            history = history[-self.max_history:]
            logger.debug(f"Trimmed {removed_count} messages from history")
        
        # Save back to session
        session['conversation_history'] = history
        session['last_activity'] = datetime.utcnow().isoformat()
        
        logger.debug(f"Added {role} message to session {session['session_id']}")
        return message
    
    def get_conversation_history(self, limit: Optional[int] = None) -> List[Message]:
        """
        Get conversation history for current session
        
        Args:
            limit: Optional limit on number of messages to return
            
        Returns:
            List of Message objects
        """
        if not self.is_session_valid():
            return []
        
        history = session.get('conversation_history', [])
        
        if limit:
            history = history[-limit:]
        
        # Convert dictionaries back to Message objects
        messages = []
        for msg_dict in history:
            try:
                messages.append(Message(**msg_dict))
            except TypeError as e:
                logger.error(f"Error converting message dict to Message object: {str(e)}")
                continue
        
        return messages
    
    def clear_conversation_history(self) -> None:
        """Clear conversation history for current session"""
        if 'session_id' in session:
            session_id = session['session_id']
            session['conversation_history'] = []
            logger.info(f"Cleared conversation history for session {session_id}")
    
    def get_session_info(self) -> Optional[ChatSession]:
        """
        Get complete session information
        
        Returns:
            ChatSession object or None if no valid session
        """
        if not self.is_session_valid():
            return None
        
        messages = self.get_conversation_history()
        
        return ChatSession(
            session_id=session['session_id'],
            messages=messages,
            created_at=session['created_at'],
            last_activity=session['last_activity']
        )
    
    def cleanup_session(self) -> None:
        """Clean up and destroy current session"""
        if 'session_id' in session:
            session_id = session['session_id']
            session.clear()
            logger.info(f"Session {session_id} cleaned up")
    
    def get_message_count(self) -> int:
        """
        Get number of messages in current conversation
        
        Returns:
            Number of messages
        """
        if not self.is_session_valid():
            return 0
        
        return len(session.get('conversation_history', []))
    
    def get_session_duration(self) -> Optional[timedelta]:
        """
        Get duration of current session
        
        Returns:
            timedelta object or None if no valid session
        """
        if not self.is_session_valid():
            return None
        
        try:
            created_at = datetime.fromisoformat(session['created_at'])
            return datetime.utcnow() - created_at
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Error calculating session duration: {str(e)}")
            return None
