"""
PDF Connector MCP Server Module

This module provides MCP server functionality for PDF document access.
It implements PDF text extraction, indexing, and search capabilities
with support for multiple PDF formats.
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime
import re
from modules.error_handler import (
    PDFProcessingError, ValidationError,
    handle_pdf_errors, log_error_with_context
)
from modules.serverless_optimizer import ensure_no_filesystem_persistence

# Suppress pdfminer debug logging to avoid format string errors
logging.getLogger('pdfminer').setLevel(logging.WARNING)
logging.getLogger('pdfminer.psparser').setLevel(logging.WARNING)
logging.getLogger('pdfminer.pdfdocument').setLevel(logging.WARNING)

try:
    import pdfplumber
    PDF_LIBRARY = 'pdfplumber'
except ImportError:
    try:
        import PyPDF2
        PDF_LIBRARY = 'PyPDF2'
    except ImportError:
        raise ImportError("Neither pdfplumber nor PyPDF2 is installed. Please install one of them.")

logger = logging.getLogger(__name__)


class PDFMCPServer:
    """
    MCP Server for PDF document integration.
    
    Provides tools for searching PDF content, retrieving documents,
    and listing available PDFs with text extraction and indexing.
    """
    
    def __init__(self):
        """
        Initialize PDF MCP Server with configuration from environment variables.
        Optimized for serverless deployment with proper filesystem handling.
        Requirements: 2.5
        """
        self.storage_path = os.getenv('PDF_STORAGE_PATH', './pdfs')
        # Ensure index file uses /tmp in serverless environments
        index_file = os.getenv('PDF_INDEX_FILE', './pdf_index.json')
        self.index_file = ensure_no_filesystem_persistence(index_file)
        self.max_search_results = int(os.getenv('PDF_MAX_SEARCH_RESULTS', '10'))
        self.index_refresh_interval = int(os.getenv('PDF_INDEX_REFRESH_INTERVAL', '3600'))
        
        self.index: Dict[str, Any] = {}
        self.last_index_time: Optional[datetime] = None
        
        self._validate_configuration()
        self._ensure_storage_path()
        
        # Skip indexing on initialization for Vercel (lazy load on first use)
        # This prevents cold start timeout and logging errors
        skip_initial_index = os.getenv('SKIP_INITIAL_PDF_INDEX', 'false').lower() == 'true'
        if not skip_initial_index:
            self._load_or_create_index()
        else:
            logger.info("Skipping initial PDF indexing (will index on first use)")
    
    def _validate_configuration(self) -> None:
        """
        Validate that all required configuration is present.
        
        Raises:
            ValueError: If required configuration is invalid
        """
        if not self.storage_path:
            raise ValueError("PDF_STORAGE_PATH environment variable is required")
        
        logger.info(f"PDF MCP Server initialized with library: {PDF_LIBRARY}")
        logger.info(f"Storage path: {self.storage_path}")
    
    def _ensure_storage_path(self) -> None:
        """
        Ensure the PDF storage path exists.
        Creates the directory if it doesn't exist.
        """
        storage_dir = Path(self.storage_path)
        if not storage_dir.exists():
            logger.warning(f"Storage path does not exist: {self.storage_path}")
            try:
                storage_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created storage directory: {self.storage_path}")
            except Exception as e:
                logger.error(f"Failed to create storage directory: {str(e)}")
    
    def _load_or_create_index(self) -> None:
        """
        Load existing index from file or create a new one.
        """
        index_path = Path(self.index_file)
        
        if index_path.exists():
            try:
                with open(index_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.index = data.get('documents', {})
                    self.last_index_time = datetime.fromisoformat(data.get('last_updated', datetime.now().isoformat()))
                logger.info(f"Loaded index with {len(self.index)} document(s)")
            except Exception as e:
                logger.error(f"Failed to load index: {str(e)}")
                self.index = {}
                self.last_index_time = None
        else:
            logger.info("No existing index found, will create new index")
            self.index = {}
            self.last_index_time = None
        
        # Perform initial indexing
        self.refresh_index()

    def _extract_text_pdfplumber(self, pdf_path: Path) -> List[Dict[str, Any]]:
        """
        Extract text from PDF using pdfplumber library.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            List of dictionaries containing page number and text
        """
        pages_data = []
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    text = page.extract_text()
                    if text:
                        pages_data.append({
                            'page': page_num,
                            'text': text.strip()
                        })
        except Exception as e:
            logger.error(f"Error extracting text from {pdf_path.name} with pdfplumber: {str(e)}")
            raise
        
        return pages_data
    
    def _extract_text_pypdf2(self, pdf_path: Path) -> List[Dict[str, Any]]:
        """
        Extract text from PDF using PyPDF2 library.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            List of dictionaries containing page number and text
        """
        pages_data = []
        
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                
                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]
                    text = page.extract_text()
                    
                    if text:
                        pages_data.append({
                            'page': page_num + 1,
                            'text': text.strip()
                        })
        except Exception as e:
            logger.error(f"Error extracting text from {pdf_path.name} with PyPDF2: {str(e)}")
            raise
        
        return pages_data
    
    def _extract_text_from_pdf(self, pdf_path: Path) -> List[Dict[str, Any]]:
        """
        Extract text from a PDF file using the available library.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            List of dictionaries containing page number and text
        """
        if PDF_LIBRARY == 'pdfplumber':
            return self._extract_text_pdfplumber(pdf_path)
        else:
            return self._extract_text_pypdf2(pdf_path)
    
    def _index_pdf(self, pdf_path: Path) -> Optional[Dict[str, Any]]:
        """
        Index a single PDF file with comprehensive error handling.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Dictionary containing indexed document data or None on failure
        """
        try:
            logger.info(f"Indexing PDF: {pdf_path.name}")
            
            # Extract text from all pages
            try:
                pages_data = self._extract_text_from_pdf(pdf_path)
            except Exception as e:
                raise PDFProcessingError(
                    pdf_path.name,
                    f"Text extraction failed: {str(e)}",
                    {"library": PDF_LIBRARY}
                )
            
            if not pages_data:
                logger.warning(f"No text extracted from {pdf_path.name}")
                raise PDFProcessingError(
                    pdf_path.name,
                    "No text content found in PDF",
                    {"library": PDF_LIBRARY}
                )
            
            # Get file metadata
            try:
                file_stats = pdf_path.stat()
            except OSError as e:
                raise PDFProcessingError(
                    pdf_path.name,
                    f"Failed to read file metadata: {str(e)}"
                )
            
            # Create document index entry
            doc_data = {
                'filename': pdf_path.name,
                'path': str(pdf_path),
                'pages': pages_data,
                'page_count': len(pages_data),
                'file_size': file_stats.st_size,
                'modified_time': datetime.fromtimestamp(file_stats.st_mtime).isoformat(),
                'indexed_time': datetime.now().isoformat()
            }
            
            logger.info(f"Successfully indexed {pdf_path.name} ({len(pages_data)} pages)")
            return doc_data
            
        except PDFProcessingError:
            # Re-raise our custom exception
            raise
        except Exception as e:
            log_error_with_context(e, {
                "filename": pdf_path.name,
                "path": str(pdf_path)
            })
            raise PDFProcessingError(
                pdf_path.name,
                f"Unexpected error during indexing: {str(e)}"
            )
    
    @handle_pdf_errors
    def refresh_index(self, force: bool = False) -> Dict[str, Any]:
        """
        Refresh the PDF index by scanning the storage directory with error handling.
        Performs incremental indexing for new or modified files.
        
        Args:
            force: If True, re-index all files regardless of modification time
            
        Returns:
            Dictionary containing indexing results
        """
        try:
            storage_dir = Path(self.storage_path)
            
            if not storage_dir.exists():
                return {
                    "success": False,
                    "error": f"Storage path does not exist: {self.storage_path}"
                }
            
            # Find all PDF files
            try:
                pdf_files = list(storage_dir.glob('*.pdf')) + list(storage_dir.glob('*.PDF'))
            except Exception as e:
                log_error_with_context(e, {"storage_path": self.storage_path})
                return {
                    "success": False,
                    "error": f"Failed to scan storage directory: {str(e)}"
                }
            
            if not pdf_files:
                logger.info(f"No PDF files found in {self.storage_path}")
                return {
                    "success": True,
                    "message": "No PDF files found",
                    "indexed": 0,
                    "skipped": 0,
                    "failed": 0
                }
            
            indexed_count = 0
            skipped_count = 0
            failed_count = 0
            failed_files = []
            
            for pdf_path in pdf_files:
                filename = pdf_path.name
                
                # Check if file needs re-indexing
                needs_indexing = force
                
                if not needs_indexing and filename in self.index:
                    # Check if file was modified since last indexing
                    try:
                        file_mtime = datetime.fromtimestamp(pdf_path.stat().st_mtime)
                        indexed_time = datetime.fromisoformat(self.index[filename]['indexed_time'])
                        
                        if file_mtime > indexed_time:
                            needs_indexing = True
                            logger.info(f"{filename} was modified, re-indexing")
                        else:
                            skipped_count += 1
                            continue
                    except Exception as e:
                        logger.warning(f"Failed to check modification time for {filename}: {str(e)}")
                        needs_indexing = True
                elif filename not in self.index:
                    needs_indexing = True
                
                if needs_indexing:
                    try:
                        doc_data = self._index_pdf(pdf_path)
                        
                        if doc_data:
                            self.index[filename] = doc_data
                            indexed_count += 1
                        else:
                            failed_count += 1
                            failed_files.append(filename)
                    except PDFProcessingError as e:
                        logger.error(f"Failed to index {filename}: {e.message}")
                        failed_count += 1
                        failed_files.append(filename)
                    except Exception as e:
                        logger.error(f"Unexpected error indexing {filename}: {str(e)}", exc_info=True)
                        failed_count += 1
                        failed_files.append(filename)
            
            # Save index to file
            try:
                self._save_index()
                self.last_index_time = datetime.now()
            except Exception as e:
                logger.error(f"Failed to save index: {str(e)}")
                # Continue anyway - index is still in memory
            
            result = {
                "success": True,
                "message": f"Index refresh complete",
                "total_files": len(pdf_files),
                "indexed": indexed_count,
                "skipped": skipped_count,
                "failed": failed_count,
                "total_documents": len(self.index)
            }
            
            if failed_files:
                result["failed_files"] = failed_files
            
            logger.info(
                f"Index refresh complete: {indexed_count} indexed, "
                f"{skipped_count} skipped, {failed_count} failed"
            )
            
            return result
            
        except Exception as e:
            log_error_with_context(e, {"storage_path": self.storage_path, "force": force})
            return {
                "success": False,
                "error": f"Failed to refresh index: {str(e)}"
            }
    
    def _save_index(self) -> None:
        """
        Save the current index to file.
        """
        try:
            index_data = {
                'last_updated': datetime.now().isoformat(),
                'document_count': len(self.index),
                'documents': self.index
            }
            
            index_path = Path(self.index_file)
            index_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(index_path, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"Index saved to {self.index_file}")
            
        except Exception as e:
            logger.error(f"Failed to save index: {str(e)}")

    def list_documents(self) -> Dict[str, Any]:
        """
        List all available PDF documents in the index.
        
        Returns:
            Dictionary containing list of documents with metadata
        """
        try:
            if not self.index:
                return {
                    "success": True,
                    "documents": [],
                    "count": 0,
                    "message": "No documents indexed"
                }
            
            documents = []
            for filename, doc_data in self.index.items():
                documents.append({
                    'filename': filename,
                    'page_count': doc_data['page_count'],
                    'file_size': doc_data['file_size'],
                    'modified_time': doc_data['modified_time'],
                    'indexed_time': doc_data['indexed_time']
                })
            
            # Sort by filename
            documents.sort(key=lambda x: x['filename'])
            
            return {
                "success": True,
                "documents": documents,
                "count": len(documents)
            }
            
        except Exception as e:
            logger.error(f"Error listing documents: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to list documents: {str(e)}"
            }
    
    def get_document(self, filename: str) -> Dict[str, Any]:
        """
        Retrieve full content of a specific PDF document.
        
        Args:
            filename: Name of the PDF file
            
        Returns:
            Dictionary containing document content and metadata
        """
        try:
            if filename not in self.index:
                return {
                    "success": False,
                    "error": f"Document '{filename}' not found in index"
                }
            
            doc_data = self.index[filename]
            
            return {
                "success": True,
                "filename": filename,
                "page_count": doc_data['page_count'],
                "pages": doc_data['pages'],
                "file_size": doc_data['file_size'],
                "modified_time": doc_data['modified_time']
            }
            
        except Exception as e:
            logger.error(f"Error retrieving document {filename}: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to retrieve document: {str(e)}"
            }
    
    def _calculate_relevance_score(self, text: str, keywords: List[str]) -> float:
        """
        Calculate relevance score for a text based on keyword matches.
        
        Args:
            text: Text to score
            keywords: List of keywords to search for
            
        Returns:
            Relevance score (higher is more relevant)
        """
        text_lower = text.lower()
        score = 0.0
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            
            # Count exact matches
            exact_matches = text_lower.count(keyword_lower)
            score += exact_matches * 2.0
            
            # Count word boundary matches (more relevant)
            word_pattern = r'\b' + re.escape(keyword_lower) + r'\b'
            word_matches = len(re.findall(word_pattern, text_lower))
            score += word_matches * 3.0
        
        return score
    
    def _extract_context(self, text: str, keywords: List[str], context_chars: int = 150) -> str:
        """
        Extract relevant context around keyword matches.
        
        Args:
            text: Full text
            keywords: Keywords to find
            context_chars: Number of characters to include around match
            
        Returns:
            Excerpt with context around keywords
        """
        text_lower = text.lower()
        
        # Find first keyword match
        for keyword in keywords:
            keyword_lower = keyword.lower()
            pos = text_lower.find(keyword_lower)
            
            if pos != -1:
                # Extract context around the match
                start = max(0, pos - context_chars)
                end = min(len(text), pos + len(keyword) + context_chars)
                
                excerpt = text[start:end].strip()
                
                # Add ellipsis if truncated
                if start > 0:
                    excerpt = '...' + excerpt
                if end < len(text):
                    excerpt = excerpt + '...'
                
                return excerpt
        
        # If no match found, return beginning of text
        return text[:context_chars * 2].strip() + ('...' if len(text) > context_chars * 2 else '')
    
    def search_pdfs(self, query: str, limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Search across all indexed PDF documents for the given query.
        
        Args:
            query: Search query string
            limit: Maximum number of results to return
            
        Returns:
            Dictionary containing search results with relevance ranking
        """
        try:
            if not query or not query.strip():
                return {
                    "success": False,
                    "error": "Search query cannot be empty"
                }
            
            if not self.index:
                return {
                    "success": True,
                    "results": [],
                    "count": 0,
                    "message": "No documents indexed"
                }
            
            # Parse query into keywords
            keywords = [kw.strip() for kw in query.split() if kw.strip()]
            
            if not keywords:
                return {
                    "success": False,
                    "error": "No valid keywords in query"
                }
            
            # Search through all documents
            results = []
            
            for filename, doc_data in self.index.items():
                for page_data in doc_data['pages']:
                    page_num = page_data['page']
                    page_text = page_data['text']
                    
                    # Check if any keyword matches
                    text_lower = page_text.lower()
                    has_match = any(kw.lower() in text_lower for kw in keywords)
                    
                    if has_match:
                        # Calculate relevance score
                        score = self._calculate_relevance_score(page_text, keywords)
                        
                        # Extract context
                        excerpt = self._extract_context(page_text, keywords)
                        
                        results.append({
                            'filename': filename,
                            'page': page_num,
                            'excerpt': excerpt,
                            'relevance_score': score
                        })
            
            # Sort by relevance score (descending)
            results.sort(key=lambda x: x['relevance_score'], reverse=True)
            
            # Apply limit
            result_limit = limit or self.max_search_results
            results = results[:result_limit]
            
            return {
                "success": True,
                "query": query,
                "results": results,
                "count": len(results),
                "limited": len(results) >= result_limit
            }
            
        except Exception as e:
            logger.error(f"Error searching PDFs: {str(e)}")
            return {
                "success": False,
                "error": f"Search failed: {str(e)}"
            }

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """
        Get MCP tool definitions for this server.
        
        Returns:
            List of tool definitions in MCP format
        """
        return [
            {
                "name": "search_pdfs",
                "description": "Search across all indexed PDF documents for the given query",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query string"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results to return"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "get_document",
                "description": "Retrieve full content of a specific PDF document",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Name of the PDF file"
                        }
                    },
                    "required": ["filename"]
                }
            },
            {
                "name": "list_documents",
                "description": "List all available PDF documents in the index",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        ]
    
    def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute an MCP tool by name.
        
        Args:
            tool_name: Name of the tool to execute
            parameters: Tool parameters
            
        Returns:
            Tool execution result
        """
        if tool_name == "search_pdfs":
            return self.search_pdfs(
                query=parameters.get("query"),
                limit=parameters.get("limit")
            )
        elif tool_name == "get_document":
            return self.get_document(filename=parameters.get("filename"))
        elif tool_name == "list_documents":
            return self.list_documents()
        else:
            return {
                "success": False,
                "error": f"Unknown tool: {tool_name}"
            }
    
    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on PDF MCP server.
        
        Returns:
            Dictionary with health status and details
        """
        try:
            storage_dir = Path(self.storage_path)
            
            if not storage_dir.exists():
                return {
                    "status": "unhealthy",
                    "message": f"Storage path does not exist: {self.storage_path}"
                }
            
            return {
                "status": "healthy",
                "message": "PDF MCP server is operational",
                "indexed_documents": len(self.index),
                "storage_path": self.storage_path,
                "last_index_time": self.last_index_time.isoformat() if self.last_index_time else None
            }
            
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return {
                "status": "unhealthy",
                "message": f"Health check failed: {str(e)}"
            }
    
    def close(self) -> None:
        """Close the PDF MCP server and release resources."""
        try:
            # Save index one final time
            self._save_index()
            logger.info("PDF MCP server closed")
        except Exception as e:
            logger.error(f"Error closing PDF MCP server: {str(e)}")
    
    def __enter__(self):
        """Support context manager protocol."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Support context manager protocol."""
        self.close()
