--------------------------------------------------------------------------------
-- CHATBOT_PKG - Oracle APEX Chatbot Package
-- Integrates with Flask backend via REST APIs
-- Reference: Oracle APEX API Reference 24.2
--------------------------------------------------------------------------------

CREATE OR REPLACE PACKAGE chatbot_pkg AS
    
    -- Package constants
    c_flask_base_url CONSTANT VARCHAR2(200) := 'http://localhost:5000/ords/chatbot/api';
    c_timeout CONSTANT NUMBER := 30;
    
    -- Main chatbot functions
    FUNCTION process_message(
        p_message IN VARCHAR2,
        p_session_id IN NUMBER DEFAULT NULL
    ) RETURN CLOB;
    
    FUNCTION query_oracle_view(
        p_view_name IN VARCHAR2,
        p_where_clause IN VARCHAR2 DEFAULT NULL,
        p_limit IN NUMBER DEFAULT 100
    ) RETURN CLOB;
    
    FUNCTION search_documents(
        p_query IN VARCHAR2,
        p_limit IN NUMBER DEFAULT 10
    ) RETURN CLOB;
    
    FUNCTION list_available_views
    RETURN CLOB;
    
    FUNCTION list_available_documents
    RETURN CLOB;
    
    -- Session management
    PROCEDURE initialize_chat_session(
        p_session_id IN NUMBER DEFAULT NULL
    );
    
    PROCEDURE add_message_to_history(
        p_message IN VARCHAR2,
        p_role IN VARCHAR2,
        p_session_id IN NUMBER DEFAULT NULL
    );
    
    FUNCTION get_chat_history(
        p_session_id IN NUMBER DEFAULT NULL,
        p_limit IN NUMBER DEFAULT 50
    ) RETURN CLOB;
    
    PROCEDURE clear_chat_history(
        p_session_id IN NUMBER DEFAULT NULL
    );
    
    -- Utility functions
    FUNCTION health_check
    RETURN CLOB;
    
END chatbot_pkg;
/

