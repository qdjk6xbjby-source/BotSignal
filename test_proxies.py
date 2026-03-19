import requests
import os

proxies_file = r'C:\Users\it-sp\.gemini\antigravity\scratch\trading_signal_bot\proxies.txt'

def test_proxy(proxy_str):
    elements = proxy_str.split(':')
    if len(elements) == 4:
        ip, port, user, pw = elements
        proxy_http = f"http://{user}:{pw}@{ip}:{port}"
        proxy_socks = f"socks5://{user}:{pw}@{ip}:{port}"
    elif len(elements) == 2:
        ip, port = elements
        proxy_http = f"http://{ip}:{port}"
        proxy_socks = f"socks5://{ip}:{port}"
    else:
        return f"ОШИБКА: Неверный формат: {proxy_str}"

    results = []
    # Тест HTTP
    try:
        r = requests.get("http://api.ipify.org?format=json", proxies={"http": proxy_http, "https": proxy_http}, timeout=15)
        if r.status_code == 200:
            results.append(f"HTTP: OK ({r.json()['ip']})")
        else:
            results.append(f"HTTP: FAIL ({r.status_code})")
    except Exception as e:
        results.append(f"HTTP: TIMEOUT/ERR")

    # Тест SOCKS5
    try:
        r = requests.get("http://api.ipify.org?format=json", proxies={"http": proxy_socks, "https": proxy_socks}, timeout=15)
        if r.status_code == 200:
            results.append(f"SOCKS5: OK ({r.json()['ip']})")
        else:
            results.append(f"SOCKS5: FAIL ({r.status_code})")
    except Exception as e:
        results.append(f"SOCKS5: TIMEOUT/ERR")

    return " | ".join(results)

if os.path.exists(proxies_file):
    print("--- ТЕСТ ПРОКСИ ---")
    with open(proxies_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            res = test_proxy(line)
            print(f"Проверка {line.split(':')[0]}... {res}")
else:
    print(f"Файл {proxies_file} не найден!")
