import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
api_key = os.environ.get("GEMINI_API_KEY")
print(f"API Key present: {bool(api_key)}")

try:
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents="Mambo"
    )
    print("Gemini Test SUCCESS!")
    print("Response:", response.text)
except Exception as e:
    print("Gemini Test ERROR:", str(e))
