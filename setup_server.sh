#!/bin/bash

# Скрипт для быстрой настройки бота на Ubuntu/Debian сервере

echo "--- Настройка Trading Signal Bot ---"

# 1. Обновление системы
sudo apt update && sudo apt install -y python3-pip python3-venv

# 2. Создание виртуального окружения
python3 -m venv venv
source venv/bin/activate

# 3. Установка зависимостей
pip install -r requirements.txt

# 4. Создание сервиса для автозапуска (опционально)
echo "--- Установка завершена! ---"
echo "Чтобы запустить бота, введите:"
echo "source venv/bin/activate && python3 trading_bot.py"
