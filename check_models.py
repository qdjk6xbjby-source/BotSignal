import os
from google import genai
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def list_models():
    client = genai.Client(api_key=GEMINI_API_KEY)
    print("Доступные модели:")
    for m in client.models.list():
        # В новой библиотеке genai атрибуты могут быть другими. Попробуем просто m.
        print(f"Name: {m.name}")

if __name__ == "__main__":
    try:
        list_models()
    except Exception as e:
        print(f"Ошибка при получении списка моделей: {e}")
