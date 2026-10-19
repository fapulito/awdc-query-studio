# Implementation Checklist - Vercel Deployment Optimization

This checklist guides you through implementing the recommended optimizations from the compliance audit.

---

## 🔴 Critical (Do Before Production)

### 1. Update vercel.json Configuration
**Status**: ✅ COMPLETED  
**File**: `vercel.json`

Changes made:
- ✅ Added function memory and timeout configuration
- ✅ Added security headers for API endpoints
- ✅ Added CORS headers for APEX integration
- ✅ Added cache headers for static files
- ✅ Configured region (iad1 - Washington DC)

**Action Required**: 
- Update `regions` array if your Oracle Cloud is in a different region
- Update CORS `Access-Control-Allow-Origin` from `*` to your APEX domain

```json
// In vercel.json, change:
"value": "*"
// To:
"value": "https://your-apex-instance.oraclecloud.com"
```

---

### 2. Upgrade to Vercel Pro Plan
**Status**: ⚠️ PENDING  
**Priority**: HIGH

**Why**: 
- Hobby plan: 10s timeout (insufficient for Oracle Cloud)
- Pro plan: 60s timeout (required for complex queries)

**How to Upgrade**:

```bash
# Option 1: Via CLI
vercel upgrade

# Option 2: Via Dashboard
# 1. Go to https://vercel.com/dashboard
# 2. Select your project
# 3. Settings > General
# 4. Click "Upgrade to Pro"
```

**Cost**: $20/month per member

**After Upgrade**: Update `vercel.json`:

```json
{
  "functions": {
    "app.py": {
      "memory": 3008,
      "maxDuration": 60
    }
  }
}
```

---

### 3. Configure Oracle Cloud Connection String
**Status**: ⚠️ NEEDS UPDATE  
**Priority**: HIGH

**Current Format**:
```
hostname:1521/service_name
```

**Recommended Format** (with retry and timeout):
```
(DESCRIPTION=(RETRY_COUNT=3)(RETRY_DELAY=3)(ADDRESS=(PROTOCOL=TCP)(HOST=hostname.oraclecloud.com)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=service_name)))
```

**Action Required**:

1. Update environment variable in Vercel:
```bash
vercel env rm ORACLE_CONNECTION_STRING production
vercel env add ORACLE_CONNECTION_STRING production
# Paste the new connection string when prompted
```

2. Or via Vercel Dashboard:
   - Settings > Environment Variables
   - Edit `ORACLE_CONNECTION_STRING`
   - Paste new value
   - Save

---

### 4. Whitelist Vercel in Oracle Cloud
**Status**: ⚠️ PENDING  
**Priority**: HIGH

**Action Required**:

1. Go to Oracle Cloud Console
2. Navigate to your Autonomous Database
3. Click "Network" or "Access Control"
4. Choose one:
   - **Option A** (Testing): Allow "Secure access from everywhere"
   - **Option B** (Production): Add specific IP allowlist

**For Production**: Contact Vercel support for current IP ranges or use Oracle Cloud VPN.

---

## 🟡 Important (Do Within First Week)

### 5. Add Rate Limiting
**Status**: ⚠️ NOT IMPLEMENTED  
**Priority**: MEDIUM

**Why**: Prevent abuse and control costs

**Implementation Options**:

**Option A: Vercel Edge Middleware** (Recommended)

Create `middleware.py`:
```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

@app.route('/api/chat', methods=['POST'])
@limiter.limit("10 per minute")
def chat():
    # existing code
    pass
```

**Option B: Use Vercel Pro Rate Limiting**
- Available in Pro plan
- Configure in Vercel Dashboard

---

### 6. Set Up Monitoring
**Status**: ⚠️ NOT CONFIGURED  
**Priority**: MEDIUM

**Action Required**:

1. **Enable Vercel Analytics**:
```bash
# In Vercel Dashboard
# Settings > Analytics > Enable
```

2. **Add Custom Metrics** (already in code):
```python
# Metrics are logged, need to configure collection
# Options:
# - Vercel Log Drains
# - Datadog
# - New Relic
# - Custom logging service
```

3. **Set Up Alerts**:
   - High error rate (> 5%)
   - Slow response time (> 3s)
   - High cold start frequency (> 50%)

---

### 7. Configure Warmup Cron Job
**Status**: ⚠️ NOT CONFIGURED  
**Priority**: MEDIUM

**Why**: Reduce cold starts

**Action Required**:

Use a cron service to ping warmup endpoint every 5 minutes:

**Option A: cron-job.org** (Free)
1. Go to https://cron-job.org
2. Create account
3. Add new cron job:
   - URL: `https://your-app.vercel.app/api/warmup`
   - Schedule: `*/5 * * * *` (every 5 minutes)
   - Method: GET

**Option B: Vercel Cron** (Pro plan)

Create `vercel.json`:
```json
{
  "crons": [
    {
      "path": "/api/warmup",
      "schedule": "*/5 * * * *"
    }
  ]
}
```

**Option C: GitHub Actions**

Create `.github/workflows/warmup.yml`:
```yaml
name: Warmup
on:
  schedule:
    - cron: '*/5 * * * *'
jobs:
  warmup:
    runs-on: ubuntu-latest
    steps:
      - name: Ping warmup endpoint
        run: curl https://your-app.vercel.app/api/warmup
```

---

### 8. Test Oracle Connection
**Status**: ⚠️ NEEDS TESTING  
**Priority**: MEDIUM

**Action Required**:

