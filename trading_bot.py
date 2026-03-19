import os
import sys
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.bot import DefaultBotProperties
from aiohttp import ClientTimeout
from tradingview_ta import TA_Handler, Interval
import random
import time as time_sync

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Секция авто-обновления для хостинга (Bothost.ru и др.) ---
try:
    import pydantic
    from aiogram import __version__ as aiogram_v
    if int(pydantic.__version__.split('.')[0]) < 2:
        raise ImportError
except (ImportError, AttributeError):
    print("🔧 [Bootloader] Установка/обновление зависимостей на сервере...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pydantic>=2.0.0", "aiogram>=3.0.0", "google-genai", "httpx", "tradingview-ta", "python-dotenv", "pytz", "requests"])
    print("✅ [Bootloader] Библиотеки обновлены. Перезапуск бота...")
    os.execv(sys.executable, [sys.executable] + sys.argv)
# -----------------------------------------------------------

# Попытка исправить кодировку в консоли Windows
"""
if sys.platform == "win32":
    import io
    try:
        # Проверяем, можно ли переобернуть поток
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        if hasattr(sys.stderr, 'buffer'):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except (AttributeError, ValueError, io.UnsupportedOperation):
        pass
"""

import requests
from datetime import datetime, timedelta, time
import pytz
import csv
import io
import httpx
import xml.etree.ElementTree as ET
from ai_analysis import get_ai_trading_insight

# Список User-Agent для ротации
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
    'Mozilla/5.0 (AppleWebKit/537.36, like Gecko) Chrome/121.0.0.0 Safari/537.36'
]

def get_random_headers():
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
    }
    return headers

HEADERS = get_random_headers() # Дефолтные заголовки

# Сентимент-кэш
GLOBAL_SENTIMENT = {
    "vix": "NEUTRAL",
    "trends": "NEUTRAL",
    "retail": {}
}

class ProxyManager:
    def __init__(self, proxies_str):
        self.proxies = []
        if proxies_str:
            parts = proxies_str.split(',')
            for p in parts:
                p = p.strip()
                if not p: continue
                # Ожидаемый формат: ip:port:login:password
                # Или просто ip:port
                elements = p.split(':')
                if len(elements) == 4:
                    ip, port, user, pw = elements
                    self.proxies.append({
                        "http": f"http://{user}:{pw}@{ip}:{port}",
                        "https": f"http://{user}:{pw}@{ip}:{port}"
                    })
                elif len(elements) == 2:
                    ip, port = elements
                    self.proxies.append({
                        "http": f"http://{ip}:{port}",
                        "https": f"http://{ip}:{port}"
                    })

    def get_proxy(self):
        if not self.proxies:
            return None
        return random.choice(self.proxies)

    def get_masked_proxy(self, proxy_dict):
        if not proxy_dict:
            return "DIRECT"
        # Маскируем для логов: http://user:***@ip:port
        p = proxy_dict['http']
        if '@' in p:
            parts = p.split('@')
            return f"***@{parts[1]}"
        return p

