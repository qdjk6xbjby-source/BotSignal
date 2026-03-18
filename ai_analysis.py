import os
import logging
import asyncio
import sys
from google import genai
from dotenv import load_dotenv

# Попытка исправить кодировку для Windows консоли
if sys.platform == "win32":
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except Exception:
        pass

logger = logging.getLogger(__name__)

# Загрузка переменных окружения с использованием абсолютного пути
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path, override=True)
else:
    load_dotenv() 

# Ищем ключ в разных возможных переменных
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
AI_ENABLED = os.getenv("AI_ENABLED", "False").lower() == "true"

client = None
if AI_ENABLED and GEMINI_API_KEY:
    try:
        # ВАЖНО: прокидываем ключ явно в клиент
        client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Gemini AI успешно настроен.")
    except Exception as e:
        logger.error(f"Ошибка настройки Gemini: {e}")
        AI_ENABLED = False
else:
    if not GEMINI_API_KEY:
        logger.error(f"КРИТИЧЕСКАЯ ОШИБКА: Ключ не найден в {env_path}")
    logger.warning("Gemini AI отключен или отсутствует API ключ.")

async def get_ai_trading_insight(symbol, signal_type, indicators, news_context="Нет важных новостей"):
    if not AI_ENABLED or client is None:
        return None

    prompt = f"""
    Ты - профессиональный эксперт по торговле на Forex с 20-летним опытом. 
    Твоя задача: проанализировать торговый сигнал и дать краткий, но глубокий комментарий.

    ДАННЫЕ:
    - Валютная пара: {symbol}
    - Рекомендация тех. анализа: {signal_type}
    - Индикаторы: {indicators}
    - Фундаментальный контекст (Новости): {news_context}

    ТРЕБОВАНИЯ К ОТВЕТУ:
    1. Будь предельно конкретен.
    2. Оцени риск (Низкий/Средний/Высокий).
    3. Дай совет по входу (например, "дождаться отката" или "заходить по текущим").
    4. Максимум 3-4 предложения на русском языке.
    5. Начни с фразы "🧠 АНАЛИЗ ИИ:"

    Сформулируй профессиональное мнение.
    """

    models_to_try = ['gemini-2.0-flash', 'gemini-flash-latest', 'gemini-2.0-flash-lite']

    for model_name in models_to_try:
        try:
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=prompt
            )
            return response.text.strip()
        except Exception as e:
            logger.warning(f"Ошибка с моделью {model_name}: {e}")
            if "429" in str(e):
                await asyncio.sleep(2)
            continue

    return "⚠️ Анализ ИИ временно недоступен (лимиты API)."

if __name__ == "__main__":
    async def test():
        print(f"--- ДИАГНОСТИКА ---")
        print(f"Папка скрипта: {script_dir}")
        print(f"Файл .env существует: {os.path.exists(env_path)}")
        print(f"GEMINI_API_KEY найден: {'Да' if os.getenv('GEMINI_API_KEY') else 'Нет'}")
        print(f"GOOGLE_API_KEY найден: {'Да' if os.getenv('GOOGLE_API_KEY') else 'Нет'}")
        print(f"AI_ENABLED: {AI_ENABLED}")
        print(f"-------------------")
        
        if not GEMINI_API_KEY:
            print("ОШИБКА: Ключ всё еще не виден! Проверьте содержимое .env")
            return

        print("Запуск теста запроса...")
        res = await get_ai_trading_insight("EURUSD", "📈 ВВЕРХ (BUY)", "RSI: 60, ADX: 25", "No news")
        print(f"\nОТВЕТ ИИ:\n{res}")
    
    asyncio.run(test())
