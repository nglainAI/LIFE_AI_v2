#!/bin/bash
# 🌸 Claire Life — Quick Start

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Цвета
PINK='\033[95m'
GREEN='\033[92m'
YELLOW='\033[93m'
RESET='\033[0m'

echo -e "${PINK}"
cat << 'EOF'
╔═══════════════════════════════════════════════════════════════╗
║                    🌸 Claire Life 🌸                            ║
╚═══════════════════════════════════════════════════════════════╝
EOF
echo -e "${RESET}"

# Проверка токена
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    # Пробуем загрузить из .env
    if [ -f ".env" ]; then
        source .env
    fi
fi

if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo -e "${YELLOW}⚠️  TELEGRAM_BOT_TOKEN не найден${RESET}"
    echo ""
    echo "Варианты:"
    echo "1. export TELEGRAM_BOT_TOKEN='токен' && ./start.sh"
    echo "2. Создайте .env файл с TELEGRAM_BOT_TOKEN=токен"
    echo ""
    exit 1
fi

# Проверка настройки
if [ ! -d "core/node_modules" ]; then
    echo -e "${YELLOW}📦 Первый запуск — настраиваю...${RESET}"
    ./setup.sh
fi

# Запуск
echo -e "${GREEN}✨ Запускаю Клэр...${RESET}"
echo ""
python3 life.py
