# Oracle APEX Integration & Optimization Strategy

## Executive Summary

Based on analysis of the Oracle APEX 24.2 API Reference (1170 pages), this document outlines:
1. **Optimizations** for the current Flask chatbot MCP server
2. **Native APEX deployment** strategy to replace Flask entirely
3. **Hybrid approach** for maximum flexibility

---

## Part 1: Current Flask App Optimizations

### 1.1 Oracle MCP Server Enhancements

#### Use APEX_EXEC Instead of Raw SQL
**Current Issue**: Direct SQL queries are less secure and harder to maintain.

**Recommendation**: Use `APEX_EXEC.OPEN_QUERY_CONTEXT` (Page 472-476)

```python
# ENHANCED: oracle_mcp_server.py
def query_view_enhanced(self, view_name: str, filters: Dict = None):
    """
    Use APEX_EXEC for better query handling
    Reference: APEX API Page 472
    """
    cursor = conn.cursor()
    
    # Use APEX_EXEC for dynamic queries with better security
    plsql = """
    DECLARE
        l_context apex_exec.t_context;
    BEGIN
        l_context := apex_exec.open_query_context(
            p_location => apex_exec.c_location_local_db,
            p_sql_query => :sql_query
        );
        
        -- Return context ID for fetching
        :context_id := l_context.id;
    END;
    """
    
    cursor.execute(plsql, {
        'sql_query': f"SELECT * FROM {view_name}",
        'context_id': cursor.var(int)
    })
```

#### Add Session State Management
**Reference**: APEX_SESSION API (Page 860-862)

```python
# NEW: Add to oracle_mcp_server.py
def create_apex_session(self, username: str, app_id: int = 100):
    """
    Create APEX session for stateful operations
    Reference: APEX_SESSION.CREATE_SESSION (Page 862)
    """
    cursor = conn.cursor()
    cursor.callproc('apex_session.create_session', [
        app_id,      # p_app_id
        1,           # p_page_id
        username     # p_username
    ])
    return cursor.var(int).getvalue()  # Returns session_id
```

#### Implement Proper Error Handling
**Reference**: APEX_ERROR API (Page 368-374)

```python
# NEW: Add to oracle_mcp_server.py
def handle_apex_error(self, error):
    """
    Use APEX error handling patterns
    Reference: APEX_ERROR (Page 370)
    """
    return {
        "success": False,
        "error": {
            "message": str(error),
            "display_location": "inline",  # apex_error.c_inline_with_field
            "page_item_name": None,
            "additional_info": None
        }
    }
```

### 1.2 Add JSON Response Formatting
**Reference**: APEX_JSON API (Page 682, 675-676)

```python
# NEW: modules/apex_json_formatter.py
"""
Format responses using APEX_JSON patterns
Reference: APEX_JSON.WRITE (Page 682)
"""

class ApexJsonFormatter:
    @staticmethod
    def format_query_results(results: List[Dict]) -> str:
        """Format query results in APEX-compatible JSON"""
        output = {
            "success": True,
            "items": results,
            "count": len(results),
            "hasMore": False
        }
        return json.dumps(output)
    
    @staticmethod
    def format_error(error_msg: str) -> str:
        """Format errors in APEX style"""
        return json.dumps({
            "success": False,
            "error": {
                "message": error_msg,
                "code": "APEX_ERROR"
            }
        })
```

### 1.3 Add REST API Endpoints
**Reference**: APEX_WEB_SERVICE (Page 1094-1095)

```python
# ENHANCED: app.py
@app.route('/api/apex/query', methods=['POST'])
def apex_query_endpoint():
    """
    APEX-compatible REST endpoint
    Reference: APEX_WEB_SERVICE patterns (Page 1094)
    """
    data = request.json
    
    # Validate using APEX patterns
    if not data.get('view_name'):
        return ApexJsonFormatter.format_error("view_name required"), 400
    
    # Execute query
    result = oracle_server.query_view(
        view_name=data['view_name'],
        where_clause=data.get('where_clause'),
        limit=data.get('limit', 100)
    )
    
    return ApexJsonFormatter.format_query_results(result['rows'])
```

