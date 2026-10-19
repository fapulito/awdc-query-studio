# Hybrid Flask + APEX Chatbot - Deployment Guide

## 🎯 What You Have Now

You've successfully implemented **Option B: Hybrid Architecture** combining:
- **Flask Backend** - Handles AI/ML processing, MCP servers, external APIs
- **APEX Frontend** - Provides enterprise UI, database integration, session management

---

## 📁 Project Structure

```
awdc_chatbot/
├── modules/
│   ├── oracle_mcp_server.py      # Oracle database connector
│   ├── pdf_mcp_server.py          # PDF document search
│   ├── llm_service.py             # LLM integration
│   ├── mcp_client.py              # MCP client orchestration
│   ├── session_manager.py         # Session management
│   ├── apex_json_formatter.py     # ✨ NEW: APEX-compatible JSON
│   └── apex_rest_handler.py       # ✨ NEW: APEX REST endpoints
├── apex/
│   ├── chatbot_pkg.sql            # ✨ NEW: PL/SQL package
│   └── APEX_INSTALLATION_GUIDE.md # ✨ NEW: APEX setup guide
├── pdfs/
│   └── oracle-apex-api-reference.pdf  # 1170-page API reference
├── app.py                         # ✨ ENHANCED: Flask app with APEX routes
├── .env                           # Configuration
├── requirements.txt               # Python dependencies
└── APEX_OPTIMIZATION_STRATEGY.md  # Complete strategy document
```

---

## 🚀 Quick Start

### 1. Start Flask Backend

```bash
# Activate virtual environment
.\venv\Scripts\Activate.ps1  # Windows
# source venv/bin/activate    # Linux/Mac

# Run Flask
python app.py
```

Flask will start on `http://localhost:5000` with these APEX-compatible endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/ords/chatbot/api/chat` | POST | Process chat messages |
| `/ords/chatbot/api/query` | POST | Query Oracle views |
| `/ords/chatbot/api/search` | POST | Search PDF documents |
| `/ords/chatbot/api/views` | GET | List available views |
| `/ords/chatbot/api/documents` | GET | List PDF documents |
| `/ords/chatbot/api/health` | GET | Health check |

### 2. Test Flask Endpoints

```bash
# Test health
curl http://localhost:5000/ords/chatbot/api/health

# Test PDF search
curl -X POST http://localhost:5000/ords/chatbot/api/search \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"APEX_UTIL\", \"limit\": 5}"

# Test chat
curl -X POST http://localhost:5000/ords/chatbot/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"What is APEX_JSON?\", \"session_id\": 12345}"
```

### 3. Deploy APEX Application

Follow the detailed guide in `apex/APEX_INSTALLATION_GUIDE.md`:

1. Configure network ACL
2. Install PL/SQL package (`apex/chatbot_pkg.sql`)
3. Create APEX application
4. Test integration

---

## 🔧 Configuration

### Flask Configuration (.env)

```env
# Flask
FLASK_ENV=development
SECRET_KEY=your-secret-key

# LLM Service (Required)
LLM_API_KEY=your-api-key
LLM_MODEL=gpt-4
LLM_API_BASE_URL=https://api.openai.com/v1

# PDF Connector (Required)
PDF_STORAGE_PATH=./pdfs
PDF_INDEX_FILE=./pdf_index.json

# Oracle Database (Optional)
ORACLE_CONNECTION_STRING=host:1521/service
ORACLE_USER=username
ORACLE_PASSWORD=password
ORACLE_ALLOWED_VIEWS=view1,view2
```

### APEX Configuration

Edit `apex/chatbot_pkg.sql` line 10:
```sql
c_flask_base_url CONSTANT VARCHAR2(200) := 'http://localhost:5000/ords/chatbot/api';
```

---

## 📊 Architecture Benefits

### Why Hybrid?

| Component | Flask | APEX | Winner |
|-----------|-------|------|--------|
| **AI/ML Processing** | ✅ Native Python libraries | ❌ Limited | Flask |
| **External APIs** | ✅ Easy integration | ⚠️ Possible but complex | Flask |
| **Database Queries** | ⚠️ Via network | ✅ Native SQL | APEX |
| **User Interface** | ❌ Manual HTML/CSS | ✅ Drag-and-drop | APEX |
| **Session Management** | ⚠️ Custom code | ✅ Built-in | APEX |
| **Security** | ⚠️ Manual setup | ✅ Enterprise-grade | APEX |
| **Reporting** | ❌ Custom | ✅ Built-in | APEX |

### Data Flow

```
User → APEX UI → PL/SQL Package → Flask REST API → MCP Servers → Data Sources
                      ↓                                ↓
                APEX Collections                  LLM Service
                (Chat History)                    (AI Processing)
```

---

## 🎨 What's New in This Implementation

### 1. APEX-Compatible JSON Formatting
**File**: `modules/apex_json_formatter.py`

Formats all responses following APEX patterns:
```python
# Success response
{
    "success": true,
    "data": {...},
    "message": "Optional message"
}

