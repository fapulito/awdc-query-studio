# Vercel Deployment Fix

## Issue
The Vercel deployment is crashing because:
1. Old code is deployed (still has `initialize_services()` call in chat route)
2. PDF indexing on startup causes logging errors and timeouts

## Solution

### Step 1: Redeploy with Latest Code
The latest code has already removed the `initialize_services()` call from the `/api/chat` route. You need to:
1. Commit and push the latest changes
2. Trigger a new Vercel deployment

### Step 2: Add Environment Variable
Add this environment variable in Vercel dashboard:

```
SKIP_INITIAL_PDF_INDEX=true
```

This will prevent PDF indexing on cold starts, eliminating the logging errors and timeout issues.

### Step 3: Verify
After redeployment, the application should:
- Start in ~1 second (no PDF indexing)
- Services initialize once at module load
- No repeated initialization on each request
- No logging errors from pdfminer

## What Was Fixed
1. Removed `initialize_services()` call from `/api/chat` route
2. Services now initialize ONCE via `warmup_services()` at module load
3. Added lazy initialization support for PDF server
4. MCP client no longer attempts server connections at startup (lazy mode)

## Current Code Status
✅ `api/index.py` - No `initialize_services()` in chat route
✅ `app.py` - No `initialize_services()` in chat route  
✅ Services initialize once at startup
✅ PDF indexing can be skipped via environment variable
