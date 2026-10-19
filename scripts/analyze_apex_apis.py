"""
Analyze Oracle APEX API Reference for relevant APIs
"""

import sys
import os
sys.path.insert(0, 'modules')

from pdf_mcp_server import PDFMCPServer

def analyze_apex_apis():
    """Search PDF for relevant APEX APIs"""
    
    pdf = PDFMCPServer()
    
    # Key APIs for our chatbot integration
    queries = {
        'Session Management': ['APEX_SESSION', 'session state', 'APEX_UTIL session'],
        'REST/Web Services': ['APEX_WEB_SERVICE', 'REST', 'APEX_EXEC'],
        'JSON Handling': ['APEX_JSON', 'JSON parse', 'JSON generate'],
        'Authentication': ['APEX_AUTHENTICATION', 'APEX_CREDENTIAL', 'custom auth'],
        'Database Operations': ['APEX_EXEC', 'OPEN_QUERY_CONTEXT', 'dynamic SQL'],
        'Plugin Development': ['APEX_PLUGIN', 'plugin type', 'render function'],
        'Page Items': ['APEX_UTIL GET_SESSION_STATE', 'SET_SESSION_STATE', 'page item'],
        'Error Handling': ['APEX_ERROR', 'error handling', 'exception'],
    }
    
    print("=" * 80)
    print("ORACLE APEX API ANALYSIS FOR CHATBOT INTEGRATION")
    print("=" * 80)
    
    for category, search_terms in queries.items():
        print(f"\n{'='*80}")
        print(f"CATEGORY: {category}")
        print('='*80)
        
        for term in search_terms:
            results = pdf.search_pdfs(term, limit=3)
            
            if results.get('success') and results.get('results'):
                print(f"\n--- {term} ---")
                for i, r in enumerate(results.get('results', [])[:2], 1):
                    print(f"\n  [{i}] Page {r['page']} (Relevance: {r['relevance_score']:.1f})")
                    excerpt = r['excerpt'].replace('\n', ' ')[:250]
                    print(f"      {excerpt}...")
    
    print("\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)

if __name__ == "__main__":
    analyze_apex_apis()
