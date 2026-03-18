import asyncio
from investiny import search_assets, technical_indicators

async def test():
    try:
        print("Testing search_assets...")
        results = search_assets(query="EUR/USD", limit=1)
        print(f"Results: {results}")
        
        if results:
            asset_id = results[0]["pairId"]
            print(f"Testing technical_indicators for {asset_id}...")
            analysis = technical_indicators(asset_id=asset_id, interval="5m")
            print(f"Summary: {analysis.get('summary')}")
    except Exception as e:
        print(f"Investiny failed with Pydantic 2.0: {e}")

if __name__ == "__main__":
    asyncio.run(test())
