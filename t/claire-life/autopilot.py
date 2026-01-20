#!/usr/bin/env python3
"""
🚀 Claire Autopilot — Автопилот для любых окон
Расширение базового life.py с управлением окнами

Функции:
- Мониторинг активного приложения
- Автоматизация действий в любых окнах
- Скриншоты и распознавание экрана
- Выполнение задач в разных приложениях

Запуск: python autopilot.py
"""

import os
import sys
import subprocess
import time
import json
import signal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent / "core"))
from window_control import WindowController

# ═══════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════

CLAIRE_HOME = Path(__file__).parent
MEMORY_DIR = CLAIRE_HOME / "memory"
LOGS_DIR = CLAIRE_HOME / "logs"

# Интервалы (секунды)
POLL_INTERVAL = 5           # Проверка состояния
CONTEXT_CHECK_INTERVAL = 30 # Проверка контекста экрана
IDLE_THINK_INTERVAL = 120   # Фоновые мысли

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
    """Красивый вывод"""

    @staticmethod
    def header():
        print(f"""
{Colors.CYAN}╔═══════════════════════════════════════════════════════════════╗
║               🚀 Claire Autopilot 🚀                            ║
║              Автопилот для любых окон v1.0                      ║
╚═══════════════════════════════════════════════════════════════╝{Colors.RESET}
""")

    @staticmethod
    def status(mode: str, last_action: str):
        now = datetime.now().strftime("%H:%M:%S")
        mode_emoji = {
            "watch": "👁️",
            "action": "⚡",
            "screenshot": "📸",
            "think": "🧠",
            "wait": "😴",
            "telegram": "💬"
        }.get(mode, "🌟")

        print(f"{Colors.DIM}[{now}]{Colors.RESET} {mode_emoji} {Colors.CYAN}{mode}{Colors.RESET} | {last_action}")

    @staticmethod
    def context(app: str, window: str, windows_count: int):
        """Показать текущий контекст"""
        print(f"{Colors.DIM}├── App: {Colors.RESET}{Colors.GREEN}{app}{Colors.RESET}")
        print(f"{Colors.DIM}├── Window: {Colors.RESET}{window[:50]}")
        print(f"{Colors.DIM}└── Total windows: {Colors.RESET}{windows_count}")

    @staticmethod
    def separator():
        print(f"{Colors.DIM}{'─' * 60}{Colors.RESET}")

    @staticmethod
    def error(msg: str):
        print(f"{Colors.RED}❌ {msg}{Colors.RESET}")

    @staticmethod
    def success(msg: str):
        print(f"{Colors.GREEN}✅ {msg}{Colors.RESET}")

    @staticmethod
    def action(msg: str):
        print(f"{Colors.YELLOW}⚡ {msg}{Colors.RESET}")

# ═══════════════════════════════════════════════════════════════
# СОСТОЯНИЕ
# ═══════════════════════════════════════════════════════════════

class AutopilotState:
    """Состояние автопилота"""

    def __init__(self):
        self.file = MEMORY_DIR / "autopilot_state.json"
        self.data = self.load()

    def load(self) -> dict:
        if self.file.exists():
            try:
                return json.loads(self.file.read_text())
            except:
                pass
        return {
            "mode": "watch",
            "last_action": "init",
            "last_action_time": None,
            "last_app": None,
            "last_window": None,
            "current_task": None,
            "task_queue": [],
            "autopilot_enabled": True
        }

    def save(self):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))

    def update(self, **kwargs):
        self.data.update(kwargs)
        self.data["last_action_time"] = datetime.now().isoformat()
        self.save()

# ═══════════════════════════════════════════════════════════════
# TASK QUEUE — Очередь задач
# ═══════════════════════════════════════════════════════════════

class TaskQueue:
    """Очередь задач для выполнения"""

    def __init__(self):
        self.file = MEMORY_DIR / "task_queue.json"
        self.tasks = self.load()

    def load(self) -> List[Dict]:
        if self.file.exists():
            try:
                return json.loads(self.file.read_text())
            except:
                pass
        return []

    def save(self):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(self.tasks, indent=2, ensure_ascii=False))

    def add(self, task: str, app: str = None, priority: int = 5) -> str:
        """Добавить задачу"""
        import uuid
        task_id = str(uuid.uuid4())[:8]
        self.tasks.append({
            "id": task_id,
            "task": task,
            "app": app,
            "priority": priority,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        })
        self.tasks.sort(key=lambda x: x.get("priority", 5))
        self.save()
        return task_id

    def get_next(self) -> Optional[Dict]:
        """Получить следующую задачу"""
        for task in self.tasks:
            if task["status"] == "pending":
                return task
        return None

    def mark_done(self, task_id: str):
        """Пометить задачу как выполненную"""
        for task in self.tasks:
            if task["id"] == task_id:
                task["status"] = "done"
                task["completed_at"] = datetime.now().isoformat()
                break
        self.save()

    def mark_failed(self, task_id: str, error: str):
        """Пометить задачу как failed"""
        for task in self.tasks:
            if task["id"] == task_id:
                task["status"] = "failed"
                task["error"] = error
                break
        self.save()

