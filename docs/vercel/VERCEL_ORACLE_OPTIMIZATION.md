# Vercel + Oracle Cloud Optimization Guide

This guide provides specific optimizations for deploying the Flask chatbot on Vercel with Oracle Cloud/APEX backend.

---

## Table of Contents

1. [Vercel Plan Selection](#vercel-plan-selection)
2. [Region Configuration](#region-configuration)
3. [Oracle Connection Optimization](#oracle-connection-optimization)
4. [APEX Integration Setup](#apex-integration-setup)
5. [Performance Tuning](#performance-tuning)
6. [Troubleshooting](#troubleshooting)

---

## 1. Vercel Plan Selection

### Hobby Plan vs Pro Plan

| Feature | Hobby (Free) | Pro ($20/month) | Recommendation |
|---------|--------------|-----------------|----------------|
| **Execution Timeout** | 10 seconds | 60 seconds | **Pro Required** |
| **Memory** | 1024 MB | 3008 MB | Pro Recommended |
| **Bandwidth** | 100 GB | 1 TB | Hobby OK |
| **Deployments** | Unlimited | Unlimited | Either OK |

### Why Pro Plan is Required for Oracle Cloud

**Oracle Cloud Connection Overhead**:
- Initial connection: 200-500ms
- TLS handshake: 100-200ms
- Authentication: 100-300ms
- Query execution: 100-5000ms (depending on complexity)
- **Total**: Can easily exceed 10 seconds on cold start

**Recommendation**: 
- ✅ **Use Pro Plan for production**
- ⚠️ Hobby plan may work for development/testing with simple queries
- 🔴 Hobby plan will timeout on complex queries or cold starts

### How to Upgrade

```bash
# Via Vercel CLI
vercel upgrade

# Or via Dashboard
# 1. Go to Settings > General
# 2. Click "Upgrade to Pro"
# 3. Add payment method
```

---

## 2. Region Configuration

### Optimal Vercel Regions for Oracle Cloud

Oracle Cloud has data centers in multiple regions. Choose Vercel regions closest to your Oracle Cloud region:

| Oracle Cloud Region | Vercel Region | Region Code | Latency |
|---------------------|---------------|-------------|---------|
| **US East (Ashburn)** | Washington DC | `iad1` | ~5-10ms |
| **US West (Phoenix)** | San Francisco | `sfo1` | ~20-30ms |
| **EU (Frankfurt)** | Frankfurt | `fra1` | ~5-10ms |
| **EU (London)** | London | `lhr1` | ~5-10ms |
| **Asia (Tokyo)** | Tokyo | `hnd1` | ~5-10ms |
| **Asia (Mumbai)** | Mumbai | `bom1` | ~5-10ms |

### Configure Region in vercel.json

The current configuration uses `iad1` (Washington DC):

```json
{
  "regions": ["iad1"]
}
```

**To change region**:
1. Identify your Oracle Cloud region
2. Update `regions` array in `vercel.json`
3. Redeploy: `vercel --prod`

**Example for EU (Frankfurt)**:
```json
{
  "regions": ["fra1"]
}
```

### Multi-Region Deployment

For global applications:

```json
{
  "regions": ["iad1", "fra1", "hnd1"]
}
```

**Note**: Multi-region requires Pro plan and increases costs.

---

## 3. Oracle Connection Optimization

### Connection String Format

**Current Format** (Simple):
```
hostname:1521/service_name
```

**Recommended Format** (Oracle Cloud):
```
(DESCRIPTION=(RETRY_COUNT=3)(RETRY_DELAY=3)(ADDRESS=(PROTOCOL=TCP)(HOST=hostname.oraclecloud.com)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=service_name)))
```

### Environment Variable Configuration

**Optimized Oracle Configuration**:

```bash
# Oracle Connection (use full descriptor)
ORACLE_CONNECTION_STRING=(DESCRIPTION=(RETRY_COUNT=3)(RETRY_DELAY=3)(ADDRESS=(PROTOCOL=TCP)(HOST=your-db.oraclecloud.com)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=your_service)))

# Oracle Credentials
ORACLE_USER=your_username
ORACLE_PASSWORD=your_password

# Connection Pool Settings (optimized for serverless)
ORACLE_POOL_MIN=1
ORACLE_POOL_MAX=5
ORACLE_POOL_INCREMENT=1

# Timeout Settings (aggressive for serverless)
QUERY_TIMEOUT=5
CONNECTION_TIMEOUT=3
ORACLE_CONNECT_TIMEOUT=3

# Result Limits (prevent memory issues)
MAX_RESULT_SIZE=1000
```

### Oracle Cloud Network Configuration

**1. Whitelist Vercel IP Ranges**

Vercel uses dynamic IPs, but you can whitelist common ranges:

```sql
-- In Oracle Cloud Network ACL
-- Allow Vercel's IP ranges (check Vercel docs for current ranges)
-- Or use 0.0.0.0/0 for testing (not recommended for production)
```

**2. Enable Public Endpoint**

In Oracle Cloud Console:
1. Go to Autonomous Database
2. Network Access → Edit
3. Select "Secure access from everywhere"
4. Or configure specific IP allowlist

**3. Use Mutual TLS (mTLS) - Optional**

For enhanced security:
1. Download Oracle Cloud wallet
2. Store wallet files in Vercel environment
3. Configure `oracledb` to use wallet

```python
# In oracle_mcp_server.py
import oracledb
oracledb.init_oracle_client(config_dir="/tmp/wallet")
```

### Connection Pooling Optimization

**Current Implementation**: ✅ Already optimized with caching

**Additional Optimization**:

```python
# In modules/oracle_mcp_server.py
def _initialize_connection_pool(self):
    """Optimized for Vercel serverless"""
    pool = oracledb.create_pool(
        user=self.username,
        password=self.password,
        dsn=self.connection_string,
        min=1,  # Minimum for serverless
        max=5,  # Maximum for serverless
        increment=1,
        threaded=True,
        getmode=oracledb.POOL_GETMODE_WAIT,
        wait_timeout=3000,  # 3 seconds
        timeout=300,  # 5 minutes (matches cache TTL)
        ping_interval=60  # Ping every 60 seconds
    )
    return pool
```

---

## 4. APEX Integration Setup

### CORS Configuration

**Already Configured** in `vercel.json`:

```json
{
  "source": "/ords/chatbot/api/(.*)",
  "headers": [
    {
      "key": "Access-Control-Allow-Origin",
      "value": "*"
    }
  ]
}
```

**For Production** (restrict to APEX domain):

```json
{
  "key": "Access-Control-Allow-Origin",
  "value": "https://your-apex-instance.oraclecloud.com"
}
```

### APEX REST API Endpoints

**Available Endpoints**:

```
POST /ords/chatbot/api/chat
  - Send message from APEX
  - Returns AI response

GET /ords/chatbot/api/session/{session_id}
  - Get conversation history
  - Returns message array

POST /ords/chatbot/api/session/{session_id}/clear
  - Clear conversation history
  - Returns success status
```

### APEX Integration Code

**JavaScript in APEX Page**:

```javascript
// Send message to Vercel chatbot
async function sendMessage(message) {
  const response = await fetch('https://your-app.vercel.app/ords/chatbot/api/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message: message,
      session_id: apex.item('P1_SESSION_ID').getValue()
    })
  });
  
  const data = await response.json();
  return data.response;
}
```

**PL/SQL in APEX**:

```sql
DECLARE
  l_response CLOB;
  l_request CLOB;
BEGIN
  -- Build request
  l_request := JSON_OBJECT(
    'message' VALUE :P1_MESSAGE,
    'session_id' VALUE :P1_SESSION_ID
  );
  
  -- Call Vercel API
  l_response := APEX_WEB_SERVICE.MAKE_REST_REQUEST(
    p_url => 'https://your-app.vercel.app/ords/chatbot/api/chat',
    p_http_method => 'POST',
    p_body => l_request
  );
  
  -- Parse response
  :P1_RESPONSE := JSON_VALUE(l_response, '$.response');
END;
```

### APEX Authentication

**Option 1: API Key** (Recommended):

```python
# In app.py - add API key validation
@app.before_request
def validate_apex_request():
    if request.path.startswith('/ords/chatbot/api'):
        api_key = request.headers.get('X-API-Key')
        if api_key != os.getenv('APEX_API_KEY'):
            return jsonify({'error': 'Unauthorized'}), 401
```

**Option 2: APEX Session Token**:

```python
# Validate APEX session token
def validate_apex_session(session_token):
    # Query Oracle to validate session
    # Return True if valid
    pass
```

---

## 5. Performance Tuning

### Query Optimization

**1. Use Indexed Views**

```sql
-- In Oracle, create indexed views for common queries
CREATE MATERIALIZED VIEW mv_customer_summary
BUILD IMMEDIATE
REFRESH FAST ON COMMIT
AS
SELECT customer_id, name, total_orders, last_order_date
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
GROUP BY customer_id, name;

-- Create index
CREATE INDEX idx_mv_customer ON mv_customer_summary(customer_id);
```

**2. Limit Result Sets**

```python
# Already implemented in oracle_mcp_server.py
MAX_RESULT_SIZE=1000  # Limit rows returned
```

**3. Use Pagination**

```python
# Add pagination to queries
def query_with_pagination(query, page=1, page_size=100):
    offset = (page - 1) * page_size
    paginated_query = f"""
        SELECT * FROM (
            SELECT a.*, ROWNUM rnum FROM ({query}) a
            WHERE ROWNUM <= {offset + page_size}
        )
        WHERE rnum > {offset}
    """
    return paginated_query
```

### Caching Strategy

**1. Query Result Caching**

```python
# Add to oracle_mcp_server.py
from functools import lru_cache
from hashlib import md5

@lru_cache(maxsize=100)
def cached_query(query_hash, query):
    """Cache query results for 5 minutes"""
    return execute_query(query)

def query_view(self, view_name, filters=None):
    query = self._build_query(view_name, filters)
    query_hash = md5(query.encode()).hexdigest()
    return cached_query(query_hash, query)
```

**2. Connection Caching**

✅ Already implemented via `serverless_optimizer.py`

**3. Session Caching**

Consider using Vercel KV for session storage:

```bash
# Install Vercel KV
npm install @vercel/kv
```

```python
# Use Redis for sessions instead of filesystem
from vercel_kv import kv

def store_session(session_id, data):
    kv.set(f"session:{session_id}", data, ex=1800)
```

### Monitoring Performance

**Add Custom Metrics**:

```python
# In app.py
@app.after_request
def log_performance(response):
    if hasattr(g, 'oracle_query_time'):
        logger.info(
            f"Oracle query time: {g.oracle_query_time:.2f}ms",
            extra={
                'metric': 'oracle_query_duration',
                'value': g.oracle_query_time,
                'query': g.oracle_query
            }
        )
    return response
```

---

## 6. Troubleshooting

### Issue: Connection Timeout

**Symptoms**:
```
Error: Connection timeout after 10 seconds
```

**Solutions**:
1. ✅ Upgrade to Vercel Pro (60s timeout)
2. ✅ Optimize Oracle connection string with retry parameters
3. ✅ Check Oracle Cloud network ACLs
4. ✅ Verify Vercel region is close to Oracle Cloud region

**Debug**:
```bash
# Test connection locally
python -c "
import oracledb
conn = oracledb.connect(
    user='user',
    password='pass',
    dsn='connection_string'
)
print('Connected successfully')
"
```

### Issue: "No connections available"

**Symptoms**:
```
Error: Pool exhausted, no connections available
```

**Solutions**:
1. Increase `ORACLE_POOL_MAX` (default: 5)
2. Decrease `QUERY_TIMEOUT` to free connections faster
3. Check for connection leaks (ensure connections are closed)

**Debug**:
```python
# Add to oracle_mcp_server.py
def get_pool_status(self):
    return {
        'open': self.pool.opened,
        'busy': self.pool.busy,
        'max': self.pool.max
    }
```

### Issue: Slow Queries

**Symptoms**:
```
Query takes > 5 seconds
```

**Solutions**:
1. Add indexes to Oracle views
2. Use materialized views
3. Limit result set size
4. Implement pagination
5. Cache frequent queries

**Debug**:
```sql
-- In Oracle, check query execution plan
EXPLAIN PLAN FOR
SELECT * FROM your_view WHERE condition;

SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY);
```

### Issue: CORS Errors from APEX

**Symptoms**:
```
Access to fetch blocked by CORS policy
```

**Solutions**:
1. ✅ Verify CORS headers in `vercel.json`
2. Check APEX domain is allowed
3. Ensure preflight OPTIONS requests are handled

**Debug**:
```bash
# Test CORS from command line
curl -H "Origin: https://your-apex.oraclecloud.com" \
     -H "Access-Control-Request-Method: POST" \
     -H "Access-Control-Request-Headers: Content-Type" \
     -X OPTIONS \
     https://your-app.vercel.app/ords/chatbot/api/chat
```

### Issue: High Cold Start Latency

**Symptoms**:
```
First request takes 8-12 seconds
```

**Solutions**:
1. ✅ Use warmup endpoint (already implemented)
2. Set up cron job to ping every 5 minutes
3. Optimize imports (lazy loading already implemented)
4. Reduce dependency size

**Warmup Cron**:
```bash
# Using cron-job.org or similar service
*/5 * * * * curl https://your-app.vercel.app/api/warmup
```

---

## Performance Benchmarks

### Expected Latency (Vercel Pro + Oracle Cloud)

| Operation | Cold Start | Warm | With Warmup |
|-----------|------------|------|-------------|
| Health Check | 2-3s | 50-100ms | 30-50ms |
| Simple Query | 3-5s | 500-800ms | 300-500ms |
| Complex Query | 5-8s | 1-2s | 800ms-1.5s |
| PDF Search | 4-6s | 800ms-1.2s | 500-800ms |
| Chat (no tools) | 3-4s | 600-900ms | 400-600ms |
| Chat (with tools) | 5-8s | 1.5-2.5s | 1-2s |

### Optimization Targets

- ✅ Cold start < 5s (Pro plan)
- ✅ Warm requests < 1s (simple queries)
- ✅ Oracle connection < 500ms
- ✅ Query execution < 2s
- ✅ Total response < 3s (90th percentile)

---

## Checklist for Production

- [ ] Upgrade to Vercel Pro plan
- [ ] Configure optimal region (close to Oracle Cloud)
- [ ] Update Oracle connection string with retry parameters
- [ ] Whitelist Vercel IPs in Oracle Cloud
- [ ] Configure CORS for APEX domain
- [ ] Set up warmup cron job
- [ ] Add monitoring and alerts
- [ ] Test with realistic load
- [ ] Document APEX integration
- [ ] Train users on chatbot usage

---

## Additional Resources

- [Vercel Regions](https://vercel.com/docs/edge-network/regions)
- [Oracle Cloud Regions](https://www.oracle.com/cloud/data-regions/)
- [Oracle python-oracledb](https://python-oracledb.readthedocs.io/)
- [APEX REST APIs](https://docs.oracle.com/en/database/oracle/apex/23.1/htmdb/managing-REST-data-sources.html)
