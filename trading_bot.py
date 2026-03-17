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

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Загрузка конфигурации
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Список разрешенных пользователей из .env
raw_allowed = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS = [int(u.strip()) for u in raw_allowed.split(",") if u.strip().isdigit()]

if not BOT_TOKEN:
    print("Ошибка: BOT_TOKEN не найден в .env!")
    exit(1)

# Настройка сессии с длинными таймаутами для стабильности (120 секунд)
session = AiohttpSession(
    timeout=ClientTimeout(total=120, connect=30, sock_read=30, sock_connect=30)
)
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
    "status_msg": "Запуск..."
}

async def get_signal(symbol):
    try:
        handler = TA_Handler(
            symbol=symbol,
            screener="forex",
            exchange="FX_IDC",
            interval=Interval.INTERVAL_1_MINUTE,
            timeout=10
        )
        # Используем asyncio.to_thread, чтобы синхронный запрос не блокировал весь бот
        analysis = await asyncio.to_thread(handler.get_analysis)
        summary = analysis.summary
        
        # summary содержит: {'RECOMMENDATION': 'STRONG_BUY', 'BUY': 20, 'SELL': 2, 'NEUTRAL': 4}
        rec = summary['RECOMMENDATION']
        
        if rec in ["STRONG_BUY", "STRONG_SELL"]:
            score = summary['BUY'] if rec == "STRONG_BUY" else summary['SELL']
            
            # В TV обычно 26 индикаторов в сумме
            confidence = int((score / 26) * 100)
            
            return {
                "symbol": symbol,
                "rec": rec,
                "confidence": confidence,
                "indicators": f"{score}/26"
            }
    except Exception as e:
        if "429" in str(e):
            logger.warning(f"Превышен лимит запросов (429) при анализе {symbol}. Нужно подождать.")
            return "RATE_LIMIT"
        logger.error(f"Ошибка при анализе {symbol}: {e}")
    return None

async def broadcast_signals():
    while True:
        bot_state["is_paused"] = False
        bot_state["status_msg"] = "Сканирование рынка..."
        bot_state["last_scan_time"] = datetime.now()
        bot_state["total_scans"] += 1
        
        for symbol in SYMBOLS:
            signal = await get_signal(symbol)
            
            if signal == "RATE_LIMIT":
                bot_state["is_paused"] = True
                bot_state["status_msg"] = "Пауза из-за лимитов TradingView (429)"
                logger.info("Пауза 5 минут из-за блокировки IP TradingView...")
                await asyncio.sleep(300)
                break
            
            if signal:
                rec_type = "📈 ВВЕРХ (BUY)" if signal['rec'] == "STRONG_BUY" else "📉 ВНИЗ (SELL)"
                signal_key = f"{symbol}_{signal['rec']}"
                
                # Отправляем только если сигнал новый (или прошло более 5 минут с последнего такого же)
                now = datetime.now()
                if signal_key not in last_signals or (now - last_signals[signal_key]).total_seconds() > 300:
                    last_signals[signal_key] = now
                    
                    message_text = (
                        f"🚀 **НОВЫЙ СИГНАЛ: {symbol}**\n\n"
                        f"⏱ Таймфрейм: **1М**\n"
                        f"🔔 Рекомендация: **{rec_type}**\n"
                        f"🎯 Уверенность: **{signal['confidence']}%** ({signal['indicators']})\n\n"
                        f"⏳ Экспирация: **1-2 минуты**\n"
                        f"🕒 Время: {now.strftime('%H:%M:%S')}"
                    )
                    
                    if ALLOWED_USERS:
                        for user_id in ALLOWED_USERS:
                            try:
                                await bot.send_message(
                                    chat_id=user_id,
                                    text=message_text,
                                    parse_mode=ParseMode.MARKDOWN
                                )
                                logger.info(f"Сигнал по {symbol} отправлен пользователю {user_id}")
                            except Exception as e:
                                logger.error(f"Не удалось отправить сообщение {user_id}: {e}")
                        bot_state["signals_sent"] += 1
            
            # Увеличиваем паузу до 2 секунд, чтобы не забанили
            await asyncio.sleep(2)
            
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
