# Vercel Deployment Quick Start

This is a quick reference guide for deploying the Flask Chatbot MCP application to Vercel.

## Prerequisites

- Vercel account
- Git repository with your code
- Required API keys and credentials

## Quick Deploy Steps

### 1. Prepare Environment Variables

Copy these required variables (get values from your services):

```bash
# Critical - Application won't start without these
SECRET_KEY=your-secret-key-here
LLM_API_KEY=your-llm-api-key
LLM_MODEL=gpt-4

# Optional - Oracle Database
ORACLE_CONNECTION_STRING=host:port/service
ORACLE_USER=username
ORACLE_PASSWORD=password
ORACLE_ALLOWED_VIEWS=view1,view2

# Optional - PDF Processing
PDF_STORAGE_PATH=./pdfs
PDF_INDEX_FILE=./pdf_index.json
```

### 2. Deploy via Vercel Dashboard

1. Go to https://vercel.com/new
2. Import your Git repository
3. Vercel auto-detects the Flask app
4. Add environment variables in the deployment settings
5. Click **Deploy**

### 3. Deploy via CLI

```bash
# Install Vercel CLI
npm install -g vercel

# Login
vercel login

# Deploy
vercel

# Deploy to production
vercel --prod
```

### 4. Verify Deployment

```bash
# Check health
curl https://your-app.vercel.app/api/health

# Warmup connections
curl https://your-app.vercel.app/api/warmup

# Test chat
curl -X POST https://your-app.vercel.app/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, how are you?"}'
```

## Environment Variables Setup

### Via Vercel Dashboard

1. Go to your project
2. Settings → Environment Variables
3. Add each variable:
   - Name: `SECRET_KEY`
   - Value: `your-secret-key`
   - Environment: Production, Preview, Development
4. Click **Save**

### Via CLI

```bash
vercel env add SECRET_KEY production
# Enter value when prompted

vercel env add LLM_API_KEY production
# Enter value when prompted
```

## Common Issues

### Issue: "Missing required environment variables"

**Solution**: Ensure `SECRET_KEY`, `LLM_API_KEY`, and `LLM_MODEL` are set

```bash
vercel env ls
# Verify all required variables are present
```

### Issue: Cold start timeout

**Solution**: Use warmup endpoint

```bash
# Set up a cron job to ping every 5 minutes
*/5 * * * * curl https://your-app.vercel.app/api/warmup
```

### Issue: Database connection fails

**Solution**: Verify connection string format

```bash
# Correct format
ORACLE_CONNECTION_STRING=hostname:1521/service_name

# Test locally first
python -c "import oracledb; print('OK')"
```

## Performance Tips

1. **Enable Warmup**: Set up scheduled pings to `/api/warmup`
2. **Monitor Logs**: Use `vercel logs` to track performance
3. **Upgrade Plan**: Consider Vercel Pro for 60s timeout (vs 10s Hobby)
4. **Optimize Queries**: Keep database queries fast (< 5s)

## Next Steps

- Read [VERCEL_DEPLOYMENT_GUIDE.md](./VERCEL_DEPLOYMENT_GUIDE.md) for detailed instructions
- Read [SERVERLESS_OPTIMIZATION.md](./SERVERLESS_OPTIMIZATION.md) for performance tuning
- Set up monitoring and alerting
- Configure custom domain (optional)

## Support

- Vercel Docs: https://vercel.com/docs
- Project Issues: [Your repo issues page]
- Vercel Support: https://vercel.com/support
