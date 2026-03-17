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

# Попытка исправить кодировку в консоли Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Загрузка конфигурации (явно указываем путь к .env в папке скрипта)
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path)

BOT_TOKEN = os.getenv("BOT_TOKEN")
# Список разрешенных пользователей из .env
raw_allowed = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS = [int(u.strip()) for u in raw_allowed.split(",") if u.strip().isdigit()]

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
    "start_time": datetime.now(),
    "last_scan_time": None,
    "total_scans": 0,
    "signals_sent": 0,
    "is_paused": False,
    "status_msg": "Запуск...",
    "news_events": []  # Список важных новостей
}

class NewsFetcher:
    def __init__(self):
        self.url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
        self.last_update = None
        
    def fetch_news(self):
        try:
            logger.info("Обновление экономического календаря...")
            response = requests.get(self.url, timeout=15)
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
                self.last_update = datetime.now()
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
    now_utc = datetime.utcnow() # ForexFactory XML в UTC-4/5, это сложнее. 
    # Временный костыль: считаем относительно текущего времени сервера
    now = datetime.now() 
    
    for event in bot_state["news_events"]:
        if event["country"] in currencies:
            # Если новость в пределах 30 минут от текущего времени
            # ВНИМАНИЕ: Тут могут быть проблемы с часовыми поясами сервера
            diff = abs((event["dt"] - now).total_seconds()) / 60
            if diff < 30:
                return event["title"]
    return False

async def get_signal(symbol):
    try:
        # 0. Проверка новостей (НОВОЕ)
        news_title = is_news_time(symbol)
        if news_title:
            logger.info(f"Сигнал по {symbol} отменен: важная новость ({news_title})")
            return "NEWS_BLOCK"

        # 1. Анализ на 1М (локальный сигнал)
        handler_1m = TA_Handler(
            symbol=symbol,
            screener="forex",
            exchange="FX_IDC",
            interval=Interval.INTERVAL_1_MINUTE,
            timeout=10
        )
        analysis_1m = await asyncio.to_thread(handler_1m.get_analysis)
        sum_1m = analysis_1m.summary
        rec_1m = sum_1m['RECOMMENDATION']
        
        # Базовая проверка на силу сигнала 1М
        if rec_1m not in ["STRONG_BUY", "STRONG_SELL"]:
            return None
            
        score_1m = sum_1m['BUY'] if rec_1m == "STRONG_BUY" else sum_1m['SELL']
        conf_1m = int((score_1m / 26) * 100)
        
        if conf_1m < 62:
            return None

        # 2. Анализ на 5М (подтверждение тренда - MTF)
        handler_5m = TA_Handler(
            symbol=symbol,
            screener="forex",
            exchange="FX_IDC",
            interval=Interval.INTERVAL_5_MINUTE,
            timeout=10
        )
        analysis_5m = await asyncio.to_thread(handler_5m.get_analysis)
        sum_5m = analysis_5m.summary
        rec_5m = sum_5m['RECOMMENDATION']
        
        # Проверка соответствия трендов
        if rec_1m == "STRONG_BUY" and rec_5m not in ["BUY", "STRONG_BUY"]:
            return None
        if rec_1m == "STRONG_SELL" and rec_5m not in ["SELL", "STRONG_SELL"]:
            return None

        # 3. Фильтр по уровням Pivot Points (НОВОЕ)
        current_price = analysis_1m.indicators.get("close")
        # Берем классические Pivot Points
        r1 = analysis_1m.indicators.get("Pivot.M.Classic.R1")
        s1 = analysis_1m.indicators.get("Pivot.M.Classic.S1")
        
        # 5 пунктов для большинства пар (0.0005 для EURUSD, 0.05 для USDJPY)
        pip_value = 0.01 if "JPY" in symbol else 0.0001
        threshold = 5 * pip_value

        if rec_1m == "STRONG_BUY" and r1:
            if r1 - current_price < threshold:
                logger.info(f"Сигнал BUY {symbol} отменен: слишком близко к уровню R1")
                return None
        
        if rec_1m == "STRONG_SELL" and s1:
            if current_price - s1 < threshold:
                logger.info(f"Сигнал SELL {symbol} отменен: слишком близко к уровню S1")
                return None

        # 4. Дополнительные фильтры (RSI + ADX)
        rsi = analysis_1m.indicators.get("RSI")
        adx = analysis_1m.indicators.get("ADX")
        
        if rsi:
            if rec_1m == "STRONG_BUY" and rsi > 70:
                return None
            if rec_1m == "STRONG_SELL" and rsi < 30:
                return None
                
        if adx and adx < 20:
            return None

        return {
            "symbol": symbol,
            "rec": rec_1m,
            "confidence": conf_1m,
            "indicators": f"{score_1m}/26",
            "rsi": round(rsi, 2) if rsi else "N/A",
            "adx": round(adx, 2) if adx else "N/A"
        }

    except Exception as e:
        if "429" in str(e):
            logger.warning(f"Превышен лимит запросов (429) при анализе {symbol}. Нужно подождать.")
            return "RATE_LIMIT"
        logger.error(f"Ошибка при анализе {symbol}: {e}")
    return None