---

## Part 2: Native APEX Deployment Strategy

### 2.1 Why Deploy in APEX?

**Benefits**:
1. **Native Integration** - Direct database access, no middleware
2. **Security** - Built-in authentication, authorization, session management
3. **Performance** - No network overhead between app and database
4. **Maintenance** - Single platform, unified deployment
5. **APEX Features** - Interactive Grids, Charts, Reports out-of-the-box

### 2.2 Architecture: APEX Native Chatbot

```
┌─────────────────────────────────────────────────────────────┐
│                    APEX Application                          │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Page 1: Chatbot Interface                             │ │
│  │  - Interactive Region (Chat Display)                   │ │
│  │  - Text Input Item (User Message)                      │ │
│  │  - Dynamic Action (Send Message)                       │ │
│  └────────────────────────────────────────────────────────┘ │
│                           ↓                                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  PL/SQL Package: CHATBOT_PKG                           │ │
│  │  - process_message(p_message VARCHAR2)                 │ │
│  │  - query_oracle_views(p_query VARCHAR2)                │ │
│  │  - search_pdf_docs(p_query VARCHAR2)                   │ │
│  │  - call_llm_api(p_prompt VARCHAR2)                     │ │
│  └────────────────────────────────────────────────────────┘ │
│                           ↓                                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  APEX APIs Used:                                        │ │
│  │  - APEX_JSON (Parse/Generate JSON)                     │ │
│  │  - APEX_WEB_SERVICE (Call LLM API)                     │ │
│  │  - APEX_EXEC (Query Views)                             │ │
│  │  - APEX_SESSION (Manage Chat History)                  │ │
│  │  - APEX_COLLECTION (Store Messages)                    │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 Implementation Plan

#### Step 1: Create APEX Application
```sql
-- Create workspace and application
BEGIN
    apex_application_install.set_workspace('CHATBOT_WS');
    apex_application_install.set_application_id(200);
    apex_application_install.set_application_name('AI Chatbot');
    apex_application_install.set_schema('CHATBOT_SCHEMA');
END;
```

#### Step 2: Create PL/SQL Package
**Reference**: APEX_WEB_SERVICE for external API calls (Page 1094)

```sql
CREATE OR REPLACE PACKAGE chatbot_pkg AS
    -- Main chatbot processing
    FUNCTION process_message(
        p_message IN VARCHAR2,
        p_session_id IN NUMBER
    ) RETURN CLOB;
    
    -- Query Oracle views using APEX_EXEC
    FUNCTION query_views(
        p_view_name IN VARCHAR2,
        p_filters IN VARCHAR2 DEFAULT NULL
    ) RETURN CLOB;
    
    -- Search PDF documents (stored as BLOBs)
    FUNCTION search_pdfs(
        p_query IN VARCHAR2
    ) RETURN CLOB;
    
    -- Call external LLM API
    FUNCTION call_llm(
        p_prompt IN CLOB,
        p_context IN CLOB DEFAULT NULL
    ) RETURN CLOB;
END chatbot_pkg;
/

