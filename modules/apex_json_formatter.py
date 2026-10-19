"""
APEX-Compatible JSON Formatter
Formats responses following APEX_JSON patterns
Reference: Oracle APEX API Reference Page 682
"""

import json
from typing import List, Dict, Any, Optional
from datetime import datetime


class ApexJsonFormatter:
    """
    Format responses in APEX-compatible JSON structure
    Reference: APEX_JSON.WRITE patterns (Page 682)
    """
    
    @staticmethod
    def success_response(data: Any, message: str = None) -> Dict[str, Any]:
        """
        Create APEX-style success response
        
        Args:
            data: Response data
            message: Optional success message
            
        Returns:
            APEX-compatible success response
        """
        response = {
            "success": True,
            "data": data
        }
        
        if message:
            response["message"] = message
            
        return response
    
    @staticmethod
    def error_response(
        error_message: str,
        error_code: str = "APEX_ERROR",
        display_location: str = "inline",
        page_item: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create APEX-style error response
        Reference: APEX_ERROR patterns (Page 370)
        
        Args:
            error_message: Error message
            error_code: Error code
            display_location: Where to display error (inline, page, notification)
            page_item: Associated page item name
            
        Returns:
            APEX-compatible error response
        """
        return {
            "success": False,
            "error": {
                "message": error_message,
                "code": error_code,
                "display_location": display_location,
                "page_item_name": page_item,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    
    @staticmethod
    def format_query_results(
        rows: List[Dict],
        columns: List[str] = None,
        total_count: int = None,
        has_more: bool = False
    ) -> Dict[str, Any]:
        """
        Format database query results for APEX
        Reference: APEX_EXEC result patterns (Page 472)
        
        Args:
            rows: Query result rows
            columns: Column names
            total_count: Total row count (if known)
            has_more: Whether more rows exist
            
        Returns:
            APEX-compatible query results
        """
        return {
            "success": True,
            "items": rows,
            "count": len(rows),
            "totalCount": total_count if total_count is not None else len(rows),
            "hasMore": has_more,
            "columns": columns or (list(rows[0].keys()) if rows else [])
        }
    
    @staticmethod
    def format_collection_response(
        collection_name: str,
        members: List[Dict],
        member_count: int = None
    ) -> Dict[str, Any]:
        """
        Format APEX collection-style response
        Reference: APEX_COLLECTION patterns (Page 215)
        
        Args:
            collection_name: Name of the collection
            members: Collection members
            member_count: Total member count
            
        Returns:
            APEX-compatible collection response
        """
        return {
            "success": True,
            "collection": {
                "name": collection_name,
                "members": members,
                "count": member_count if member_count is not None else len(members)
            }
        }
    
    @staticmethod
    def format_chat_message(
        message: str,
        role: str,
        timestamp: datetime = None,
        metadata: Dict = None
    ) -> Dict[str, Any]:
        """
        Format chat message for APEX display
        
        Args:
            message: Message content
            role: Message role (user, assistant, system)
            timestamp: Message timestamp
            metadata: Additional metadata
            
        Returns:
            Formatted chat message
        """
        msg = {
            "message": message,
            "role": role,
            "timestamp": (timestamp or datetime.utcnow()).isoformat()
        }
        
        if metadata:
            msg["metadata"] = metadata
            
        return msg
    
    @staticmethod
    def format_pagination(
        items: List[Any],
        page: int,
        page_size: int,
        total_count: int
    ) -> Dict[str, Any]:
        """
        Format paginated response for APEX
        
        Args:
            items: Page items
            page: Current page number
            page_size: Items per page
            total_count: Total item count
            
        Returns:
            APEX-compatible paginated response
        """
        total_pages = (total_count + page_size - 1) // page_size
        
        return {
            "success": True,
            "items": items,
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "totalCount": total_count,
                "totalPages": total_pages,
                "hasNext": page < total_pages,
                "hasPrevious": page > 1
            }
        }
    
    @staticmethod
    def to_json_string(data: Dict[str, Any], pretty: bool = False) -> str:
        """
        Convert to JSON string
        
        Args:
            data: Data to convert
            pretty: Whether to pretty-print
            
        Returns:
            JSON string
        """
        if pretty:
            return json.dumps(data, indent=2, ensure_ascii=False)
        return json.dumps(data, ensure_ascii=False)
