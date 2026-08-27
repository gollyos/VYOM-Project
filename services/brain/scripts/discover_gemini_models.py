import sys; sys.path.insert(0,'services/brain')
from dotenv import load_dotenv; load_dotenv('services/brain/.env', override=True)
import asyncio, httpx, os

async def test():
    key = os.getenv('GEMINI_API_KEY')
    print('Key:', key[:10], '...')
    # List available models
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(
            'https://generativelanguage.googleapis.com/v1beta/models',
            headers={'x-goog-api-key': key}
        )
        data = r.json()
        models = [m['name'] for m in data.get('models', []) if 'flash' in m['name'].lower()]
        print('Flash models available:')
        for m in models[:10]:
            print(' ', m)

asyncio.run(test())