class RobustProxyManager:
    def __init__(self, file_path="proxies.txt"):
        self.file_path = file_path
        self.proxies = []
        self.load_proxies()

    def load_proxies(self):
        try:
            path = os.path.join(os.path.dirname(__file__), self.file_path)
            if os.path.exists(path):
                with open(path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        elements = line.split(':')
                        if len(elements) == 4:
                            ip, port, user, pw = elements
                            self.proxies.append(f"socks5://{user}:{pw}@{ip}:{port}")
                        elif len(elements) == 2:
                            ip, port = elements
                            self.proxies.append(f"socks5://{ip}:{port}")
                logger.info(f"Загружено {len(self.proxies)} прокси из {self.file_path}")
            else:
                logger.warning(f"Файл {self.file_path} не найден. Работаем без прокси.")
        except Exception as e:
            logger.error(f"Ошибка при загрузке прокси: {e}")

    def get_proxy(self):
        if not self.proxies:
            return None
        return random.choice(self.proxies)

proxy_manager = RobustProxyManager()

# Кэш для H1 анализа {symbol: (recommendation, timestamp)}
h1_cache = {}
H1_CACHE_TTL = 900  # 15 минут

# Маппинг символов для отчетов COT...
COT_MAPPING = {
    "EUR": "EURO FX",
    "GBP": "BRITISH POUND",
    "JPY": "JAPANESE YEN",
    "AUD": "AUSTRALIAN DOLLAR",
    "CAD": "CANADIAN DOLLAR",
    "NZD": "NEW ZEALAND DOLLAR",
    "CHF": "SWISS FRANC",
    "MXN": "MEXICAN PESO"
}

# Функция для получения времени в МСК (UTC+3)

# Функция для получения времени в МСК (UTC+3)
def get_now_msk():
    return datetime.utcnow() + timedelta(hours=3)

# Загрузка конфигурации
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path)
    logger.info("Файл .env загружен.")
else:
    logger.warning("Файл .env не найден! Пытаюсь использовать переменные окружения.")

BOT_TOKEN = os.getenv("BOT_TOKEN")
raw_allowed = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS = [int(u.strip()) for u in raw_allowed.split(",") if u.strip().isdigit()]

if not BOT_TOKEN:
    logger.error("КРИТИЧЕСКАЯ ОШИБКА: BOT_TOKEN не найден!")
    sys.exit(1)

if not ALLOWED_USERS:
    logger.error("КРИТИЧЕСКАЯ ОШИБКА: ALLOWED_USERS пуст! Кому слать сигналы?")
    sys.exit(1)

logger.info(f"Загружено ID пользователей: {len(ALLOWED_USERS)}")

if not BOT_TOKEN:
    print("Ошибка: BOT_TOKEN не найден в .env!")
    exit(1)

# Настройка сессии с таймаутом 120 секунд для стабильности
session = AiohttpSession(timeout=120.0)
bot = Bot(
    token=BOT_TOKEN, 
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)
dp = Dispatcher()

# Список валютных пар для отслеживания
# Мы используем FOREX для большинства валют. 
# Биржа FX_IDC или SAXO обычно дает хорошие данные для TradingView
SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", 
    "EURJPY", "EURGBP", "GBPJPY", "NZDUSD", "USDCHF"
]

# Чтобы не спамить одним и тем же сигналом каждую секунду
last_signals = {}

# Глобальное состояние бота для команды /status
bot_state = {
    "start_time": get_now_msk(),
    "last_scan_time": None,
    "total_scans": 0,
    "signals_sent": 0,
    "is_paused": False,
    "status_msg": "Запуск...",
    "news_events": [],  # Список важных новостей
    "cot_data": {}      # Данные COT отчетов
}

