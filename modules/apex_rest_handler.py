"""
APEX REST API Handler
Provides REST endpoints compatible with APEX ORDS patterns
Reference: Oracle APEX API Reference - APEX_WEB_SERVICE (Page 1094)
"""

from flask import Blueprint, request, jsonify
from typing import TYPE_CHECKING, Dict, Any, Optional
import logging

from modules.apex_json_formatter import ApexJsonFormatter
from modules.oracle_mcp_server import OracleMCPServer
from modules.pdf_mcp_server import PDFMCPServer
from modules.llm_service import LLMService

if TYPE_CHECKING:
    from modules.yugabyte_mcp_server import YugabyteMCPServer

logger = logging.getLogger(__name__)

# Create Blueprint for APEX REST endpoints
apex_api = Blueprint('apex_api', __name__, url_prefix='/ords/chatbot/api')


class ApexRestHandler:
    """
    Handle REST requests from APEX application
    Follows ORDS REST patterns
    """
    
    def __init__(
        self,
        oracle_server: OracleMCPServer,
        pdf_server: PDFMCPServer,
        llm_service: LLMService,
        yugabyte_server: Optional['YugabyteMCPServer'] = None,
    ):
        self.oracle_server = oracle_server
        self.pdf_server = pdf_server
        self.llm_service = llm_service
        self.yugabyte_server = yugabyte_server
        self.formatter = ApexJsonFormatter()
    
    def query_view(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Query Oracle view - APEX compatible
        Reference: APEX_EXEC patterns (Page 472)
        """
        try:
            view_name = data.get('view_name')
            where_clause = data.get('where_clause')
            limit = data.get('limit', 100)
            
            if not view_name:
                return self.formatter.error_response(
                    "view_name is required",
                    error_code="MISSING_PARAMETER",
                    page_item="P1_VIEW_NAME"
                )
            
            result = self.oracle_server.query_view(
                view_name=view_name,
                where_clause=where_clause,
                limit=limit
            )
            
            if result.get('success'):
                return self.formatter.format_query_results(
                    rows=result['rows'],
                    columns=result['columns'],
                    total_count=result['row_count'],
                    has_more=result.get('limited', False)
                )
            else:
                return self.formatter.error_response(
                    result.get('error', 'Query failed'),
                    error_code="QUERY_ERROR"
                )
                
        except Exception as e:
            logger.error(f"Error querying view: {str(e)}")
            return self.formatter.error_response(
                str(e),
                error_code="INTERNAL_ERROR"
            )
    
    def search_documents(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search PDF documents - APEX compatible
        Reference: Oracle Text search patterns
        """
        try:
            query = data.get('query')
            limit = data.get('limit', 10)
            
            if not query:
                return self.formatter.error_response(
                    "query is required",
                    error_code="MISSING_PARAMETER",
                    page_item="P1_SEARCH_QUERY"
                )
            
            result = self.pdf_server.search_pdfs(query, limit)
            
            if result.get('success'):
                return self.formatter.format_query_results(
                    rows=result['results'],
                    total_count=result['count'],
                    has_more=result.get('limited', False)
                )
            else:
                return self.formatter.error_response(
                    result.get('error', 'Search failed'),
                    error_code="SEARCH_ERROR"
                )
                
        except Exception as e:
            logger.error(f"Error searching documents: {str(e)}")
            return self.formatter.error_response(
                str(e),
                error_code="INTERNAL_ERROR"
            )
    
    def process_chat_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process chat message from APEX
        Reference: APEX_COLLECTION for chat history (Page 215)
        """
        try:
            message = data.get('message')
            session_id = data.get('session_id')
            context = data.get('context', [])
            
            if not message:
                return self.formatter.error_response(
                    "message is required",
                    error_code="MISSING_PARAMETER",
                    page_item="P1_MESSAGE"
                )
            
            # Process with LLM
            response = self.llm_service.generate_response(
                user_message=message,
                conversation_history=context
            )
            
            # Format as chat message
            chat_response = {
                "user_message": self.formatter.format_chat_message(
                    message=message,
                    role="user"
                ),
                "assistant_message": self.formatter.format_chat_message(
                    message=response,
                    role="assistant"
                )
            }
            
            return self.formatter.success_response(
                chat_response,
                message="Message processed successfully"
            )
            
        except Exception as e:
            logger.error(f"Error processing chat message: {str(e)}")
            return self.formatter.error_response(
                str(e),
                error_code="CHAT_ERROR"
            )
    
    def list_views(self) -> Dict[str, Any]:
        """
        List available Oracle views
        """
        try:
            result = self.oracle_server.list_views()
            
            if result.get('success'):
                return self.formatter.format_query_results(
                    rows=result['views'],
                    total_count=result['count']
                )
            else:
                return self.formatter.error_response(
                    result.get('error', 'Failed to list views'),
                    error_code="LIST_ERROR"
                )
                
        except Exception as e:
            logger.error(f"Error listing views: {str(e)}")
            return self.formatter.error_response(
                str(e),
                error_code="INTERNAL_ERROR"
            )
    
    def list_documents(self) -> Dict[str, Any]:
        """
        List available PDF documents
        """
        try:
            result = self.pdf_server.list_documents()
            
            if result.get('success'):
                return self.formatter.format_query_results(
                    rows=result['documents'],
                    total_count=result['count']
                )
            else:
                return self.formatter.error_response(
                    result.get('error', 'Failed to list documents'),
                    error_code="LIST_ERROR"
                )
                
        except Exception as e:
            logger.error(f"Error listing documents: {str(e)}")
            return self.formatter.error_response(
                str(e),
                error_code="INTERNAL_ERROR"
            )
    
    def health_check(self) -> Dict[str, Any]:
        """
        Health check endpoint for APEX monitoring
        """
        try:
            oracle_health = self.oracle_server.health_check() if self.oracle_server else {"status": "disabled"}
            pdf_health = self.pdf_server.health_check()
            yugabyte_health = (
                self.yugabyte_server.health_check() if self.yugabyte_server else {"status": "disabled"}
            )

            overall_status = "healthy" if (
                oracle_health.get('status') in ['healthy', 'disabled'] and
                pdf_health.get('status') == 'healthy' and
                yugabyte_health.get('status') in ['healthy', 'disabled']
            ) else "unhealthy"

            return self.formatter.success_response({
                "status": overall_status,
                "services": {
                    "oracle": oracle_health,
                    "pdf": pdf_health,
                    "yugabyte": yugabyte_health,
                }
            })

        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return self.formatter.error_response(
                str(e),
                error_code="HEALTH_CHECK_ERROR"
            )


# Flask route handlers
def register_apex_routes(app, handler: ApexRestHandler):
    """
    Register APEX-compatible REST routes
    """
    
    @apex_api.route('/query', methods=['POST'])
    def query_view():
        """Query Oracle view"""
        return jsonify(handler.query_view(request.json or {}))
    
    @apex_api.route('/search', methods=['POST'])
    def search_documents():
        """Search PDF documents"""
        return jsonify(handler.search_documents(request.json or {}))
    
    @apex_api.route('/chat', methods=['POST'])
    def process_chat():
        """Process chat message"""
        return jsonify(handler.process_chat_message(request.json or {}))
    
    @apex_api.route('/views', methods=['GET'])
    def list_views():
        """List available views"""
        return jsonify(handler.list_views())
    
    @apex_api.route('/documents', methods=['GET'])
    def list_documents():
        """List available documents"""
        return jsonify(handler.list_documents())
    
    @apex_api.route('/health', methods=['GET'])
    def health_check():
        """Health check"""
        return jsonify(handler.health_check())
    
    # Register blueprint
    app.register_blueprint(apex_api)
    
    logger.info("APEX REST API routes registered at /ords/chatbot/api")
