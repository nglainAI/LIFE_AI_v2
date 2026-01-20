#!/bin/bash
# Запуск Claire Life в интерактивном режиме

cd "$(dirname "$0")"

# Проверяем токен
if [ -f core/.env ]; then
    export $(grep -v '^#' core/.env | xargs)
fi

if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "❌ TELEGRAM_BOT_TOKEN не установлен!"
    echo "Создай файл core/.env с содержимым:"
    echo "TELEGRAM_BOT_TOKEN=твой_токен"
    exit 1
fi

echo "🌸 Запуск Claire Life..."
echo ""

# Запуск с цветным выводом
python3 life.py
