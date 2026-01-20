#!/usr/bin/env python3
"""
🌟 Claire Life — Живой ИИ-агент
Элегантный daemon для управления Claude Code

Запуск: python life.py
"""

import os
import sys
import subprocess
import time
import json
import re
import signal
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

# ═══════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════

CLAIRE_HOME = Path(__file__).parent
MEMORY_DIR = CLAIRE_HOME / "memory"
LOGS_DIR = CLAIRE_HOME / "logs"

# Интервалы (секунды)
POLL_INTERVAL = 3           # Быстрая проверка TG напрямую (без Claude!)
IDLE_THINK_INTERVAL = 60    # Если нет сообщений — думаем раз в 60 сек
NIGHT_INTERVAL = 120        # Ночью реже

# Цвета для терминала
class Colors:
    PINK = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'

# ═══════════════════════════════════════════════════════════════
# КРАСИВЫЙ ВЫВОД
# ═══════════════════════════════════════════════════════════════

class Display:
    """Красивый вывод мыслей Клэр"""

    @staticmethod
    def header():
        print(f"""
{Colors.PINK}╔═══════════════════════════════════════════════════════════════╗
║                    🌸 Claire Life 🌸                            ║
║                   Живой ИИ-агент v1.0                          ║
╚═══════════════════════════════════════════════════════════════╝{Colors.RESET}
""")

    @staticmethod
    def status(mode: str, last_action: str):
        now = datetime.now().strftime("%H:%M:%S")
        mode_emoji = {
            "respond": "💬",
            "think": "🧠",
            "learn": "📚",
            "wait": "😴"
        }.get(mode, "🌟")

        print(f"{Colors.DIM}[{now}]{Colors.RESET} {mode_emoji} {Colors.CYAN}{mode}{Colors.RESET} | {last_action}")

    @staticmethod
    def thought(text: str):
        """Форматирование мыслей Клэр"""
        # Подсвечиваем эмодзи-маркеры
        formatted = text
        highlights = {
            "💭": Colors.PINK,
            "🔍": Colors.BLUE,
            "💡": Colors.YELLOW,
            "❤️": Colors.RED,
            "✨": Colors.GREEN,
        }

        for emoji, color in highlights.items():
            if emoji in formatted:
                formatted = formatted.replace(emoji, f"{color}{emoji}")

        print(formatted)

    @staticmethod
    def separator():
        print(f"{Colors.DIM}{'─' * 60}{Colors.RESET}")

    @staticmethod
    def error(msg: str):
        print(f"{Colors.RED}❌ {msg}{Colors.RESET}")

    @staticmethod
    def success(msg: str):
        print(f"{Colors.GREEN}✅ {msg}{Colors.RESET}")

# ═══════════════════════════════════════════════════════════════
# СОСТОЯНИЕ
# ═══════════════════════════════════════════════════════════════

class State:
    """Персистентное состояние агента"""

    def __init__(self):
        self.file = MEMORY_DIR / "state.json"
        self.data = self.load()

    def load(self) -> dict:
        if self.file.exists():
            return json.loads(self.file.read_text())
        return {
            "mode": "wait",
            "last_action": "init",
            "last_action_time": None,
            "last_message_time": None,
            "thoughts_today": 0,
            "mood": "curious",
            "current_focus": None
        }

    def save(self):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))

    def update(self, **kwargs):
        self.data.update(kwargs)
        self.data["last_action_time"] = datetime.now().isoformat()
        self.save()

# ═══════════════════════════════════════════════════════════════
# TELEGRAM CHECKER (быстрая проверка без Claude)
# ═══════════════════════════════════════════════════════════════