1. **Local Test**:
```bash
# Set environment variables
export ORACLE_CONNECTION_STRING="your-connection-string"
export ORACLE_USER="your-user"
export ORACLE_PASSWORD="your-password"

# Test connection
python -c "
from modules.oracle_mcp_server import OracleMCPServer
server = OracleMCPServer()
print('✅ Oracle connection successful')
"
```

2. **Vercel Test**:
```bash
# Deploy to preview
vercel

# Test health endpoint
curl https://your-preview.vercel.app/api/health

# Check Oracle status in response
```

3. **Load Test**:
```bash
# Install Apache Bench
# Test with realistic queries
ab -n 100 -c 10 -p query.json -T application/json \
  https://your-app.vercel.app/api/chat
```

---

## 🟢 Optional (Nice to Have)

### 9. Optimize Static Assets
**Status**: ⚠️ NOT OPTIMIZED  
**Priority**: LOW

**Action Required**:

1. **Minify JavaScript**:
```bash
# Install terser
npm install -g terser

# Minify
terser static/app.js -o static/app.min.js -c -m
```

2. **Minify CSS**:
```bash
# Install cssnano
npm install -g cssnano-cli

# Minify
cssnano static/style.css static/style.min.css
```

3. **Update templates** to use minified versions in production

---

### 10. Add Session Storage (Redis/Vercel KV)
**Status**: ⚠️ NOT IMPLEMENTED  
**Priority**: LOW

**Why**: Better session persistence across regions

**Action Required**:

1. **Enable Vercel KV**:
```bash
vercel env add KV_REST_API_URL production
vercel env add KV_REST_API_TOKEN production
```

2. **Update session_manager.py**:
```python
from vercel_kv import kv

class SessionManager:
    def store_session(self, session_id, data):
        kv.set(f"session:{session_id}", data, ex=1800)
    
    def get_session(self, session_id):
        return kv.get(f"session:{session_id}")
```

---

### 11. Document APEX Integration
**Status**: ⚠️ NEEDS DOCUMENTATION  
**Priority**: LOW

**Action Required**:

Create `APEX_INTEGRATION_GUIDE.md` with:
- API endpoint documentation
- JavaScript examples for APEX
- PL/SQL examples
- Authentication setup
- Troubleshooting guide

---

## Deployment Steps

### Initial Deployment

```bash
# 1. Ensure all environment variables are set
vercel env ls

# 2. Deploy to preview
vercel

# 3. Test preview deployment
curl https://your-preview.vercel.app/api/health

# 4. Deploy to production
vercel --prod

# 5. Test production
curl https://your-app.vercel.app/api/health
```

### After Configuration Changes

```bash
# 1. Update vercel.json
# 2. Commit changes
git add vercel.json
git commit -m "Update Vercel configuration"
git push

# 3. Vercel auto-deploys on push (if GitHub integration enabled)
# Or manually deploy:
vercel --prod
```

---

## Verification Checklist

After completing implementation:

- [ ] `vercel.json` updated with optimizations
- [ ] Deployed to Vercel successfully
- [ ] Health endpoint returns 200 OK
- [ ] Oracle connection working (check `/api/health`)
- [ ] CORS headers present (check browser console)
- [ ] Static files cached (check response headers)
- [ ] Security headers present (check response headers)
- [ ] Warmup endpoint working (`/api/warmup`)
- [ ] Chat endpoint working (`/api/chat`)
- [ ] APEX endpoints accessible (`/ords/chatbot/api/*`)
- [ ] Monitoring configured
- [ ] Alerts set up
- [ ] Documentation updated

---

## Testing Commands

```bash
# Health check
curl https://your-app.vercel.app/api/health | jq

# Warmup
curl https://your-app.vercel.app/api/warmup | jq

# Chat test
curl -X POST https://your-app.vercel.app/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, test message"}' | jq

# APEX endpoint test
curl -X POST https://your-app.vercel.app/ords/chatbot/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Test from APEX", "session_id": "test123"}' | jq

# Check headers
curl -I https://your-app.vercel.app/api/health

# Check CORS
curl -H "Origin: https://your-apex.oraclecloud.com" \
     -H "Access-Control-Request-Method: POST" \
     -X OPTIONS \
     https://your-app.vercel.app/ords/chatbot/api/chat -v
```

---

## Rollback Procedure

If deployment has issues:

```bash
# Option 1: Rollback via CLI
vercel rollback

# Option 2: Rollback via Dashboard
# 1. Go to Deployments
# 2. Find previous working deployment
# 3. Click "..." menu
# 4. Select "Promote to Production"
```

---

## Support Resources

- **Vercel Documentation**: https://vercel.com/docs
- **Oracle Cloud Support**: https://support.oracle.com
- **Project Issues**: [Your GitHub repo]/issues
- **Vercel Support**: https://vercel.com/support (Pro plan)

---

## Summary

**Completed**: ✅ vercel.json optimization, documentation  
**Pending**: ⚠️ Vercel Pro upgrade, Oracle Cloud configuration, monitoring setup  
**Optional**: 🟢 Asset optimization, Redis session storage

**Estimated Time to Complete**:
- Critical items: 2-4 hours
- Important items: 4-6 hours
- Optional items: 4-8 hours
- **Total**: 10-18 hours

**Next Steps**:
1. Upgrade to Vercel Pro plan
2. Update Oracle connection string
3. Configure Oracle Cloud network access
4. Deploy and test
5. Set up monitoring and warmup cron