async def broadcast_signals():
    while True:
        # Обновляем новости при каждом сканировании (или раз в час)
        if news_fetcher.last_update is None or (datetime.now() - news_fetcher.last_update).total_seconds() > 3600:
            news_fetcher.fetch_news()

        bot_state["is_paused"] = False
        bot_state["status_msg"] = "Сканирование рынка..."
        bot_state["last_scan_time"] = datetime.now()
        bot_state["total_scans"] += 1
        
        # Собираем все сигналы за один цикл сканирования
        current_cycle_signals = []
        
        for symbol in SYMBOLS:
            signal = await get_signal(symbol)
            
            if signal == "RATE_LIMIT":
                bot_state["is_paused"] = True
                bot_state["status_msg"] = "Пауза из-за лимитов TradingView (429)"
                logger.info("Пауза 5 минут из-за блокировки IP TradingView...")
                await asyncio.sleep(300)
                break
            
            if signal == "NEWS_BLOCK":
                # Просто пропускаем эту пару из-за новостей
                continue
                
            if signal:
                current_cycle_signals.append(signal)
            
            # Пауза между запросами к символам
            await asyncio.sleep(2)
            
        # Теперь отправляем ВСЕ сигналы, которые прошли фильтры (по просьбе пользователя)
        if current_cycle_signals and not bot_state["is_paused"]:
            from datetime import timedelta
            
            for signal_data in current_cycle_signals:
                symbol = signal_data['symbol']
                rec_type = "📈 ВВЕРХ (BUY)" if signal_data['rec'] == "STRONG_BUY" else "📉 ВНИЗ (SELL)"
                signal_key = f"{symbol}_{signal_data['rec']}"
                
                # Коррекция времени: +3 часа для МСК
                now_local = datetime.now() + timedelta(hours=3)
                
                # Отправляем только если сигнал новый (или прошло более 5 минут)
                if signal_key not in last_signals or (datetime.now() - last_signals[signal_key]).total_seconds() > 300:
                    last_signals[signal_key] = datetime.now()
                    
                    message_text = (
                        f"🚀 **НОВЫЙ СИГНАЛ: {symbol}**\n\n"
                        f"⚠️ **ТОЛЬКО РЕАЛЬНЫЙ РЫНОК (НЕ OTC)**\n\n"
                        f"⏱ Таймфрейм: **1М + 5М (Подтверждено)**\n"
                        f"🔔 Рекомендация: **{rec_type}**\n"
                        f"🎯 Уверенность: **{signal_data['confidence']}%** ({signal_data['indicators']})\n"
                        f"📈 RSI: **{signal_data['rsi']}** | ADX: **{signal_data['adx']}**\n\n"
                        f"⏳ Экспирация: **1-2 минуты**\n"
                        f"🕒 Время (МСК): {now_local.strftime('%H:%M:%S')}"
                    )
                    
                    if ALLOWED_USERS:
                        for user_id in ALLOWED_USERS:
                            try:
                                await bot.send_message(
                                    chat_id=user_id,
                                    text=message_text,
                                    parse_mode=ParseMode.MARKDOWN
                                )
                                logger.info(f"Сигнал по {symbol} отправлен {user_id}")
                            except Exception as e:
                                logger.error(f"Ошибка отправки {user_id}: {e}")
                        bot_state["signals_sent"] += 1
            
        # Пауза перед следующим полным циклом увеличена до 60 секунд
        if not bot_state["is_paused"]:
            bot_state["status_msg"] = "Ожидание следующего цикла..."
            await asyncio.sleep(60)

@dp.message()
async def cmd_handler(message: types.Message):
    # Безопасность: проверяем, что пишет именно владелец
    if message.from_user.id not in ALLOWED_USERS:
        logger.warning(f"Попытка доступа от постороннего: {message.from_user.id}")
        return

    if message.text == "/status":
        uptime = datetime.now() - bot_state["start_time"]
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
            "Я анализирую рынок через TradingView (26 индикаторов) на таймфрейме 1 минута.\n\n"
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
