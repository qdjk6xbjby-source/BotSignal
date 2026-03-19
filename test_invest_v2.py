import asyncio
from investiny import search_assets

async def test():
    try:
        print("Testing search_assets...")
        results = search_assets(query="EUR/USD", limit=1)
        print(f"Results: {results}")
        
        if results:
            asset_id = results[0]["pairId"]
            print(f"Found Asset ID: {asset_id}")
            # Investiny v2.x может иметь другую структуру, 
            # для диагностики достаточно успешного поиска
    except Exception as e:
        print(f"Investiny test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test())