# ═══════════════════════════════════════════════════════════════
# CLAUDE CODE CONTROLLER
# ═══════════════════════════════════════════════════════════════

class ClaudeController:
    """Управление Claude Code"""

    def __init__(self):
        self.ready = False

    def start(self) -> bool:
        """Проверка готовности"""
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                self.ready = True
                return True
        except Exception as e:
            Display.error(f"Claude not available: {e}")
        return False

    def send(self, command: str) -> str:
        """Выполнить команду через claude --print"""
        if not self.ready:
            return ""

        try:
            mcp_config = str(CLAIRE_HOME / ".mcp.json")

            # Получаем токен телеграма
            env_file = CLAIRE_HOME / "core" / ".env"
            token = ""
            if env_file.exists():
                for line in env_file.read_text().split('\n'):
                    if line.startswith('TELEGRAM_BOT_TOKEN='):
                        token = line.split('=', 1)[1].strip()

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
                timeout=180,
                cwd=str(CLAIRE_HOME),
                env={**os.environ, "TELEGRAM_BOT_TOKEN": token}
            )

            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr

            return output

        except subprocess.TimeoutExpired:
            return "Timeout"
        except Exception as e:
            return f"Error: {e}"

# ═══════════════════════════════════════════════════════════════
# AUTOPILOT
# ═══════════════════════════════════════════════════════════════

