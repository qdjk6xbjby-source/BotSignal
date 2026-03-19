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

# Загрузка переменных окружения
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')

if os.path.exists(env_path):
    load_dotenv(env_path, override=True)
else:
    load_dotenv()

# Ищем ключ (сначала в GEMINI_API_KEY, потом в GOOGLE_API_KEY)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") 
if not GEMINI_API_KEY:
    GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")

AI_ENABLED = os.getenv("AI_ENABLED", "False").lower() == "true"

# Настройка клиента
client = None
if AI_ENABLED:
    if GEMINI_API_KEY:
        try:
            # Маскированный вывод ключа для диагностики
            masked_key = f"{GEMINI_API_KEY[:4]}...{GEMINI_API_KEY[-4:]}"
            logger.info(f"Настройка Gemini (Ключ: {masked_key})")
            
            client = genai.Client(api_key=GEMINI_API_KEY)
            logger.info("Gemini AI клиент успешно создан.")
        except Exception as e:
            logger.error(f"Ошибка при инициализации Gemini: {e}")
            AI_ENABLED = False
    else:
        logger.error(f"КРИТИЧЕСКАЯ ОШИБКА: API ключ не найден в окружении (проверьте {env_path})")
        AI_ENABLED = False
else:
    logger.warning("Gemini AI отключен в настройках (AI_ENABLED=False).")

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

    # Список моделей от самой "умной" к более легким
    models_to_try = ['gemini-2.0-flash', 'gemini-2.0-flash-lite', 'gemini-1.5-flash']

    for model_name in models_to_try:
        try:
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=prompt
            )
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                logger.warning(f"⚠️ Лимит API превышен для {model_name}. Ждем...")
                return "⚠️ Анализ ИИ временно недоступен (лимиты API ключа)."
            
            logger.warning(f"Ошибка с моделью {model_name}: {e}")
            continue

    return "⚠️ Не удалось получить анализ ИИ (ошибка сервиса)."

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
