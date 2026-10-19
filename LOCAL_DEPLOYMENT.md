# Local Deployment Guide

## Quick Start - Deploy Locally with Vercel

### Option 1: Vercel Dev (Recommended for testing Vercel deployment)

1. **Install Vercel CLI** (if not already installed):
   ```bash
   npm install -g vercel
   ```

2. **Login to Vercel**:
   ```bash
   vercel login
   ```

3. **Run locally with Vercel dev server**:
   ```bash
   vercel dev
   ```
   
   This will:
   - Start local server at `http://localhost:3000`
   - Simulate Vercel's serverless environment
   - Hot-reload on file changes
   - Use your `.env` file for environment variables

4. **Test the application**:
   - Open browser: `http://localhost:3000`
   - Health check: `http://localhost:3000/api/health`
   - Chat interface: `http://localhost:3000/`

### Option 2: Run Flask Directly (Simpler, faster for development)

1. **Ensure dependencies are installed**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Make sure `.env` file is configured**:
   ```bash
   # Copy from example if needed
   cp .env.example .env
   
   # Edit .env and add your API keys
   ```

3. **Run Flask app**:
   ```bash
   python app.py
   ```
   
   This will:
   - Start local server at `http://localhost:5000`
   - Run in development mode with hot-reload
   - Use your `.env` file for environment variables

4. **Test the application**:
   - Open browser: `http://localhost:5000`
   - Health check: `http://localhost:5000/api/health`
   - Chat interface: `http://localhost:5000/`

## Required Environment Variables

Make sure your `.env` file has these minimum variables:

```bash
# Required
SECRET_KEY=your-secret-key-here
LLM_API_KEY=your-openai-api-key
LLM_MODEL=gpt-4

# Optional - Oracle Database
ORACLE_CONNECTION_STRING=localhost:1521/XEPDB1
ORACLE_USER=your_username
ORACLE_PASSWORD=your_password
ORACLE_ALLOWED_VIEWS=view1,view2

# Optional - PDF Processing
PDF_STORAGE_PATH=./pdfs
PDF_INDEX_FILE=./pdf_index.json
```

## Troubleshooting

### Issue: "Module not found" errors

**Solution**: Install dependencies
```bash
pip install -r requirements.txt
```

### Issue: "Missing required environment variables"

**Solution**: Check your `.env` file
```bash
# Verify .env exists
ls -la .env

# Check contents (be careful not to expose secrets)
cat .env | grep -v "KEY\|PASSWORD"
```

### Issue: Vercel dev fails with "404 NOT_FOUND"

**Solution**: This is the issue you're experiencing. The `vercel.json` has been updated with proper rewrites. Try again:
```bash
vercel dev
```

### Issue: Port already in use

**Solution**: Kill the process or use a different port
```bash
# For Flask (port 5000)
lsof -ti:5000 | xargs kill -9

# For Vercel dev (port 3000)
lsof -ti:3000 | xargs kill -9

# Or specify a different port
PORT=8000 python app.py
```

### Issue: OpenAI API errors

**Solution**: Verify your API key
```bash
# Test API key
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer YOUR_API_KEY"
```

## Testing Endpoints

### Health Check
```bash
curl http://localhost:5000/api/health
```

### Chat Message
```bash
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, how are you?"}'
```

### Session History
```bash
curl http://localhost:5000/api/session/history
```

### Warmup (for Vercel optimization)
```bash
curl http://localhost:5000/api/warmup
```

## Next Steps

Once local testing works:

1. **Deploy to Vercel**:
   ```bash
   vercel --prod
   ```

2. **Set environment variables in Vercel**:
   ```bash
   vercel env add SECRET_KEY production
   vercel env add LLM_API_KEY production
   # ... add other variables
   ```

3. **Monitor deployment**:
   ```bash
   vercel logs
   ```

## Common Commands

```bash
# Start Vercel dev server
vercel dev

# Deploy to preview
vercel

# Deploy to production
vercel --prod

# View logs
vercel logs

# List environment variables
vercel env ls

# Pull environment variables locally
vercel env pull
```

## Performance Tips

1. **Use warmup endpoint**: Reduces cold start time
2. **Monitor logs**: `vercel logs` or check Vercel dashboard
3. **Test locally first**: Always test with `vercel dev` before deploying
4. **Check health endpoint**: Verify all services are initialized

## Support

- Vercel Docs: https://vercel.com/docs
- Vercel CLI Docs: https://vercel.com/docs/cli
- Project README: See `README.md` for more details