class COTFetcher:
    def __init__(self):
        self.url = "https://www.cftc.gov/dea/newcot/deafut.txt"
        self.last_update = None
        
    async def update_cot(self):
        try:
            logger.info("Обновление COT отчетов (CFTC)...")
            response = await asyncio.to_thread(requests.get, self.url, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                content = response.text
                f = io.StringIO(content)
                reader = csv.reader(f)
                cot_results = {}
                for row in reader:
                    if not row: continue
                    market_name = row[0].strip()
                    # Проверяем, есть ли этот рынок в нашем маппинге
                    for key, val in COT_MAPPING.items():
                        if val in market_name:
                            try:
                                long_pos = int(row[8].strip())
                                short_pos = int(row[9].strip())
                                # Сентимент: (Long - Short) / (Long + Short)
                                sentiment = (long_pos - short_pos) / (long_pos + short_pos) if (long_pos + short_pos) > 0 else 0
                                cot_results[key] = {
                                    "sentiment": round(sentiment, 4),
                                    "long": long_pos,
                                    "short": short_pos
                                }
                            except (ValueError, IndexError):
                                continue
                bot_state["cot_data"] = cot_results
                self.last_update = get_now_msk()
                logger.info(f"Загружены данные COT для {len(cot_results)} валют.")
        except Exception as e:
            logger.error(f"Ошибка при загрузке COT: {e}")

cot_fetcher = COTFetcher()

def is_market_active():
    """Проверка торговых сессий (UTC)"""
    now = datetime.utcnow().time()
    # Лондон: 08:00 - 16:00 UTC
    # Нью-Йорк: 13:00 - 21:00 UTC
    # Мы разрешаем торговлю с 07:00 (пре-маркет Лондона) до 22:00 UTC
    start_time = time(7, 0)
    end_time = time(22, 0)
    
    # Пятница вечер и выходные (Форекс закрыт)
    now_dt = datetime.utcnow()
    if now_dt.weekday() == 4 and now_dt.hour > 21: # Пятница после 21:00 UTC
        return False, "Рынок закрывается (Пятница)"
    if now_dt.weekday() > 4: # Суббота, Воскресенье
        return False, "Выходные (Рынок закрыт)"
        
    if start_time <= now <= end_time:
        return True, "Активная сессия"
    else:
        return False, "Сессия закрыта (Ночь)"

class NewsFetcher:
    def __init__(self):
        self.url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
        self.last_update = None
        
    async def fetch_news(self):
        try:
            logger.info("Обновление экономического календаря...")
            response = await asyncio.to_thread(requests.get, self.url, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                events = []
                for event in root.findall('event'):
                    impact = event.find('impact').text
                    if impact == 'High':
                        title = event.find('title').text
                        country = event.find('country').text
                        date_str = event.find('date').text # MM-DD-YYYY
                        time_str = event.find('time').text # HH:MMam/pm
                        
                        # Парсим время (оно в EST/EDT обычно, но для простоты считаем UTC и добавим сдвиг)
                        # В идеале нужно приводить к одному часовому поясу
                        try:
                            # Пример: 03-17-2026 12:30pm
                            full_date_str = f"{date_str} {time_str}"
                            event_dt = datetime.strptime(full_date_str, "%m-%d-%Y %I:%M%p")
                            # ForexFactory XML обычно в EST (UTC-5/UTC-4). 
                            # Если у пользователя UTC+3, разница около 7-8 часов.
                            # Для точности на сервере лучше использовать pytz, но пока сделаем базово.
                            events.append({
                                "country": country,
                                "title": title,
                                "dt": event_dt
                            })
                        except:
                            continue
                bot_state["news_events"] = events
                self.last_update = get_now_msk()
                logger.info(f"Загружено {len(events)} важных новостей.")
        except Exception as e:
            logger.error(f"Ошибка при загрузке новостей: {e}")

news_fetcher = NewsFetcher()

def is_news_time(symbol):
    """Проверяет, нет ли важных новостей по валютам в паре прямо сейчас (+/- 30 мин)"""
    if not bot_state["news_events"]:
        return False
    
    # Извлекаем валюты из пары (например, EUR и USD из EURUSD)
    currencies = [symbol[:3], symbol[3:]]
    now = get_now_msk()
    
    for event in bot_state["news_events"]:
        if event["country"] in currencies:
            # Если новость в пределах 30 минут от текущего времени
            diff = abs((event["dt"] - now).total_seconds()) / 60
            if diff < 30:
                return event["title"]
    return False

async def get_vix_sentiment():
    """Получает индекс страха VIX с TradingView"""
    global GLOBAL_SENTIMENT
    try:
        handler = TA_Handler(
            symbol="VIX",
            screener="cfd",
            exchange="CBOE-FX",
            interval=Interval.INTERVAL_1_HOUR,
            timeout=10
        )
        analysis = await asyncio.to_thread(handler.get_analysis)
        price = analysis.indicators.get("close")
        if price > 25:
            sent = "EXTREME_FEAR"
        elif price > 20:
            sent = "FEAR"
        elif price < 15:
            sent = "GREED"
        else:
            sent = "NEUTRAL"
        GLOBAL_SENTIMENT["vix"] = sent
        logger.info(f"VIX: {price} ({sent})")
    except Exception as e:
        logger.debug(f"Ошибка получения VIX: {e}")

async def get_trends_sentiment():
    """Получает индекс страха и жадности (прокси для Google Trends/Сентимента)"""
    global GLOBAL_SENTIMENT
    try:
        # Используем открытый API Alternative.me для индекса страха и жадности
        async with httpx.AsyncClient(headers=HEADERS) as client:
            r = await client.get("https://api.alternative.me/fng/?limit=1", timeout=10)
            if r.status_code == 200:
                data = r.json()
                value = int(data['data'][0]['value'])
                classify = data['data'][0]['value_classification']
                GLOBAL_SENTIMENT["trends"] = classify.upper().replace(" ", "_")
                logger.info(f"Sentiment (F&G): {value} ({classify})")
    except Exception as e:
        logger.debug(f"Ошибка получения Sentiment: {e}")

async def get_retail_sentiment():
    """Заглушка для Retail Sentiment (DailyFX)"""
    # В реальности тут был бы скрапер DailyFX, для стабильности пока возвращаем нейтраль
    GLOBAL_SENTIMENT["retail"] = {}

async def update_macro_sentiment():
    """Периодическое обновление макро-сентимента"""
    await get_vix_sentiment()
    await get_trends_sentiment()
    await get_retail_sentiment()

async def get_tradingview_summary(symbol, interval):
    """Получает техническое резюме с TradingView для заданного интервала"""
    try:
        handler = TA_Handler(
            symbol=symbol,
            screener="forex",
            exchange="FX_IDC",
            interval=interval,
            timeout=10
        )
        analysis = await asyncio.to_thread(handler.get_analysis)
        return analysis.summary.get('RECOMMENDATION', 'NEUTRAL')
    except Exception as e:
        logger.debug(f"Ошибка TradingView ({interval}) для {symbol}: {e}")
        return "ERROR"

async def get_signal(symbol):
    try:
        # 0. Проверка сессии
        active, reason = is_market_active()
        if not active:
            logger.info(f"Пропуск {symbol}: {reason}")
            return None

        # 0.1 Проверка новостей
        news_title = is_news_time(symbol)
        if news_title:
            logger.info(f"Сигнал по {symbol} отменен: важная новость ({news_title})")
            return "NEWS_BLOCK"

        # 0. Проверка VIX (Macro Fear)
        vix = GLOBAL_SENTIMENT.get("vix")
        
        # 1. Анализ Трендов (H1) с кэшированием
        now_ts = time_sync.time()
        cached_h1 = h1_cache.get(symbol)
        
        if cached_h1 and (now_ts - cached_h1[1]) < H1_CACHE_TTL:
            rec_h1 = cached_h1[0]
            logger.debug(f"Используем кэшированный тренд H1 для {symbol}: {rec_h1}")
        else:
            proxy = proxy_manager.get_proxy()
            handler_h1 = TA_Handler(
                symbol=symbol,
                screener="forex",
                exchange="FX_IDC",
                interval=Interval.INTERVAL_1_HOUR,
                timeout=10,
                proxy=proxy
            )
            analysis_h1 = await asyncio.to_thread(handler_h1.get_analysis)
            rec_h1 = analysis_h1.summary.get('RECOMMENDATION')
            h1_cache[symbol] = (rec_h1, now_ts)
            logger.info(f"Обновлен тренд H1 для {symbol}: {rec_h1} (через {proxy or 'DIRECT'})")
        
        # Тренд должен быть сильным
        if rec_h1 not in ["STRONG_BUY", "STRONG_SELL"]:
            return None

        # 2. Анализ Сигнала (M15)
        proxy = proxy_manager.get_proxy()
        handler_m15 = TA_Handler(
            symbol=symbol,
            screener="forex",
            exchange="FX_IDC",
            interval=Interval.INTERVAL_15_MINUTES,
            timeout=10,
            proxy=proxy
        )
        analysis_m15 = await asyncio.to_thread(handler_m15.get_analysis)
        rec_m15 = analysis_m15.summary.get('RECOMMENDATION')
        
        if rec_h1 == "STRONG_BUY" and rec_m15 not in ["BUY", "STRONG_BUY"]:
            return None
        if rec_h1 == "STRONG_SELL" and rec_m15 not in ["SELL", "STRONG_SELL"]:
            return None

        # 3. Анализ точки входа (M5)
        proxy = proxy_manager.get_proxy()
        handler_m5 = TA_Handler(
            symbol=symbol,
            screener="forex",
            exchange="FX_IDC",
            interval=Interval.INTERVAL_5_MINUTES,
            timeout=10,
            proxy=proxy
        )
        analysis_m5 = await asyncio.to_thread(handler_m5.get_analysis)
        rec_m5 = analysis_m5.summary.get('RECOMMENDATION')
        
        # Подтверждение направления
        if rec_h1 == "STRONG_BUY" and rec_m5 not in ["BUY", "STRONG_BUY"]:
            return None
        if rec_h1 == "STRONG_SELL" and rec_m5 not in ["SELL", "STRONG_SELL"]:
            return None

        # 5. Фильтр VIX и Trends (Риск-офф)
        trends = GLOBAL_SENTIMENT.get("trends", "NEUTRAL")
        
        # Если на рынке экстремальный страх (VIX или Trends)
        if vix in ["FEAR", "EXTREME_FEAR"] or "FEAR" in trends:
            if any(x in symbol for x in ["AUD", "GBP", "EUR"]) and "BUY" in rec_h1:
                logger.info(f"Сигнал {symbol} (BUY) отменен: Паника на рынках (VIX/Trends)")
                return None
        
        # Если на рынке экстремальная жадность - риск коррекции
        if "GREED" in trends and vix == "GREED":
            logger.info(f"Сигнал {symbol} отменен: Экстремальная жадность (риск разворота)")
            return None

        # 4. Фильтр по полосам Боллинджера (и волатильность) на М15
        bb_upper = analysis_m15.indicators.get("BB.upper")
        bb_lower = analysis_m15.indicators.get("BB.lower")
        rsi = analysis_m15.indicators.get("RSI")
        adx = analysis_m15.indicators.get("ADX")
        current_price = analysis_m15.indicators.get("close")

        if bb_upper and bb_lower:
            bb_width = bb_upper - bb_lower
            # Фильтр волатильности (если канал слишком узкий - рынок спит)
            if bb_width / current_price < 0.0001: # Пример порога 0.01%
                logger.info(f"Сигнал {symbol} отменен: слишком низкая волатильность (флет)")
                return None

            if rec_h1 == "STRONG_BUY" and (bb_upper - current_price) < bb_width * 0.1:
                logger.info(f"Сигнал {symbol} отменен: цена слишком близко к верхней полосе")
                return None
            if rec_h1 == "STRONG_SELL" and (current_price - bb_lower) < bb_width * 0.1:
                logger.info(f"Сигнал {symbol} отменен: цена слишком близко к нижней полосе")
                return None

        # 5. EMA Crossover подтверждение (на M5)
        ema20 = analysis_m5.indicators.get("EMA20")
        ema50 = analysis_m5.indicators.get("EMA50")
        if ema20 and ema50:
            if rec_h1 == "STRONG_BUY" and ema20 < ema50:
                logger.info(f"Сигнал {symbol} (BUY) отменен: EMA20 < EMA50 на M5")
                return None
            if rec_h1 == "STRONG_SELL" and ema20 > ema50:
                logger.info(f"Сигнал {symbol} (SELL) отменен: EMA20 > EMA50 на M5")
                return None

        # 6. RSI и ADX фильтры (на M15)
        if rsi:
            if rec_h1 == "STRONG_BUY" and rsi > 70:
                logger.info(f"Сигнал {symbol} (BUY) отменен: RSI > 70 на M15 (перекупленность)")
                return None
            if rec_h1 == "STRONG_SELL" and rsi < 30:
                logger.info(f"Сигнал {symbol} (SELL) отменен: RSI < 30 на M15 (перепроданность)")
                return None
        
        if adx and adx < 20:
            logger.info(f"Сигнал {symbol} отменен: ADX < 20 на M15 (слабый тренд)")
            return None

        # 5. Сентимент COT
        cot_status = get_cot_sentiment(symbol)
        if cot_status == "REJECT":
            logger.info(f"Сигнал {symbol} отклонен по отчету COT")
            return None

        rec_type = "Long/BUY" if "BUY" in rec_h1 else "Short/SELL"
        
        return {
            "type": rec_type,
            "confidence": 85, # Базовая уверенность для MTF
            "indicators": f"H1+M15+M5",
            "rsi": round(rsi, 2) if rsi else "N/A",
            "adx": round(adx, 2) if adx else "N/A",
            "vix": vix,
            "cot": cot_status
        }

    except Exception as e:
        error_str = str(e)
        if "429" in error_str:
            logger.warning(f"429 Limit на {symbol}. Пробуем другой прокси...")
            return "RATE_LIMIT"
        logger.error(f"Ошибка при анализе {symbol}: {e}")
    return None

async def get_signal_robust(symbol):
    """Обертка над get_signal для повторных попыток с разными прокси"""
    max_retries = 3
    for attempt in range(max_retries):
        result = await get_signal(symbol)
        if result == "RATE_LIMIT":
            if attempt < max_retries - 1:
                # Ждем чуть-чуть перед сменой прокси
                await asyncio.sleep(random.uniform(1, 3))
                continue
            else:
                return "RATE_LIMIT"
        return result
    return None

async def broadcast_signals():
    """Главный цикл: параллельное сканирование"""
    last_cot_update = None
    last_news_update = None
    while True:
        now = get_now_msk()
        # Периодические задачи
        if last_cot_update is None or (now - last_cot_update).total_seconds() > 43200:
            await cot_fetcher.update_cot()
            await update_macro_sentiment()
            last_cot_update = now
        
        if last_news_update is None or (now - last_news_update).total_seconds() > 3600:
            await news_fetcher.fetch_news()
            last_news_update = now

        bot_state["is_paused"] = False
        bot_state["status_msg"] = "Сканирование..."
        bot_state["last_scan_time"] = get_now_msk()
        bot_state["total_scans"] += 1
        
        logger.info(f"--- НАЧАЛО ЦИКЛА СКАНИРОВАНИЯ #{bot_state['total_scans']} ---")
        
        async def process_symbol(symbol):
            try:
                # Используем робастную версию с повторами через разные прокси
                signal_data = await get_signal_robust(symbol)
                
                if signal_data == "RATE_LIMIT":
                    return "RATE_LIMIT"
                
                if isinstance(signal_data, dict):
                    rec_type = "📈 ВВЕРХ (BUY)" if "BUY" in signal_data['type'] else "📉 ВНИЗ (SELL)"
                    signal_key = f"{symbol}_{signal_data['type']}"
                    
                    if signal_key not in last_signals or (get_now_msk() - last_signals[signal_key]).total_seconds() > 300:
                        last_signals[signal_key] = get_now_msk()
                        
                        message_text = (
                            f"🚀 **ИНТРАДЕЙ СИГНАЛ: {symbol}**\n\n"
                            f"🔔 Рекомендация: **{rec_type}**\n"
                            f"📊 Стратегия: **H1 (Trend) + M15 + M5**\n"
                            f"⏳ Статус: **Вход подтвержден**\n"
                            f"🏛 COT Sentiment: **{signal_data['cot']}**\n"
                            f"📉 VIX (Fear): **{signal_data['vix']}**\n"
                            f"📊 Trends (F&G): **{GLOBAL_SENTIMENT.get('trends')}**\n"
                            f"📈 RSI: **{signal_data['rsi']}** | ADX: **{signal_data['adx']}**\n\n"
                            f"🕒 Время (МСК): {get_now_msk().strftime('%H:%M:%S')}"
                        )
                        
                        # Добавляем анализ ИИ
                        indicators_summary = f"RSI: {signal_data['rsi']}, ADX: {signal_data['adx']}, VIX: {signal_data['vix']}, Strategy: {signal_data['indicators']}"
                        news_block = is_news_time(symbol) or "Нет важных новостей"
                        
                        ai_insight = await get_ai_trading_insight(
                            symbol=symbol,
                            signal_type=rec_type,
                            indicators=indicators_summary,
                            news_context=news_block
                        )
                        
                        if ai_insight:
                            message_text += f"\n\n{ai_insight}"
                        
                        for user_id in ALLOWED_USERS:
                            try:
                                await bot.send_message(chat_id=user_id, text=message_text, parse_mode=ParseMode.MARKDOWN)
                            except Exception as e:
                                logger.error(f"Ошибка отправки {user_id}: {e}")
                        bot_state["signals_sent"] += 1
                return None
            except Exception as e:
                logger.error(f"Ошибка при обработке {symbol}: {e}")
                return None

        chunk_size = 3 # Уменьшили размер чанка, чтобы снизить пиковую нагрузку на API
        market_results = []
        for i in range(0, len(SYMBOLS), chunk_size):
            chunk = SYMBOLS[i:i + chunk_size]
            chunk_results = await asyncio.gather(*[process_symbol(s) for s in chunk])
            market_results.extend(chunk_results)
            
            if "RATE_LIMIT" in chunk_results:
                bot_state["is_paused"] = True
                bot_state["status_msg"] = "Пауза (429)"
                logger.warning("🔴 ОБНАРУЖЕН 429! Превышены лимиты API. Уходим на перерыв 10 минут...")
                await asyncio.sleep(600)
                break
            await asyncio.sleep(2.0) # Увеличили задержку между чанками для стабильности
            
        logger.info(f"--- ЦИКЛ ЗАВЕРШЕН. Отдых 120 секунд. ---")
        bot_state["status_msg"] = "Отдых (120 сек)..."
        await asyncio.sleep(120)

@dp.message()
async def cmd_handler(message: types.Message):
    # Безопасность: проверяем, что пишет именно владелец
    if message.from_user.id not in ALLOWED_USERS:
        logger.warning(f"Попытка доступа от постороннего: {message.from_user.id}")
        return

    if message.text == "/status":
        uptime = get_now_msk() - bot_state["start_time"]
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        last_scan = bot_state["last_scan_time"].strftime('%H:%M:%S') if bot_state["last_scan_time"] else "Нет"
        
        status_text = (
            f"📊 **СТАТУС БОТА**\n\n"
            f"🤖 Состояние: **{bot_state['status_msg']}**\n"
            f"⏱ Работает: `{uptime.days}д {hours}ч {minutes}м`\n"
            f"🔄 Всего сканирований: `{bot_state['total_scans']}`\n"
            f"🚀 Отправлено сигналов: `{bot_state['signals_sent']}`\n"
            f"🕒 Последняя проверка: `{last_scan}`\n\n"
            f"📈 Отслеживаю пар: `{len(SYMBOLS)}`"
        )
        await message.answer(status_text, parse_mode=ParseMode.MARKDOWN)
    
    elif message.text == "/start":
        await message.answer(
            "👋 **Привет! Я Твой Торговый Помощник.**\n\n"
            "Я анализирую рынок по стратегии **H1 (Тренд) + M15 (Сигнал) + M5 (Вход)**.\n\n"
            "📍 Просто жди сигналов или нажми /status для проверки моей работы."
        )

async def main():
    logger.info("Бот-сигнальщик запущен!")
    # Запускаем цикл анализа как фоновую задачу
    asyncio.create_task(broadcast_signals())
    # Запускаем самого бота (если захотим добавить команды вроде /status)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