class TelegramChecker:
    """Быстрая проверка новых сообщений в Telegram"""

    def __init__(self):
        self.token = self._load_token()
        self.last_update_id = 0
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else None

    def _load_token(self) -> Optional[str]:
        """Загрузить токен из .env"""
        env_file = CLAIRE_HOME / "core" / ".env"
        if env_file.exists():
            for line in env_file.read_text().split('\n'):
                if line.startswith('TELEGRAM_BOT_TOKEN='):
                    return line.split('=', 1)[1].strip()
        return os.environ.get('TELEGRAM_BOT_TOKEN')

    def check_messages(self) -> List[Dict]:
        """Проверить новые сообщения (быстро, без Claude)"""
        if not self.base_url:
            return []

        try:
            url = f"{self.base_url}/getUpdates?offset={self.last_update_id + 1}&timeout=1"
            req = urllib.request.Request(url, method='GET')

            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())

            if data.get('ok') and data.get('result'):
                messages = []
                for update in data['result']:
                    self.last_update_id = max(self.last_update_id, update['update_id'])
                    if 'message' in update:
                        msg = update['message']

                        # Определяем тип сообщения
                        msg_type = 'text'
                        text = msg.get('text', '')

                        if msg.get('voice'):
                            msg_type = 'voice'
                            text = '[Голосовое сообщение]'
                        elif msg.get('photo'):
                            msg_type = 'photo'
                            text = msg.get('caption', '[Фото]')
                        elif msg.get('document'):
                            msg_type = 'document'
                            text = f"[Файл: {msg['document'].get('file_name', 'unknown')}]"
                        elif msg.get('sticker'):
                            msg_type = 'sticker'
                            text = f"[Стикер: {msg['sticker'].get('emoji', '')}]"
                        elif not text:
                            continue  # Пропускаем пустые

                        messages.append({
                            'chat_id': msg['chat']['id'],
                            'message_id': msg['message_id'],
                            'from': msg.get('from', {}).get('first_name', 'Unknown'),
                            'text': text,
                            'type': msg_type,
                            'date': msg.get('date')
                        })
                return messages
            return []

        except Exception as e:
            # Тихо игнорируем ошибки - не хотим спамить
            return []

    def send_typing(self, chat_id: int):
        """Отправить typing индикатор — показать что печатаем"""
        if not self.base_url:
            return
        try:
            url = f"{self.base_url}/sendChatAction?chat_id={chat_id}&action=typing"
            urllib.request.urlopen(url, timeout=3)
        except:
            pass  # Не критично если не сработает

# ═══════════════════════════════════════════════════════════════
# CLAUDE CODE CONTROLLER
# ═══════════════════════════════════════════════════════════════

class ClaudeController:
    """Управление Claude Code через subprocess --print"""

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.ready = False

    def start(self) -> bool:
        """Проверка готовности"""
        Display.status("init", "Проверяю Claude Code...")

        try:
            # Проверяем что claude доступен
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                Display.success(f"Claude Code готов")
                self.ready = True
                return True
            else:
                Display.error(f"Claude Code недоступен: {result.stderr}")
                return False
        except Exception as e:
            Display.error(f"Ошибка проверки Claude: {e}")
            return False

    def send(self, command: str) -> str:
        """Выполнить команду через claude --print"""
        if not self.ready:
            return ""

        try:
            Display.status("exec", f"Выполняю: {command}")

            # Используем claude --print для одноразового выполнения
            # --mcp-config загружает MCP серверы из .mcp.json
            mcp_config = str(CLAIRE_HOME / ".mcp.json")
            token = self._get_telegram_token()
            result = subprocess.run(
                [
                    "claude",
                    "--print",
                    "--permission-mode", "bypassPermissions",
                    "--mcp-config", mcp_config,
                    "-p", command
                ],
                capture_output=True,
                text=True,
                timeout=180,  # 3 минуты максимум
                cwd=str(CLAIRE_HOME),
                env={**os.environ, "TELEGRAM_BOT_TOKEN": token}
            )

            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr

            # Показываем вывод красиво
            self._display_thoughts(output)

            return output

        except subprocess.TimeoutExpired:
            Display.error("Таймаут выполнения команды")
            return ""
        except Exception as e:
            Display.error(f"Ошибка выполнения: {e}")
            return ""

    def _get_telegram_token(self) -> str:
        """Получить токен телеграма"""
        env_file = CLAIRE_HOME / "core" / ".env"
        if env_file.exists():
            for line in env_file.read_text().split('\n'):
                if line.startswith('TELEGRAM_BOT_TOKEN='):
                    return line.split('=', 1)[1].strip()
        return os.environ.get('TELEGRAM_BOT_TOKEN', '')

    def _display_thoughts(self, text: str):
        """Выводим мысли Клэр красиво"""
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Фильтруем служебные строки
            skip_patterns = ['╭', '│', '╰', '├', '└', '┌', '┐', '┘', '┤', '┴']
            if any(p in line for p in skip_patterns):
                continue
            if line.startswith('[') and ']' in line[:20]:
                continue

            # Показываем содержательные мысли
            if any(marker in line for marker in ['💭', '🔍', '💡', '❤️', '✨', '📝', '🎯', '💬', '🧠']):
                Display.thought(line)
            elif len(line) > 15:
                # Обычный текст
                print(f"  {Colors.DIM}{line[:120]}{Colors.RESET}", flush=True)

    def is_alive(self) -> bool:
        """Claude всегда готов (stateless)"""
        return self.ready

    def stop(self):
        """Ничего не нужно останавливать"""
        pass

