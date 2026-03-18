from tradingview_ta import TA_Handler, Interval

handler = TA_Handler(
    symbol="EURUSD",
    screener="forex",
    exchange="FX_IDC",
    interval=Interval.INTERVAL_1_MINUTE
)

analysis = handler.get_analysis()
print("--- Indicators ---")
for key in sorted(analysis.indicators.keys()):
    # if "Pivot" in key or "R1" in key or "S1" in key:
    print(f"{key}: {analysis.indicators[key]}")

print("\n--- Summary ---")
print(analysis.summary)
