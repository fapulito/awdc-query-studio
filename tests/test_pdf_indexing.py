"""
Test script for PDF MCP Server
Tests PDF indexing and search functionality
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add modules directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'modules'))

from pdf_mcp_server import PDFMCPServer

def test_pdf_indexing():
    """Test PDF indexing functionality"""
    print("=" * 60)
    print("PDF MCP Server - Indexing Test")
    print("=" * 60)
    
    # Load environment variables
    load_dotenv()
    
    print("\n1. Initializing PDF MCP Server...")
    try:
        pdf_server = PDFMCPServer()
        print("   ✓ Server initialized successfully")
    except Exception as e:
        print(f"   ✗ Failed to initialize: {str(e)}")
        return
    
    print("\n2. Checking health status...")
    health = pdf_server.health_check()
    print(f"   Status: {health.get('status')}")
    print(f"   Message: {health.get('message')}")
    print(f"   Indexed Documents: {health.get('indexed_documents', 0)}")
    
    print("\n3. Listing available documents...")
    docs = pdf_server.list_documents()
    if docs.get('success'):
        print(f"   Found {docs.get('count', 0)} document(s):")
        for doc in docs.get('documents', []):
            print(f"   - {doc['filename']} ({doc['page_count']} pages)")
    else:
        print(f"   ✗ Error: {docs.get('error')}")
    
    print("\n4. Testing search functionality...")
    test_queries = [
        "APEX_UTIL",
        "session state",
        "authentication"
    ]
    
    for query in test_queries:
        print(f"\n   Searching for: '{query}'")
        results = pdf_server.search_pdfs(query, limit=3)
        
        if results.get('success'):
            count = results.get('count', 0)
            print(f"   Found {count} result(s)")
            
            for i, result in enumerate(results.get('results', [])[:3], 1):
                print(f"\n   Result {i}:")
                print(f"   - File: {result['filename']}")
                print(f"   - Page: {result['page']}")
                print(f"   - Relevance: {result['relevance_score']:.2f}")
                print(f"   - Excerpt: {result['excerpt'][:100]}...")
        else:
            print(f"   ✗ Search failed: {results.get('error')}")
    
    print("\n5. Testing document retrieval...")
    if docs.get('success') and docs.get('documents'):
        first_doc = docs['documents'][0]['filename']
        print(f"   Retrieving: {first_doc}")
        
        doc_content = pdf_server.get_document(first_doc)
        if doc_content.get('success'):
            print(f"   ✓ Retrieved {doc_content.get('page_count')} pages")
            print(f"   First page preview: {doc_content['pages'][0]['text'][:150]}...")
        else:
            print(f"   ✗ Error: {doc_content.get('error')}")
    
    print("\n6. Testing available tools...")
    tools = pdf_server.get_available_tools()
    print(f"   Available tools: {len(tools)}")
    for tool in tools:
        print(f"   - {tool['name']}: {tool['description']}")
    
    print("\n" + "=" * 60)
    print("Test Complete!")
    print("=" * 60)
    
    # Close server
    pdf_server.close()

if __name__ == "__main__":
    test_pdf_indexing()
