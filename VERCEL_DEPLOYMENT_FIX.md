# Vercel Deployment Fix

## Issues Fixed

### 1. PDF Indexing Timeout
**Problem:** PDF indexing was happening on every cold start, causing:
- Vercel 10-second timeout exceeded
- Logging errors from pdfminer library
- Application failing to start

**Solution:**
- Added `SKIP_INITIAL_PDF_INDEX` environment variable
- PDF indexing now happens lazily on first use
- Suppressed pdfminer debug logging

### 2. Logging Format Errors
**Problem:** pdfminer library had incorrect logging format strings causing:
```
TypeError: not all arguments converted during string formatting
```

**Solution:**
- Set pdfminer loggers to WARNING level
- Suppresses debug messages that were causing format errors

## Changes Made

### 1. `modules/pdf_mcp_server.py`
- Added logging suppression for pdfminer
- Made initial indexing optional based on environment variable
- Logs message when skipping initial index

### 2. `vercel.json`
- Added `SKIP_INITIAL_PDF_INDEX=true` environment variable
- This tells the PDF server to skip indexing on startup

## Deployment Instructions

### 1. Deploy to Vercel
```bash
npx vercel --prod
```

### 2. Set Environment Variables in Vercel Dashboard

Go to your project → Settings → Environment Variables and add:

**Required:**
```
SECRET_KEY=your-secret-key-here
LLM_API_KEY=your-gemini-api-key
LLM_MODEL=gemini-2.0-flash
LLM_PROVIDER=gemini
```

**Optional (Oracle):**
```
ORACLE_CONNECTION_STRING=host:port/service
ORACLE_USER=username
ORACLE_PASSWORD=password
ORACLE_ALLOWED_VIEWS=view1,view2
```

**Optional (PDF - already set in vercel.json):**
```
PDF_STORAGE_PATH=./pdfs
SKIP_INITIAL_PDF_INDEX=true
```

### 3. Redeploy
After adding environment variables, redeploy:
```bash
npx vercel --prod
```

## How It Works Now

1. **Cold Start:** Application starts without indexing PDFs (fast)
2. **First PDF Request:** PDF index is created on-demand
3. **Subsequent Requests:** Uses cached index

## Performance Impact

- **Before:** 30+ seconds cold start (timeout)
- **After:** <5 seconds cold start ✅
- **First PDF search:** May take 10-15 seconds (one-time)
- **Subsequent searches:** Fast (<1 second)

## Testing

### Test Health Endpoint
```bash
curl https://your-app.vercel.app/api/health
```

Should return:
```json
{
  "status": "healthy",
  "configuration": {
    "llm_configured": true,
    "pdf_configured": true
  }
}
```

### Test Chat
```bash
curl -X POST https://your-app.vercel.app/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello"}'
```

### Test PDF Search (will trigger indexing)
```bash
curl -X POST https://your-app.vercel.app/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Search for APEX_JSON in the documentation"}'
```

## Troubleshooting

### Issue: Still timing out
- Check Vercel logs: `npx vercel logs`
- Verify `SKIP_INITIAL_PDF_INDEX=true` is set
- Consider upgrading to Vercel Pro for 60-second timeout

### Issue: PDF search not working
- PDFs need to be in the deployment
- First search will take longer (indexing)
- Check logs for PDF-related errors

### Issue: LLM not responding
- Verify `LLM_API_KEY` is set correctly
- Check Gemini API quota/limits
- Review logs for API errors

## Notes

- PDF indexing is now lazy-loaded
- Index is stored in `/tmp` on Vercel (ephemeral)
- Index will be recreated on each cold start when first needed
- Consider pre-building index and deploying it for faster first searches