CREATE OR REPLACE PACKAGE BODY chatbot_pkg AS
    
    FUNCTION call_llm(
        p_prompt IN CLOB,
        p_context IN CLOB DEFAULT NULL
    ) RETURN CLOB
    IS
        l_response CLOB;
        l_request_body CLOB;
    BEGIN
        -- Build JSON request using APEX_JSON
        -- Reference: APEX_JSON.WRITE (Page 682)
        apex_json.initialize_clob_output;
        apex_json.open_object;
        apex_json.write('model', 'gpt-4');
        apex_json.open_array('messages');
        
        -- System message
        apex_json.open_object;
        apex_json.write('role', 'system');
        apex_json.write('content', 'You are an Oracle APEX assistant');
        apex_json.close_object;
        
        -- User message
        apex_json.open_object;
        apex_json.write('role', 'user');
        apex_json.write('content', p_prompt);
        apex_json.close_object;
        
        apex_json.close_array;
        apex_json.close_object;
        
        l_request_body := apex_json.get_clob_output;
        apex_json.free_output;
        
        -- Call LLM API using APEX_WEB_SERVICE
        -- Reference: APEX_WEB_SERVICE.MAKE_REST_REQUEST (Page 1113)
        l_response := apex_web_service.make_rest_request(
            p_url => 'https://api.openai.com/v1/chat/completions',
            p_http_method => 'POST',
            p_body => l_request_body
        );
        
        RETURN l_response;
    END call_llm;
    
    FUNCTION query_views(
        p_view_name IN VARCHAR2,
        p_filters IN VARCHAR2 DEFAULT NULL
    ) RETURN CLOB
    IS
        l_context apex_exec.t_context;
        l_result CLOB;
    BEGIN
        -- Use APEX_EXEC for secure queries
        -- Reference: APEX_EXEC.OPEN_QUERY_CONTEXT (Page 472)
        l_context := apex_exec.open_query_context(
            p_location => apex_exec.c_location_local_db,
            p_sql_query => 'SELECT * FROM ' || p_view_name
        );
        
        -- Format results as JSON
        apex_json.initialize_clob_output;
        apex_json.open_array;
        
        WHILE apex_exec.next_row(l_context) LOOP
            apex_json.open_object;
            -- Add columns dynamically
            FOR i IN 1..apex_exec.get_column_count(l_context) LOOP
                apex_json.write(
                    apex_exec.get_column(l_context, i).name,
                    apex_exec.get_varchar2(l_context, i)
                );
            END LOOP;
            apex_json.close_object;
        END LOOP;
        
        apex_json.close_array;
        l_result := apex_json.get_clob_output;
        apex_json.free_output;
        
        apex_exec.close(l_context);
        
        RETURN l_result;
    END query_views;
    
    FUNCTION process_message(
        p_message IN VARCHAR2,
        p_session_id IN NUMBER
    ) RETURN CLOB
    IS
        l_context CLOB;
        l_response CLOB;
    BEGIN
        -- Store message in session using APEX_COLLECTION
        -- Reference: APEX_COLLECTION (Page 215)
        apex_collection.add_member(
            p_collection_name => 'CHAT_HISTORY',
            p_c001 => p_message,
            p_c002 => 'user',
            p_d001 => SYSTIMESTAMP
        );
        
        -- Build context from chat history
        SELECT LISTAGG(c001, CHR(10)) WITHIN GROUP (ORDER BY seq_id)
        INTO l_context
        FROM apex_collections
        WHERE collection_name = 'CHAT_HISTORY';
        
        -- Call LLM with context
        l_response := call_llm(p_message, l_context);
        
        -- Store assistant response
        apex_collection.add_member(
            p_collection_name => 'CHAT_HISTORY',
            p_c001 => l_response,
            p_c002 => 'assistant',
            p_d001 => SYSTIMESTAMP
        );
        
        RETURN l_response;
    END process_message;
    
END chatbot_pkg;
/
```

#### Step 3: Create APEX Page

**Page Items**:
- `P1_MESSAGE` - Text input for user message
- `P1_CHAT_DISPLAY` - Rich Text Display for chat history

**Dynamic Action** (On P1_MESSAGE change):
```javascript
// Reference: APEX JavaScript APIs
apex.server.process(
    'PROCESS_MESSAGE',
    {
        x01: apex.item('P1_MESSAGE').getValue()
    },
    {
        success: function(data) {
            // Update chat display
            $('#P1_CHAT_DISPLAY').append(
                '<div class="user-message">' + data.user_message + '</div>' +
                '<div class="bot-message">' + data.bot_response + '</div>'
            );
            apex.item('P1_MESSAGE').setValue('');
        }
    }
);
```

**Page Process** (PROCESS_MESSAGE):
```sql
DECLARE
    l_response CLOB;
BEGIN
    l_response := chatbot_pkg.process_message(
        p_message => apex_application.g_x01,
        p_session_id => :APP_SESSION
    );
    
    -- Return JSON response
    apex_json.open_object;
    apex_json.write('user_message', apex_application.g_x01);
    apex_json.write('bot_response', l_response);
    apex_json.close_object;