CREATE OR REPLACE PACKAGE BODY chatbot_pkg AS
    
    --------------------------------------------------------------------------------
    -- Private helper function to call Flask REST API
    --------------------------------------------------------------------------------
    FUNCTION call_flask_api(
        p_endpoint IN VARCHAR2,
        p_method IN VARCHAR2 DEFAULT 'GET',
        p_body IN CLOB DEFAULT NULL
    ) RETURN CLOB
    IS
        l_url VARCHAR2(500);
        l_response CLOB;
    BEGIN
        l_url := c_flask_base_url || p_endpoint;
        
        -- Set HTTP headers
        -- Reference: APEX_WEB_SERVICE (Page 1094)
        apex_web_service.g_request_headers.DELETE;
        apex_web_service.g_request_headers(1).name := 'Content-Type';
        apex_web_service.g_request_headers(1).value := 'application/json';
        
        -- Make REST request
        -- Reference: APEX_WEB_SERVICE.MAKE_REST_REQUEST (Page 1113)
        l_response := apex_web_service.make_rest_request(
            p_url => l_url,
            p_http_method => p_method,
            p_body => p_body
        );
        
        RETURN l_response;
        
    EXCEPTION
        WHEN OTHERS THEN
            -- Return error as JSON
            -- Reference: APEX_JSON (Page 682)
            apex_json.initialize_clob_output;
            apex_json.open_object;
            apex_json.write('success', FALSE);
            apex_json.write('error', SQLERRM);
            apex_json.close_object;
            RETURN apex_json.get_clob_output;
    END call_flask_api;
    
    --------------------------------------------------------------------------------
    -- Process chat message
    --------------------------------------------------------------------------------
    FUNCTION process_message(
        p_message IN VARCHAR2,
        p_session_id IN NUMBER DEFAULT NULL
    ) RETURN CLOB
    IS
        l_request_body CLOB;
        l_response CLOB;
        l_session_id NUMBER;
    BEGIN
        l_session_id := NVL(p_session_id, :APP_SESSION);
        
        -- Build request JSON
        -- Reference: APEX_JSON.WRITE (Page 682)
        apex_json.initialize_clob_output;
        apex_json.open_object;
        apex_json.write('message', p_message);
        apex_json.write('session_id', l_session_id);
        
        -- Add context from APEX collection
        apex_json.open_array('context');
        FOR rec IN (
            SELECT c001 as message, c002 as role
            FROM apex_collections
            WHERE collection_name = 'CHAT_HISTORY'
            ORDER BY seq_id
        ) LOOP
            apex_json.open_object;
            apex_json.write('role', rec.role);
            apex_json.write('content', rec.message);
            apex_json.close_object;
        END LOOP;
        apex_json.close_array;
        
        apex_json.close_object;
        l_request_body := apex_json.get_clob_output;
        apex_json.free_output;
        
        -- Call Flask API
        l_response := call_flask_api(
            p_endpoint => '/chat',
            p_method => 'POST',
            p_body => l_request_body
        );
        
        -- Store messages in collection
        -- Reference: APEX_COLLECTION (Page 215)
        add_message_to_history(p_message, 'user', l_session_id);
        
        -- Parse response and store assistant message
        apex_json.parse(l_response);
        IF apex_json.get_varchar2('success') = 'true' THEN
            add_message_to_history(
                apex_json.get_varchar2('data.assistant_message.message'),
                'assistant',
                l_session_id
            );
        END IF;
        
        RETURN l_response;
        
    END process_message;
    
    --------------------------------------------------------------------------------
    -- Query Oracle view via Flask
    --------------------------------------------------------------------------------
    FUNCTION query_oracle_view(
        p_view_name IN VARCHAR2,
        p_where_clause IN VARCHAR2 DEFAULT NULL,
        p_limit IN NUMBER DEFAULT 100
    ) RETURN CLOB
    IS
        l_request_body CLOB;
    BEGIN
        -- Build request JSON
        apex_json.initialize_clob_output;
        apex_json.open_object;
        apex_json.write('view_name', p_view_name);
        IF p_where_clause IS NOT NULL THEN
            apex_json.write('where_clause', p_where_clause);
        END IF;
        apex_json.write('limit', p_limit);
        apex_json.close_object;
        l_request_body := apex_json.get_clob_output;
        apex_json.free_output;
        
        -- Call Flask API
        RETURN call_flask_api(
            p_endpoint => '/query',
            p_method => 'POST',
            p_body => l_request_body
        );
        
    END query_oracle_view;
    
    --------------------------------------------------------------------------------
    -- Search PDF documents
    --------------------------------------------------------------------------------
    FUNCTION search_documents(
        p_query IN VARCHAR2,
        p_limit IN NUMBER DEFAULT 10
    ) RETURN CLOB
    IS
        l_request_body CLOB;
    BEGIN
        -- Build request JSON
        apex_json.initialize_clob_output;
        apex_json.open_object;
        apex_json.write('query', p_query);
        apex_json.write('limit', p_limit);
        apex_json.close_object;
        l_request_body := apex_json.get_clob_output;
        apex_json.free_output;
        
        -- Call Flask API
        RETURN call_flask_api(
            p_endpoint => '/search',
            p_method => 'POST',
            p_body => l_request_body
        );
        
    END search_documents;
    
    --------------------------------------------------------------------------------
    -- List available views
    --------------------------------------------------------------------------------
    FUNCTION list_available_views
    RETURN CLOB
    IS
    BEGIN
        RETURN call_flask_api(
            p_endpoint => '/views',
            p_method => 'GET'
        );
    END list_available_views;
    
    --------------------------------------------------------------------------------
    -- List available documents
    --------------------------------------------------------------------------------
    FUNCTION list_available_documents
    RETURN CLOB
    IS
    BEGIN
        RETURN call_flask_api(
            p_endpoint => '/documents',
            p_method => 'GET'
        );
    END list_available_documents;
    
    --------------------------------------------------------------------------------
    -- Initialize chat session
    --------------------------------------------------------------------------------
    PROCEDURE initialize_chat_session(
        p_session_id IN NUMBER DEFAULT NULL
    )
    IS
        l_session_id NUMBER;
    BEGIN
        l_session_id := NVL(p_session_id, :APP_SESSION);
        
        -- Create or truncate collection for chat history
        -- Reference: APEX_COLLECTION (Page 215)
        IF apex_collection.collection_exists('CHAT_HISTORY') THEN
            apex_collection.truncate_collection('CHAT_HISTORY');
        ELSE
            apex_collection.create_collection('CHAT_HISTORY');
        END IF;
        
    END initialize_chat_session;
    
    --------------------------------------------------------------------------------
    -- Add message to history
    --------------------------------------------------------------------------------
    PROCEDURE add_message_to_history(
        p_message IN VARCHAR2,
        p_role IN VARCHAR2,
        p_session_id IN NUMBER DEFAULT NULL
    )
    IS
    BEGIN
        -- Ensure collection exists
        IF NOT apex_collection.collection_exists('CHAT_HISTORY') THEN
            apex_collection.create_collection('CHAT_HISTORY');
        END IF;
        
        -- Add message to collection
        -- Reference: APEX_COLLECTION.ADD_MEMBER (Page 215)
        apex_collection.add_member(
            p_collection_name => 'CHAT_HISTORY',
            p_c001 => p_message,
            p_c002 => p_role,
            p_d001 => SYSTIMESTAMP
        );
        
    END add_message_to_history;
    
    --------------------------------------------------------------------------------
    -- Get chat history
    --------------------------------------------------------------------------------
    FUNCTION get_chat_history(
        p_session_id IN NUMBER DEFAULT NULL,
        p_limit IN NUMBER DEFAULT 50
    ) RETURN CLOB
    IS
        l_result CLOB;
    BEGIN
        -- Format chat history as JSON
        apex_json.initialize_clob_output;
        apex_json.open_array;
        
        FOR rec IN (
            SELECT c001 as message, c002 as role, d001 as timestamp
            FROM apex_collections
            WHERE collection_name = 'CHAT_HISTORY'
            ORDER BY seq_id DESC
            FETCH FIRST p_limit ROWS ONLY
        ) LOOP
            apex_json.open_object;
            apex_json.write('message', rec.message);
            apex_json.write('role', rec.role);
            apex_json.write('timestamp', TO_CHAR(rec.timestamp, 'YYYY-MM-DD"T"HH24:MI:SS"Z"'));
            apex_json.close_object;
        END LOOP;
        
        apex_json.close_array;
        l_result := apex_json.get_clob_output;
        apex_json.free_output;
        
        RETURN l_result;
        
    END get_chat_history;
    
    --------------------------------------------------------------------------------
    -- Clear chat history
    --------------------------------------------------------------------------------
    PROCEDURE clear_chat_history(
        p_session_id IN NUMBER DEFAULT NULL
    )
    IS
    BEGIN
        IF apex_collection.collection_exists('CHAT_HISTORY') THEN
            apex_collection.truncate_collection('CHAT_HISTORY');
        END IF;
    END clear_chat_history;
    
    --------------------------------------------------------------------------------
    -- Health check
    --------------------------------------------------------------------------------
    FUNCTION health_check
    RETURN CLOB
    IS
    BEGIN
        RETURN call_flask_api(
            p_endpoint => '/health',
            p_method => 'GET'
        );
    END health_check;
    
END chatbot_pkg;
/

-- Grant execute to APEX workspace schema
GRANT EXECUTE ON chatbot_pkg TO PUBLIC;

-- Create synonym for easier access
CREATE OR REPLACE PUBLIC SYNONYM chatbot_pkg FOR chatbot_pkg;
