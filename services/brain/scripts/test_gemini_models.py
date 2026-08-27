import sys; sys.path.insert(0,'services/brain')
from dotenv import load_dotenv; load_dotenv('services/brain/.env', override=True)
import asyncio, httpx, os

async def test():
    key = os.getenv('GEMINI_API_KEY')
    # Test model names directly via REST
    models_to_try = ['gemini-3.1-flash-lite', 'gemini-2.5-flash', 'gemini-flash-lite-latest']
    for model in models_to_try:
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
        payload = {
            'systemInstruction': {'parts': [{'text': 'You are VYOM.'}]},
            'contents': [{'role': 'user', 'parts': [{'text': 'Say: VYOM_LIVE_OK'}]}],
            'generationConfig': {'temperature': 0.1}
        }
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(url, headers={'x-goog-api-key': key, 'Content-Type': 'application/json'}, json=payload)
            if r.status_code == 200:
                data = r.json()
                text = data['candidates'][0]['content']['parts'][0]['text']
                print(f'  OK [{model}]: {text[:60].strip()}')
                break
            else:
                print(f'  FAIL [{model}]: HTTP {r.status_code}')

asyncio.run(test())