END;
```

### 2.4 PDF Document Integration in APEX

**Store PDFs in Database**:
```sql
CREATE TABLE chatbot_documents (
    doc_id NUMBER PRIMARY KEY,
    filename VARCHAR2(255),
    content BLOB,
    indexed_text CLOB,
    created_date DATE
);

-- Index PDF text for searching
CREATE INDEX idx_doc_text ON chatbot_documents(indexed_text)
INDEXTYPE IS CTXSYS.CONTEXT;
```

**Search Function**:
```sql
FUNCTION search_pdfs(p_query IN VARCHAR2) RETURN CLOB
IS
    l_results CLOB;
BEGIN
    apex_json.initialize_clob_output;
    apex_json.open_array;
    
    FOR rec IN (
        SELECT filename, 
               SCORE(1) as relevance,
               CTX_DOC.SNIPPET('idx_doc_text', rowid, p_query) as excerpt
        FROM chatbot_documents
        WHERE CONTAINS(indexed_text, p_query, 1) > 0
        ORDER BY SCORE(1) DESC
        FETCH FIRST 10 ROWS ONLY
    ) LOOP
        apex_json.open_object;
        apex_json.write('filename', rec.filename);
        apex_json.write('relevance', rec.relevance);
        apex_json.write('excerpt', rec.excerpt);
        apex_json.close_object;
    END LOOP;
    
    apex_json.close_array;
    l_results := apex_json.get_clob_output;
    apex_json.free_output;
    
    RETURN l_results;
END search_pdfs;
```

---

## Part 3: Hybrid Approach (Recommended)

### 3.1 Architecture

Keep Flask for:
- External API gateway
- Non-APEX clients
- Microservices integration

Use APEX for:
- Internal user interface
- Database operations
- Session management
- Reporting and analytics

### 3.2 Integration Points

**Flask → APEX**:
```python
# Flask calls APEX REST endpoints
@app.route('/query', methods=['POST'])
def query_apex():
    response = requests.post(
        'https://apex.company.com/ords/chatbot/api/query',
        json=request.json,
        headers={'Authorization': f'Bearer {apex_token}'}
    )
    return response.json()
```

**APEX → Flask**:
```sql
-- APEX calls Flask MCP servers
DECLARE
    l_response CLOB;
BEGIN
    l_response := apex_web_service.make_rest_request(
        p_url => 'http://flask-server/api/mcp/query',
        p_http_method => 'POST',
        p_body => l_request_json
    );
END;
```

---

## Part 4: Deployment Recommendations

### Option A: Pure APEX (Recommended for Internal Use)
**Pros**: Native, secure, performant, maintainable
**Cons**: Requires APEX infrastructure
**Best For**: Internal enterprise applications

### Option B: Flask + APEX Hybrid
**Pros**: Flexibility, external API support
**Cons**: More complex architecture
**Best For**: Mixed internal/external use cases

### Option C: Keep Flask, Optimize with APEX Patterns
**Pros**: Minimal changes, gradual migration
**Cons**: Doesn't leverage full APEX capabilities
**Best For**: Quick wins, proof of concept

---

## Next Steps

1. **Review** this strategy with your team
2. **Choose** deployment approach (A, B, or C)
3. **Implement** Phase 1 optimizations to current Flask app
4. **Prototype** APEX version (if choosing A or B)
5. **Migrate** gradually with parallel systems

---

## Key APEX APIs to Use

| API | Purpose | Page Reference |
|-----|---------|----------------|
| APEX_JSON | JSON parsing/generation | 682, 675-676 |
| APEX_WEB_SERVICE | External API calls | 1094-1095 |
| APEX_EXEC | Secure database queries | 472-476 |
| APEX_SESSION | Session management | 860-862 |
| APEX_COLLECTION | Chat history storage | 215 |
| APEX_ERROR | Error handling | 368-374 |
| APEX_UTIL | Utility functions | 961, 1068 |
| APEX_CREDENTIAL | API authentication | 251 |

