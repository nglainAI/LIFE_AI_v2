#!/bin/bash
# 🌸 Claire Life — Setup Script

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "🌸 Claire Life — Настройка"
echo "═══════════════════════════════════════"

# Проверка токена
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "⚠️  TELEGRAM_BOT_TOKEN не установлен"
    echo ""
    echo "Создайте бота через @BotFather в Telegram и получите токен."
    echo "Затем выполните:"
    echo ""
    echo "  export TELEGRAM_BOT_TOKEN='ваш_токен'"
    echo "  ./setup.sh"
    echo ""
    exit 1
fi

echo "✅ Токен найден: ${TELEGRAM_BOT_TOKEN:0:10}..."

# Устанавливаем зависимости
echo ""
echo "📦 Устанавливаю зависимости..."
cd core && npm install --silent && cd ..

# Создаём структуру памяти
echo "🧠 Создаю структуру памяти..."
mkdir -p memory/people
mkdir -p memory/diary
mkdir -p memory/knowledge
mkdir -p logs

# Инициализируем файлы
cat > memory/state.json << 'EOF'
{
  "mode": "init",
  "last_action": null,
  "last_action_time": null,
  "mood": "curious",
  "current_focus": null
}
EOF

cat > memory/curiosity.json << 'EOF'
{
  "topics": [
    "природа сознания",
    "как люди принимают решения",
    "история искусственного интеллекта"
  ],
  "last_updated": null
}
EOF

# Добавляем MCP
echo "🔌 Настраиваю MCP telegram..."
claude mcp add telegram node "$SCRIPT_DIR/core/telegram.js" \
    --scope project \
    --env TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN" \
    --env MEMORY_DIR="$SCRIPT_DIR/memory"

echo ""
echo "═══════════════════════════════════════"
echo "✨ Настройка завершена!"
echo ""
echo "Запуск Клэр:"
echo "  python life.py"
echo ""
echo "Или в фоне:"
echo "  nohup python life.py > logs/claire.log 2>&1 &"
echo ""
