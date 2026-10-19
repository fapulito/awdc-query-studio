# Oracle APEX Chatbot - Installation Guide

## Overview

This guide walks you through deploying the hybrid Flask + APEX chatbot solution.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    APEX Application                          │
│                    (User Interface)                          │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Page 1: Chatbot Interface                             │ │
│  │  - Chat Display Region                                 │ │
│  │  - Message Input                                       │ │
│  │  - Send Button                                         │ │
│  └────────────────────────────────────────────────────────┘ │
│                           ↓                                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  PL/SQL Package: CHATBOT_PKG                           │ │
│  │  - Calls Flask REST APIs                               │ │
│  │  - Manages APEX Collections                            │ │
│  │  - Formats JSON responses                              │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────────┬───────────────────────────────────┘
                           │ REST API Calls
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                    Flask Backend                             │
│                    (Business Logic)                          │
│                                                              │
│  /ords/chatbot/api/chat       - Process messages            │
│  /ords/chatbot/api/query      - Query Oracle views          │
│  /ords/chatbot/api/search     - Search PDF documents        │
│  /ords/chatbot/api/views      - List available views        │
│  /ords/chatbot/api/documents  - List documents              │
│  /ords/chatbot/api/health     - Health check                │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ Oracle MCP   │  │  PDF MCP     │  │  LLM Service │     │
│  │  Server      │  │  Server      │  │              │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

### 1. Flask Backend
- Python 3.8+
- Virtual environment set up
- All dependencies installed (`pip install -r requirements.txt`)
- `.env` file configured with:
  - `LLM_API_KEY`
  - `PDF_STORAGE_PATH`
  - `ORACLE_CONNECTION_STRING` (optional)

### 2. Oracle APEX
- APEX 20.1 or higher (24.2 recommended)
- Workspace created
- Schema with execute privileges
- Network access to Flask backend

### 3. Network Configuration
- Flask backend accessible from APEX server
- APEX ACL configured for outbound HTTP/HTTPS

---

## Installation Steps

### Step 1: Deploy Flask Backend

1. **Start Flask application**:
   ```bash
   # Activate virtual environment
   .\venv\Scripts\Activate.ps1  # Windows
   source venv/bin/activate      # Linux/Mac
   
   # Run Flask
   python app.py
   ```

2. **Verify Flask is running**:
   ```bash
   curl http://localhost:5000/ords/chatbot/api/health
   ```

3. **Test APEX endpoints**:
   ```bash
   # Test chat endpoint
   curl -X POST http://localhost:5000/ords/chatbot/api/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "Hello", "session_id": 12345}'
   
   # Test search endpoint
   curl -X POST http://localhost:5000/ords/chatbot/api/search \
     -H "Content-Type: application/json" \
     -d '{"query": "APEX_UTIL", "limit": 5}'
   ```

### Step 2: Configure APEX Network Access

1. **Login to APEX as Workspace Administrator**

2. **Configure ACL for outbound requests**:
   ```sql
   -- Run as APEX schema owner or DBA
   BEGIN
       DBMS_NETWORK_ACL_ADMIN.APPEND_HOST_ACE(
           host => 'localhost',  -- Change to your Flask server hostname
           ace  => xs$ace_type(
               privilege_list => xs$name_list('http', 'connect', 'resolve'),
               principal_name => 'YOUR_WORKSPACE_SCHEMA',
               principal_type => xs_acl.ptype_db
           )
       );
   END;
   /
   
   -- For production, use actual hostname
   BEGIN
       DBMS_NETWORK_ACL_ADMIN.APPEND_HOST_ACE(
           host => 'your-flask-server.com',
           ace  => xs$ace_type(
               privilege_list => xs$name_list('http', 'https', 'connect', 'resolve'),
               principal_name => 'YOUR_WORKSPACE_SCHEMA',
               principal_type => xs_acl.ptype_db
           )
       );
   END;
   /
   ```

### Step 3: Install PL/SQL Package

1. **Connect to your APEX workspace schema**:
   ```sql
   -- Using SQL Workshop or SQL*Plus
   @apex/chatbot_pkg.sql
   ```

2. **Update Flask URL in package** (if not localhost):
   ```sql
   -- Edit chatbot_pkg.sql line 10
   c_flask_base_url CONSTANT VARCHAR2(200) := 'http://your-server:5000/ords/chatbot/api';
   ```

3. **Test package**:
   ```sql
   -- Test health check
   SELECT chatbot_pkg.health_check FROM dual;
   
   -- Test search
   SELECT chatbot_pkg.search_documents('APEX_UTIL', 5) FROM dual;
   ```

### Step 4: Create APEX Application

#### Option A: Manual Creation

1. **Create New Application**:
   - Application Name: `AI Chatbot`
   - Application ID: `200` (or auto-assign)
   - Theme: Universal Theme (42)