# Error response
{
    "success": false,
    "error": {
        "message": "Error description",
        "code": "ERROR_CODE",
        "display_location": "inline",
        "page_item_name": "P1_FIELD"
    }
}
```

### 2. APEX REST Handler
**File**: `modules/apex_rest_handler.py`

Provides ORDS-style REST endpoints that APEX can easily consume.

### 3. PL/SQL Integration Package
**File**: `apex/chatbot_pkg.sql`

Complete PL/SQL package with:
- `process_message()` - Chat processing
- `query_oracle_view()` - Database queries
- `search_documents()` - PDF search
- `get_chat_history()` - History management
- Uses `APEX_WEB_SERVICE` for REST calls
- Uses `APEX_JSON` for JSON handling
- Uses `APEX_COLLECTION` for session storage

### 4. Enhanced Flask App
**File**: `app.py`

Now includes:
- APEX REST route registration
- Oracle MCP Server initialization
- PDF MCP Server initialization
- APEX-compatible error handling

---

## 🧪 Testing

### Test Flask Backend

```bash
# Activate venv
.\venv\Scripts\Activate.ps1

# Run tests
python test_pdf_indexing.py

# Test APEX endpoints
python -c "
import requests
response = requests.post(
    'http://localhost:5000/ords/chatbot/api/search',
    json={'query': 'APEX_UTIL', 'limit': 3}
)
print(response.json())
"
```

### Test APEX Integration

```sql
-- Test health check
SELECT chatbot_pkg.health_check FROM dual;

-- Test PDF search
SELECT chatbot_pkg.search_documents('APEX_JSON', 5) FROM dual;

-- Test chat
SELECT chatbot_pkg.process_message('What is APEX_UTIL?', :APP_SESSION) FROM dual;
```

---

## 📈 Next Steps

### Immediate (Development)
- [ ] Configure your LLM API key in `.env`
- [ ] Test Flask endpoints
- [ ] Install APEX package
- [ ] Create APEX page
- [ ] Test end-to-end flow

### Short Term (Enhancement)
- [ ] Add authentication to REST endpoints
- [ ] Implement rate limiting
- [ ] Add request logging
- [ ] Create admin dashboard in APEX
- [ ] Add more Oracle views to query

### Long Term (Production)
- [ ] Deploy Flask to production server
- [ ] Configure HTTPS
- [ ] Set up monitoring
- [ ] Implement caching
- [ ] Add load balancing
- [ ] Create backup strategy

---

## 🔒 Security Checklist

- [ ] Change `SECRET_KEY` in `.env`
- [ ] Use HTTPS for Flask in production
- [ ] Configure APEX ACL properly
- [ ] Add API authentication
- [ ] Implement rate limiting
- [ ] Enable CORS restrictions
- [ ] Sanitize user inputs
- [ ] Log security events
- [ ] Regular security audits

---

## 📚 Documentation

| Document | Purpose |
|----------|---------|
| `APEX_OPTIMIZATION_STRATEGY.md` | Complete strategy with code examples |
| `apex/APEX_INSTALLATION_GUIDE.md` | Step-by-step APEX setup |
| `DEPLOYMENT_README.md` | This file - deployment overview |
| `README.md` | Original project README |

---

## 🆘 Troubleshooting

### Flask won't start
```bash
# Check Python version
python --version  # Should be 3.8+

# Reinstall dependencies
pip install -r requirements.txt

# Check .env file exists
ls .env
```

### APEX can't reach Flask
```sql
-- Test network access
SELECT UTL_HTTP.REQUEST('http://localhost:5000/ords/chatbot/api/health') FROM dual;

-- If error, configure ACL (see APEX_INSTALLATION_GUIDE.md)
```

### PDF indexing fails
```bash
# Check PDF directory
ls pdfs/

# Re-run indexing test
python test_pdf_indexing.py
```

---

## 🎉 Success Criteria

You'll know it's working when:

1. ✅ Flask starts without errors
2. ✅ `/ords/chatbot/api/health` returns healthy status
3. ✅ PDF search finds results from Oracle APEX documentation
4. ✅ APEX package installs without errors
5. ✅ APEX page displays chat interface
6. ✅ Messages sent from APEX get responses
7. ✅ Chat history persists in APEX session

---

## 💡 Tips

1. **Start Simple**: Test Flask endpoints before APEX integration
2. **Use Logs**: Check Flask console and APEX debug for errors
3. **Test Incrementally**: Test each component separately
4. **Keep Documentation**: Update this file as you customize
5. **Version Control**: Commit working configurations

---

## 📞 Support Resources

- **Flask Docs**: https://flask.palletsprojects.com/
- **APEX Docs**: https://docs.oracle.com/en/database/oracle/apex/
- **APEX API Reference**: `pdfs/oracle-apex-api-reference.pdf`
- **Project Issues**: Check Flask logs and APEX debug output

---

**You're ready to deploy! 🚀**

Start with Flask, test the endpoints, then move to APEX integration.