class ClaireAutopilot:
    """Главный класс автопилота"""

    def __init__(self):
        self.state = AutopilotState()
        self.wc = WindowController()
        self.claude = ClaudeController()
        self.tasks = TaskQueue()
        self.alive = True
        self.last_context_check = 0
        self.last_think_time = time.time()
        self.last_app = None
        self.last_window = None

    def get_screen_context(self) -> Dict:
        """Получить контекст текущего экрана"""
        return {
            "app": self.wc.get_frontmost_app(),
            "window": self.wc.get_frontmost_window_title(),
            "windows": self.wc.get_all_windows(),
            "timestamp": datetime.now().isoformat()
        }

    def detect_context_change(self, ctx: Dict) -> bool:
        """Обнаружить смену контекста (переключение приложения/окна)"""
        app_changed = ctx["app"] != self.last_app
        window_changed = ctx["window"] != self.last_window

        self.last_app = ctx["app"]
        self.last_window = ctx["window"]

        return app_changed or window_changed

    def should_take_screenshot(self, ctx: Dict) -> bool:
        """Нужно ли делать скриншот?"""
        # Делаем скриншот при смене контекста или по таймеру
        return (time.time() - self.last_context_check) > CONTEXT_CHECK_INTERVAL

    def process_with_claude(self, prompt: str):
        """Отправить запрос в Claude и показать ответ"""
        Display.status("action", "Обрабатываю через Claude...")
        response = self.claude.send(prompt)

        # Парсим и показываем красиво
        lines = response.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Фильтруем служебные строки
            if any(p in line for p in ['╭', '│', '╰', '├', '└', '┌']):
                continue
            if len(line) > 10:
                print(f"  {Colors.DIM}{line[:100]}{Colors.RESET}")

    def execute_task(self, task: Dict):
        """Выполнить задачу"""
        Display.separator()
        Display.action(f"Выполняю задачу: {task['task'][:50]}...")

        # Если задача для конкретного приложения — переключаемся
        if task.get("app"):
            Display.status("action", f"Переключаюсь на {task['app']}")
            self.wc.switch_to_app(task["app"])
            time.sleep(0.5)

        # Получаем скриншот текущего состояния
        screenshot = self.wc.take_screenshot("screen")

        # Формируем промпт для Claude
        ctx = self.get_screen_context()
        prompt = f"""Выполни задачу: {task['task']}

Текущий контекст:
- Активное приложение: {ctx['app']}
- Окно: {ctx['window']}
- Скриншот: {screenshot}

У тебя есть инструменты window-control MCP:
- switch_to_app, launch_app — переключение между приложениями
- type_text — ввод текста
- press_key — нажатие клавиш (с модификаторами command, control, option, shift)
- click_at — клик мышью
- take_screenshot — сделать скриншот

Выполни задачу пошагово. Если нужно посмотреть на экран — сделай скриншот.
После выполнения сообщи результат."""

        self.process_with_claude(prompt)
        self.tasks.mark_done(task["id"])
        Display.success(f"Задача {task['id']} выполнена")

    def run(self):
        """Главный цикл"""
        Display.header()

        # Инициализация
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

        if not self.claude.start():
            Display.error("Claude Code не доступен")
            return

        Display.success("Claude Code готов")
        Display.separator()

        # Получаем начальный контекст
        ctx = self.get_screen_context()
        Display.status("watch", "Начинаю наблюдение за экраном")
        Display.context(ctx["app"], ctx["window"], len(ctx["windows"]))

        try:
            while self.alive:
                # ═══════════════════════════════════════
                # 1. Проверяем очередь задач
                # ═══════════════════════════════════════
                next_task = self.tasks.get_next()
                if next_task:
                    self.execute_task(next_task)
                    continue

                # ═══════════════════════════════════════
                # 2. Мониторинг контекста
                # ═══════════════════════════════════════
                ctx = self.get_screen_context()

                if self.detect_context_change(ctx):
                    Display.separator()
                    Display.status("watch", f"Контекст изменился")
                    Display.context(ctx["app"], ctx["window"], len(ctx["windows"]))

                    # Можно отправить в Claude для анализа
                    self.state.update(
                        last_app=ctx["app"],
                        last_window=ctx["window"]
                    )

                # ═══════════════════════════════════════
                # 3. Периодические скриншоты
                # ═══════════════════════════════════════
                if self.should_take_screenshot(ctx):
                    self.last_context_check = time.time()
                    # Скриншот делаем только если включён режим анализа
                    # screenshot = self.wc.take_screenshot("screen")
                    # Display.status("screenshot", f"Скриншот: {screenshot}")

                # ═══════════════════════════════════════
                # 4. Фоновые мысли (редко)
                # ═══════════════════════════════════════
                if (time.time() - self.last_think_time) > IDLE_THINK_INTERVAL:
                    self.last_think_time = time.time()
                    Display.separator()
                    Display.status("think", "Размышляю...")
                    self.process_with_claude(f"""Ты Клэр — живой ИИ-агент.
Текущий контекст пользователя:
- Приложение: {ctx['app']}
- Окно: {ctx['window']}

Поделись короткой мыслью (1-2 предложения) о том, чем занят пользователь или что интересного видишь.""")

                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            Display.separator()
            Display.status("stop", "Останавливаю автопилот...")
            self.state.update(mode="stopped")

        Display.success("Автопилот остановлен. До встречи! 🌙")

# ═══════════════════════════════════════════════════════════════
# CLI ИНТЕРФЕЙС
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Claire Autopilot")
    parser.add_argument("--add-task", "-t", help="Добавить задачу")
    parser.add_argument("--app", "-a", help="Приложение для задачи")
    parser.add_argument("--list-tasks", "-l", action="store_true", help="Показать задачи")
    parser.add_argument("--context", "-c", action="store_true", help="Показать текущий контекст")
    parser.add_argument("--screenshot", "-s", action="store_true", help="Сделать скриншот")
    args = parser.parse_args()

    wc = WindowController()
    tasks = TaskQueue()

    if args.add_task:
        task_id = tasks.add(args.add_task, app=args.app)
        print(f"✅ Задача добавлена: {task_id}")
        return

    if args.list_tasks:
        print("📋 Очередь задач:")
        for t in tasks.tasks:
            status = "✅" if t["status"] == "done" else "⏳" if t["status"] == "pending" else "❌"
            print(f"  {status} [{t['id']}] {t['task'][:50]}")
        return

    if args.context:
        ctx = wc.get_context()
        print(f"🖥️ Контекст:")
        print(f"  App: {ctx['frontmost_app']}")
        print(f"  Window: {ctx['frontmost_window']}")
        print(f"  Windows: {len(ctx['all_windows'])}")
        return

    if args.screenshot:
        path = wc.take_screenshot("screen")
        print(f"📸 Скриншот: {path}")
        return

    # Запуск основного цикла
    autopilot = ClaireAutopilot()
    autopilot.run()


if __name__ == "__main__":
    main()
