from tradingview_ta import Interval

print("Available intervals:")
for attr in dir(Interval):
    if not attr.startswith("__"):
        print(attr)
