# Vercel Deployment Guide

This guide provides step-by-step instructions for deploying the Flask Chatbot MCP application to Vercel.

## Prerequisites

- Vercel account (sign up at https://vercel.com)
- Vercel CLI installed (optional, for command-line deployment)
- Git repository with your application code

## Vercel Configuration

The application includes a `vercel.json` configuration file with the following settings:

```json
{
  "version": 2,
  "builds": [
    {
      "src": "app.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/static/(.*)",
      "dest": "/static/$1"
    },
    {
      "src": "/(.*)",
      "dest": "app.py"
    }
  ],
  "env": {
    "FLASK_ENV": "production"
  }
}
```

### Configuration Explanation

- **builds**: Specifies that `app.py` should be built using the Python runtime
- **routes**: Defines URL routing - static files are served directly, all other requests go to Flask
- **env**: Sets Flask environment to production mode

## Environment Variables Configuration

### Required Environment Variables

Configure these in the Vercel dashboard under Project Settings > Environment Variables:

#### Flask Configuration
- `SECRET_KEY` - Flask session secret key (generate a secure random string)
- `FLASK_ENV` - Set to `production`

#### LLM Service Configuration
- `LLM_API_KEY` - API key for your LLM service (OpenAI, Anthropic, etc.)
- `LLM_MODEL` - Model name (e.g., `gpt-4`, `gpt-3.5-turbo`, `claude-3-sonnet`)
- `LLM_API_BASE_URL` - API base URL (default: `https://api.openai.com/v1`)
- `LLM_MAX_TOKENS` - Maximum tokens per response (default: `1000`)
- `LLM_TEMPERATURE` - Response creativity (0.0-1.0, default: `0.7`)
- `LLM_TIMEOUT` - API timeout in seconds (default: `30`)
- `LLM_MAX_RETRIES` - Maximum retry attempts (default: `3`)

#### Oracle Database Configuration
- `ORACLE_CONNECTION_STRING` - Oracle database connection string (format: `host:port/service_name`)
- `ORACLE_USER` - Database username
- `ORACLE_PASSWORD` - Database password
- `ORACLE_ALLOWED_VIEWS` - Comma-separated list of allowed views (e.g., `view1,view2,view3`)

#### PDF Connector Configuration
- `PDF_STORAGE_PATH` - Path to PDF storage directory (use `/tmp` for Vercel)
- `PDF_INDEX_FILE` - Path to PDF index file (default: `./pdf_index.json`)
- `PDF_INDEX_REFRESH_INTERVAL` - Index refresh interval in seconds (default: `3600`)
- `PDF_MAX_SEARCH_RESULTS` - Maximum search results to return (default: `10`)

#### Application Settings
- `SESSION_TIMEOUT` - Session timeout in seconds (default: `1800`)
- `MAX_CONVERSATION_HISTORY` - Maximum messages to keep in history (default: `50`)
- `QUERY_TIMEOUT` - Database query timeout in seconds (default: `5`)
- `MAX_RESULT_SIZE` - Maximum result set size (default: `1000`)

#### Logging Configuration
- `LOG_LEVEL` - Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`)
- `LOG_JSON` - Enable JSON logging (set to `true` for production)

### Setting Environment Variables in Vercel Dashboard

1. Go to your project in Vercel dashboard
2. Navigate to **Settings** > **Environment Variables**
3. Add each variable with appropriate values
4. Select which environments to apply to (Production, Preview, Development)
5. Click **Save**

### Setting Environment Variables via CLI

```bash
vercel env add SECRET_KEY production
vercel env add LLM_API_KEY production
vercel env add ORACLE_CONNECTION_STRING production
# ... add other variables
```

## Deployment Methods

### Method 1: Deploy via Git Integration (Recommended)

1. Push your code to GitHub, GitLab, or Bitbucket
2. Go to Vercel dashboard and click **Add New Project**
3. Import your Git repository
4. Vercel will auto-detect the Flask application
5. Configure environment variables
6. Click **Deploy**

### Method 2: Deploy via Vercel CLI

1. Install Vercel CLI:
   ```bash
   npm install -g vercel
   ```

2. Login to Vercel:
   ```bash
   vercel login
   ```

3. Deploy from project directory:
   ```bash
   vercel
   ```

4. Follow the prompts to configure your project

5. Deploy to production:
   ```bash
   vercel --prod
   ```

## Build Settings

Vercel will automatically detect and use these settings:

- **Framework Preset**: Other
- **Build Command**: (none required)
- **Output Directory**: (none required)
- **Install Command**: `pip install -r requirements.txt`

## Serverless Function Limits

Be aware of Vercel's serverless function limits:

### Hobby Plan
- **Execution Timeout**: 10 seconds
- **Memory**: 1024 MB
- **Deployment Size**: 100 MB

### Pro Plan
- **Execution Timeout**: 60 seconds
- **Memory**: 3008 MB
- **Deployment Size**: 250 MB

The application is optimized to work within these limits through:
- Lazy loading of dependencies
- Connection caching
- Efficient initialization
- Streaming responses for long operations

## Post-Deployment Verification

After deployment, verify the application:

1. **Health Check**: Visit `https://your-app.vercel.app/api/health`
   - Should return: `{"status": "healthy"}`

2. **Chat Interface**: Visit `https://your-app.vercel.app/`
   - Should display the chat interface

3. **Test Conversation**: Send a test message
   - Verify LLM integration works
   - Test database queries (if applicable)
   - Test PDF search (if applicable)

## Troubleshooting

### Cold Start Issues
- **Symptom**: First request takes longer than 10 seconds
- **Solution**: Optimize initialization code, use lazy loading

### Database Connection Errors
- **Symptom**: "Unable to connect to database"
- **Solution**: Verify `ORACLE_CONNECTION_STRING`, `ORACLE_USER`, and `ORACLE_PASSWORD` are correct

### LLM API Errors
- **Symptom**: "LLM service unavailable"
- **Solution**: Verify `LLM_API_KEY` is valid and has sufficient credits

### PDF Processing Errors
- **Symptom**: "PDF documents not found"
- **Solution**: Ensure PDFs are accessible at `PDF_STORAGE_PATH` (note: Vercel has read-only filesystem except `/tmp`)

### Session Issues
- **Symptom**: Conversation history not persisting
- **Solution**: Verify `SECRET_KEY` is set and consistent across deployments

## Monitoring and Logs

### View Logs in Vercel Dashboard
1. Go to your project in Vercel dashboard
2. Click on **Deployments**
3. Select a deployment
4. Click **View Function Logs**

### View Logs via CLI
```bash
vercel logs [deployment-url]
```

## Continuous Deployment

Vercel automatically deploys when you push to your Git repository:

- **Production**: Pushes to `main` or `master` branch
- **Preview**: Pushes to other branches or pull requests

## Security Best Practices

1. **Never commit secrets**: Use environment variables for all sensitive data
2. **Rotate credentials**: Regularly update API keys and database passwords
3. **Use HTTPS**: Vercel provides automatic HTTPS for all deployments
4. **Enable CORS**: Configure CORS headers appropriately in Flask
5. **Rate limiting**: Implement rate limiting on chat endpoint

## Performance Optimization

1. **Enable caching**: Cache frequently accessed data
2. **Optimize queries**: Use indexed views and limit result sets
3. **Compress responses**: Enable gzip compression in Flask
4. **Monitor metrics**: Use Vercel Analytics to track performance

## Scaling Considerations

For high-traffic applications:

1. **Upgrade to Pro plan**: Get longer execution timeouts and more memory
2. **Use external caching**: Consider Redis for session storage
3. **Optimize database**: Use connection pooling and read replicas
4. **CDN for static assets**: Vercel automatically uses CDN for static files

## Support and Resources

- Vercel Documentation: https://vercel.com/docs
- Vercel Python Runtime: https://vercel.com/docs/runtimes#official-runtimes/python
- Vercel Support: https://vercel.com/support

## Rollback Procedure

If a deployment has issues:

1. Go to Vercel dashboard > **Deployments**
2. Find a previous working deployment
3. Click the three dots menu
4. Select **Promote to Production**

Or via CLI:
```bash
vercel rollback
```
