import google.generativeai as genai
from dotenv import load_dotenv
import os

load_dotenv()

api_key = os.getenv('LLM_API_KEY')
genai.configure(api_key=api_key)

print("Available Gemini models:")
for model in genai.list_models():
    if 'generateContent' in model.supported_generation_methods:
        print(f"  - {model.name}")