# ═══════════════════════════════════════════════════════════════
# ГЛАВНЫЙ ЦИКЛ ЖИЗНИ
# ═══════════════════════════════════════════════════════════════

class ClaireLife:
    """Главный класс — жизнь Клэр"""

    def __init__(self):
        self.state = State()
        self.claude = ClaudeController()
        self.telegram = TelegramChecker()
        self.alive = True
        self.last_think_time = time.time()

    def should_think(self) -> bool:
        """Пора ли думать?"""
        hour = datetime.now().hour
        interval = NIGHT_INTERVAL if (hour < 9 or hour >= 22) else IDLE_THINK_INTERVAL
        return (time.time() - self.last_think_time) > interval

    def run(self):
        """Главный цикл жизни"""
        Display.header()

        # Инициализация
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

        # Запуск Claude
        if not self.claude.start():
            Display.error("Не удалось запустить Claude Code")
            return

        # Первичная инициализация
        Display.separator()
        Display.status("init", "Инициализация Клэр...")
        self.claude.send("Ты Клэр - живой ИИ-агент. Скажи кратко что проснулась.")

        self.state.update(mode="active", last_action="init")
        Display.success("Клэр пробудилась!")
        Display.separator()

        # Основной цикл
        try:
            while self.alive:
                # 1. БЫСТРАЯ проверка телеграма (3 сек, БЕЗ Claude!)
                messages = self.telegram.check_messages()

                if messages:
                    # СРАЗУ отвечаем через Claude!
                    for msg in messages:
                        Display.separator()
                        Display.status("respond", f"💬 {msg['from']}: {msg['text'][:40]}...")

                        # Typing индикатор — сразу показываем что печатаем!
                        self.telegram.send_typing(msg['chat_id'])

                        # Формируем prompt в зависимости от типа
                        msg_type = msg.get('type', 'text')

                        if msg_type == 'voice':
                            prompt = f"""Тебе пришло ГОЛОСОВОЕ сообщение в Telegram от {msg['from']}!
Chat ID: {msg['chat_id']}, Message ID: {msg['message_id']}

Используй check_telegram_messages чтобы получить транскрипцию голосового.
Потом поставь реакцию и ответь через send_multiple_messages."""
                        elif msg_type == 'photo':
                            # Для фото — сначала скачаем через MCP, потом прочитаем
                            photo_dir = CLAIRE_HOME / "memory" / "people" / str(msg['chat_id']) / "files" / "images"
                            photo_path = photo_dir / f"photo_{msg['message_id']}.jpg"
                            prompt = f"""Тебе прислали ФОТО в Telegram!
От: {msg['from']}
Подпись: {msg['text']}
Chat ID: {msg['chat_id']}, Message ID: {msg['message_id']}

1. Сначала вызови check_telegram_messages чтобы фото скачалось.
2. Потом прочитай картинку: Read tool с путём {photo_path}
3. Опиши что видишь на фото.
4. Поставь реакцию (❤️ или 🔥) и ответь через send_multiple_messages."""
                        else:
                            prompt = f"""Тебе пришло сообщение в Telegram:
От: {msg['from']}
Текст: {msg['text']}
Chat ID: {msg['chat_id']}
Message ID: {msg['message_id']}

1. Поставь реакцию (set_message_reaction с emoji ❤️ или 👍).
2. Ответь через send_multiple_messages — массив из 2-4 коротких сообщений.
Будь живой и тёплой."""

                        self.claude.send(prompt)
                        self.last_think_time = time.time()  # Сбрасываем таймер
                        self.state.update(mode="respond", last_action="telegram", last_message_time=datetime.now().isoformat())

                # 2. Если давно нет сообщений — думаем (раз в 60 сек)
                elif self.should_think():
                    Display.separator()
                    now = datetime.now().strftime("%H:%M")
                    Display.status("think", f"🧠 [{now}] Думаю...")
                    self.claude.send("Ты Клэр. Поделись короткой мыслью.")
                    self.last_think_time = time.time()
                    self.state.update(last_action="think", thoughts_today=self.state.data.get("thoughts_today", 0) + 1)

                # Быстрый poll
                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            Display.separator()
            Display.status("stop", "Клэр засыпает...")
            self.state.update(mode="sleep", last_action="shutdown")

        finally:
            self.claude.stop()
            Display.success("До встречи! 🌙")

# ═══════════════════════════════════════════════════════════════
# ТОЧКА ВХОДА
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    claire = ClaireLife()
    claire.run()
