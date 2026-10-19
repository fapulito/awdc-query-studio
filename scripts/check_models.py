import os
from dotenv import load_dotenv
import requests

load_dotenv()

api_key = os.getenv('LLM_API_KEY')
headers = {'Authorization': f'Bearer {api_key}'}

try:
    response = requests.get('https://api.openai.com/v1/models', headers=headers)
    if response.status_code == 200:
        models = [m['id'] for m in response.json()['data'] if 'gpt' in m['id']]
        print("Available GPT models:")
        for model in sorted(models):
            print(f"  - {model}")
    else:
        print(f"Error: {response.status_code}")
        print(response.text)
except Exception as e:
    print(f"Error: {e}")
