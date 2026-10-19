# Vercel Configuration Reference

**Official Documentation:** https://vercel.com/docs/projects/project-configuration

## IMPORTANT: Do NOT use deprecated `builds` property

The `builds` property was deprecated in 2020. Vercel now auto-detects Python applications.

## Current Configuration (vercel.json)

```json
{
  "functions": {
    "api/index.py": {
      "memory": 1024,
      "maxDuration": 10
    }
  }
}
```

## Project Structure for Vercel

Vercel requires serverless functions to be in the `api/` directory:

```
awdc-chat/
├── api/
│   └── index.py          # Main Flask app (copy of app.py)
├── app.py                # Local development version
├── requirements.txt      # Python dependencies
└── vercel.json          # Vercel configuration
```

## How Vercel Detects Python Apps

Vercel automatically detects Python serverless functions when:
1. A `requirements.txt` file exists in the root
2. Python files are in the `api/` directory
3. The file exports a WSGI/ASGI application

**No `builds` property needed!**

## Configuration Properties

### `functions` (Optional)
Configure serverless function settings:
- `memory`: RAM allocation (128-3008 MB)
- `maxDuration`: Timeout in seconds (1-900s, Hobby: max 10s, Pro: max 60s)

### `routes` (Optional)
Define URL routing:
- `src`: Source pattern (regex)
- `dest`: Destination file or path

## What NOT to do

❌ **NEVER use both `builds` and `functions`**
```json
{
  "builds": [...],      // DEPRECATED - DO NOT USE
  "functions": {...}    // Modern way
}
```

❌ **NEVER use `builds` at all**
```json
{
  "builds": [
    {
      "src": "app.py",
      "use": "@vercel/python"  // This is deprecated!
    }
  ]
}
```

## References

- Vercel Configuration: https://vercel.com/docs/projects/project-configuration
- Python on Vercel: https://vercel.com/docs/functions/runtimes/python
- Serverless Functions: https://vercel.com/docs/functions/serverless-functions

## Migration from `builds` to modern config

If you see `builds` in any config:
1. **Delete the entire `builds` section**
2. Keep only `functions` for memory/timeout config
3. Vercel will auto-detect Python from `requirements.txt`

That's it. No other changes needed.
