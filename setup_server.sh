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

# 4. Чтобы бот работал 24/7, используйте systemd.
# Шаблон сервиса доступен в deployment_guide.md

echo "--- Установка завершена! ---"
echo "1. Настройте .env файл."
echo "2. Запустите бота для теста: source venv/bin/activate && python3 trading_bot.py"
echo "3. Настройте systemd для работы 24/7 (см. deployment_guide.md)."
