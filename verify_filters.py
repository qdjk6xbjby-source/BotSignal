import asyncio
import logging
from trading_bot import cot_fetcher, is_market_active, bot_state, get_signal, SYMBOLS

logging.basicConfig(level=logging.INFO)

async def verify():
    print("--- 1. Testing Session Filter ---")
    active, reason = is_market_active()
    print(f"Market Active: {active}, Reason: {reason}")

    print("\n--- 2. Testing COT Fetcher ---")
    await cot_fetcher.update_cot()
    print(f"COT Data Keys: {list(bot_state['cot_data'].keys())}")
    for symbol in ["EUR", "GBP", "JPY"]:
        if symbol in bot_state["cot_data"]:
            print(f"{symbol} Sentiment: {bot_state['cot_data'][symbol]['sentiment']}")

    print("\n--- 3. Testing get_signal (Dry Run for first 3 symbols) ---")
    for symbol in SYMBOLS[:3]:
        print(f"Analyzing {symbol}...")
        result = await get_signal(symbol)
        if result:
            print(f"Result for {symbol}: {result}")
        else:
            print(f"No signal for {symbol} (Filtered or Neutral)")

if __name__ == "__main__":
    asyncio.run(verify())
