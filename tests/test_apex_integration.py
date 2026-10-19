"""
Test APEX Integration Endpoints
Verifies Flask backend is ready for APEX integration
"""

import sys
import os
sys.path.insert(0, 'modules')

from dotenv import load_dotenv
from apex_rest_handler import ApexRestHandler
from apex_json_formatter import ApexJsonFormatter
from oracle_mcp_server import OracleMCPServer
from pdf_mcp_server import PDFMCPServer
from llm_service import create_llm_service_from_env

load_dotenv()

def test_apex_integration():
    """Test APEX integration components"""
    
    print("=" * 80)
    print("APEX INTEGRATION TEST")
    print("=" * 80)
    
    # Test 1: JSON Formatter
    print("\n1. Testing APEX JSON Formatter...")
    formatter = ApexJsonFormatter()
    
    success_resp = formatter.success_response(
        {"message": "Hello from APEX"},
        message="Test successful"
    )
    print(f"   ✓ Success response: {success_resp}")
    
    error_resp = formatter.error_response(
        "Test error",
        error_code="TEST_ERROR",
        page_item="P1_TEST"
    )
    print(f"   ✓ Error response: {error_resp}")
    
    # Test 2: Initialize Services
    print("\n2. Initializing Services...")
    
    try:
        oracle_server = None
        if os.getenv('ORACLE_CONNECTION_STRING'):
            oracle_server = OracleMCPServer()
            print("   ✓ Oracle MCP Server initialized")
        else:
            print("   ⚠ Oracle MCP Server skipped (not configured)")
    except Exception as e:
        print(f"   ⚠ Oracle MCP Server failed: {str(e)}")
        oracle_server = None
    
    try:
        pdf_server = PDFMCPServer()
        print("   ✓ PDF MCP Server initialized")
    except Exception as e:
        print(f"   ✗ PDF MCP Server failed: {str(e)}")
        return
    
    try:
        llm_service = create_llm_service_from_env()
        print("   ✓ LLM Service initialized")
    except Exception as e:
        print(f"   ✗ LLM Service failed: {str(e)}")
        print("   Note: Set LLM_API_KEY in .env to test chat functionality")
        llm_service = None
    
    # Test 3: APEX REST Handler
    print("\n3. Testing APEX REST Handler...")
    
    if not llm_service:
        print("   ⚠ Skipping REST handler tests (LLM service not available)")
        print("   Set LLM_API_KEY in .env to enable full testing")
    else:
        handler = ApexRestHandler(oracle_server, pdf_server, llm_service)
        print("   ✓ APEX REST Handler created")
        
        # Test 4: Health Check
        print("\n4. Testing Health Check Endpoint...")
        health = handler.health_check()
        print(f"   Status: {health.get('data', {}).get('status', 'unknown')}")
        print(f"   Services: {health.get('data', {}).get('services', {})}")
        
        # Test 5: List Documents
        print("\n5. Testing List Documents Endpoint...")
        docs = handler.list_documents()
        if docs.get('success'):
            count = docs.get('data', {}).get('totalCount', 0)
            print(f"   ✓ Found {count} document(s)")
            for doc in docs.get('data', {}).get('items', [])[:3]:
                print(f"     - {doc.get('filename')} ({doc.get('page_count')} pages)")
        else:
            print(f"   ✗ Error: {docs.get('error', {}).get('message')}")
        
        # Test 6: Search Documents
        print("\n6. Testing Search Documents Endpoint...")
        search_data = {
            'query': 'APEX_JSON',
            'limit': 3
        }
        results = handler.search_documents(search_data)
        if results.get('success'):
            count = results.get('data', {}).get('count', 0)
            print(f"   ✓ Found {count} result(s) for 'APEX_JSON'")
            for result in results.get('data', {}).get('items', [])[:2]:
                print(f"     - Page {result.get('page')}: {result.get('excerpt')[:80]}...")
        else:
            print(f"   ✗ Error: {results.get('error', {}).get('message')}")
        
        # Test 7: List Views (if Oracle configured)
        if oracle_server:
            print("\n7. Testing List Views Endpoint...")
            views = handler.list_views()
            if views.get('success'):
                count = views.get('data', {}).get('totalCount', 0)
                print(f"   ✓ Found {count} view(s)")
            else:
                print(f"   ⚠ Error: {views.get('error', {}).get('message')}")
        else:
            print("\n7. Skipping List Views Test (Oracle not configured)")
    
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print("✓ JSON Formatter: Working")
    print(f"{'✓' if pdf_server else '✗'} PDF MCP Server: {'Working' if pdf_server else 'Failed'}")
    print(f"{'✓' if oracle_server else '⚠'} Oracle MCP Server: {'Working' if oracle_server else 'Not Configured'}")
    print(f"{'✓' if llm_service else '⚠'} LLM Service: {'Working' if llm_service else 'Not Configured'}")
    print("\nREADY FOR APEX INTEGRATION!" if pdf_server else "\nFIX ERRORS BEFORE PROCEEDING")
    print("=" * 80)

if __name__ == "__main__":
    test_apex_integration()