2. **Create Page 1 - Chatbot Interface**:

   **Page Items**:
   - `P1_MESSAGE` (Text Field)
     - Label: Your Message
     - Placeholder: Type your message here...
   
   - `P1_CHAT_DISPLAY` (Rich Text Display)
     - Label: Chat History
     - Settings → Escape special characters: No
   
   - `P1_RESPONSE` (Hidden)
     - Used to store API response

   **Buttons**:
   - `SEND_MESSAGE` (Button)
     - Label: Send
     - Action: Defined by Dynamic Action
   
   - `CLEAR_HISTORY` (Button)
     - Label: Clear Chat
     - Action: Defined by Dynamic Action

   **Dynamic Actions**:

   **DA 1: Send Message**
   - Event: Click
   - Selection Type: Button
   - Button: SEND_MESSAGE
   
   - Action 1: Execute PL/SQL Code
     ```sql
     DECLARE
         l_response CLOB;
     BEGIN
         l_response := chatbot_pkg.process_message(
             p_message => :P1_MESSAGE,
             p_session_id => :APP_SESSION
         );
         :P1_RESPONSE := l_response;
     END;
     ```
     - Items to Submit: P1_MESSAGE
     - Items to Return: P1_RESPONSE
   
   - Action 2: Execute JavaScript Code
     ```javascript
     // Parse response
     var response = JSON.parse(apex.item('P1_RESPONSE').getValue());
     
     if (response.success) {
         var data = response.data;
         var userMsg = data.user_message.message;
         var botMsg = data.assistant_message.message;
         
         // Append to chat display
         var chatHtml = $('#P1_CHAT_DISPLAY').html();
         chatHtml += '<div class="chat-message user">' +
                     '<strong>You:</strong> ' + apex.util.escapeHTML(userMsg) +
                     '</div>';
         chatHtml += '<div class="chat-message assistant">' +
                     '<strong>Assistant:</strong> ' + apex.util.escapeHTML(botMsg) +
                     '</div>';
         $('#P1_CHAT_DISPLAY').html(chatHtml);
         
         // Clear input
         apex.item('P1_MESSAGE').setValue('');
         
         // Scroll to bottom
         $('#P1_CHAT_DISPLAY').scrollTop($('#P1_CHAT_DISPLAY')[0].scrollHeight);
     } else {
         apex.message.showErrors([{
             type: 'error',
             location: 'page',
             message: response.error.message
         }]);
     }
     ```

   **DA 2: Clear Chat**
   - Event: Click
   - Selection Type: Button
   - Button: CLEAR_HISTORY
   
   - Action 1: Execute PL/SQL Code
     ```sql
     BEGIN
         chatbot_pkg.clear_chat_history(:APP_SESSION);
     END;
     ```
   
   - Action 2: Execute JavaScript Code
     ```javascript
     $('#P1_CHAT_DISPLAY').html('');
     apex.item('P1_MESSAGE').setValue('');
     apex.message.showPageSuccess('Chat history cleared');
     ```

3. **Add CSS** (Page → CSS → Inline):
   ```css
   .chat-message {
       padding: 10px;
       margin: 10px 0;
       border-radius: 8px;
   }
   
   .chat-message.user {
       background-color: #e3f2fd;
       margin-left: 20%;
   }
   
   .chat-message.assistant {
       background-color: #f5f5f5;
       margin-right: 20%;
   }
   
   #P1_CHAT_DISPLAY {
       height: 500px;
       overflow-y: auto;
       border: 1px solid #ddd;
       padding: 15px;
       background-color: white;
   }
   
   #P1_MESSAGE {
       width: 100%;
   }
   ```

#### Option B: Import Application (Coming Soon)
- Application export file will be provided
- Import via App Builder → Import

### Step 5: Test Integration

1. **Run APEX Application**
2. **Send test message**: "Hello, can you help me?"
3. **Verify response** appears in chat display
4. **Test search**: "What is APEX_UTIL?"
5. **Test clear**: Click "Clear Chat" button

---

## Configuration

### Update Flask URL

Edit `chatbot_pkg.sql` line 10:
```sql
c_flask_base_url CONSTANT VARCHAR2(200) := 'http://your-server:5000/ords/chatbot/api';
```

### Configure LLM Provider

Update Flask `.env` file:
```env
LLM_API_KEY=your-api-key
LLM_MODEL=gpt-4
LLM_API_BASE_URL=https://api.openai.com/v1
```

### Add Oracle Database Views

Update Flask `.env` file:
```env
ORACLE_CONNECTION_STRING=host:1521/service
ORACLE_USER=username
ORACLE_PASSWORD=password
ORACLE_ALLOWED_VIEWS=view1,view2,view3
```

---

## Troubleshooting

### Issue: "ORA-24247: network access denied by access control list (ACL)"

**Solution**: Configure ACL (see Step 2)

### Issue: "Connection refused" when calling Flask

**Solution**: 
1. Verify Flask is running: `curl http://localhost:5000/ords/chatbot/api/health`
2. Check firewall settings
3. Verify hostname/port in `chatbot_pkg.sql`

### Issue: "JSON parsing error"

**Solution**:
1. Check Flask logs for errors
2. Verify response format matches APEX expectations
3. Test endpoint directly with curl

### Issue: Chat messages not displaying

**Solution**:
1. Check browser console for JavaScript errors
2. Verify P1_RESPONSE item is populated
3. Check Dynamic Action execution order

---

## Production Deployment

### Security Considerations

1. **Use HTTPS** for Flask backend
2. **Add authentication** to REST endpoints
3. **Configure CORS** properly
4. **Use environment variables** for sensitive data
5. **Enable APEX session timeout**
6. **Implement rate limiting**

### Performance Optimization

1. **Enable Flask caching**
2. **Use connection pooling** for Oracle
3. **Implement PDF index caching**
4. **Configure APEX region caching**
5. **Use CDN** for static assets

### Monitoring

1. **Flask logs**: Monitor application logs
2. **APEX Debug**: Enable debug mode during testing
3. **Database monitoring**: Track PL/SQL execution
4. **API metrics**: Monitor response times

---

## Next Steps

1. ✅ Deploy Flask backend
2. ✅ Install PL/SQL package
3. ✅ Create APEX application
4. ✅ Test integration
5. 🔄 Customize UI/UX
6. 🔄 Add authentication
7. 🔄 Deploy to production

---

## Support

For issues or questions:
1. Check Flask logs: `tail -f flask.log`
2. Check APEX debug output
3. Review this guide
4. Test endpoints individually

