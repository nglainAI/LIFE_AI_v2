#!/usr/bin/env python3
"""
🚀 Terminal Autopilot — Автопилот для любых терминальных окон

Подключается к существующим окнам Terminal с Claude Code,
понимает контекст разговора и продолжает вести переписку автоматически.

Использование:
    python terminal_autopilot.py              # Показать окна и выбрать
    python terminal_autopilot.py --list       # Список окон
    python terminal_autopilot.py --attach ID  # Подключиться к окну
    python terminal_autopilot.py --goal "..." # Установить цель

Как работает:
1. Находит окна Terminal с Claude Code
2. Читает контекст разговора
3. Понимает текущий статус (idle/working/waiting)
4. Автоматически отправляет сообщения для достижения цели
"""

import subprocess
import time
import sys
import re
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass

# ═══════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════

CLAIRE_HOME = Path(__file__).parent
STATE_FILE = CLAIRE_HOME / "memory" / "autopilot_sessions.json"

# Интервалы
POLL_INTERVAL = 2  # Проверка статуса
THINK_TIMEOUT = 300  # Макс. время ожидания ответа Claude

# Цвета
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
# TERMINAL BRIDGE (из agent02, улучшенный)
# ═══════════════════════════════════════════════════════════════

class TerminalBridge:
    """Мост к окну Terminal через AppleScript"""

    def __init__(self, window_id: int = None):
        self.window_id = window_id

    @staticmethod
    def list_windows(max_windows: int = 30) -> List[Dict]:
        """Получить список окон Terminal"""
        script = f'''
        tell application "Terminal"
            set resultText to ""
            set winCount to count of windows
            if winCount > {max_windows} then
                set winCount to {max_windows}
            end if
            repeat with i from 1 to winCount
                try
                    set w to window i
                    set wName to name of w as text
                    set wID to id of w as text
                    set resultText to resultText & wID & "|" & wName & "\\n"
                end try
            end repeat
            return resultText
        end tell
        '''
        output = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True, text=True
        ).stdout.strip()

        windows = []
        for line in output.split('\n'):
            if '|' in line:
                parts = line.split('|', 1)
                name = parts[1] if len(parts) > 1 else ''
                # ✳ означает Claude Code сессию
                is_claude = '✳' in name or 'claude' in name.lower() or 'glm' in name.lower()
                windows.append({
                    'id': int(parts[0]),
                    'name': name,
                    'is_claude': is_claude
                })
        return windows

    @staticmethod
    def find_claude_windows() -> List[Dict]:
        """Найти окна с Claude Code"""
        windows = TerminalBridge.list_windows()
        return [w for w in windows if w['is_claude']]

    def activate(self) -> bool:
        """Активировать окно"""
        if not self.window_id:
            return False
        script = f'''
        tell application "Terminal"
            set frontmost of window id {self.window_id} to true
            activate
        end tell
        '''
        result = subprocess.run(['osascript', '-e', script], capture_output=True)
        return result.returncode == 0

    def read_content(self, tail_lines: int = 50, full_history: bool = False) -> str:
        """Прочитать содержимое окна"""
        if not self.window_id:
            return ""

        if full_history:
            # Cmd+A + Cmd+C — весь scrollback
            script = f'''
            tell application "Terminal"
                set frontmost of window id {self.window_id} to true
                delay 0.15
            end tell
            tell application "System Events"
                keystroke "a" using command down
                delay 0.1
                keystroke "c" using command down
                delay 0.1
                key code 53  -- Escape
            end tell
            '''
            subprocess.run(['osascript', '-e', script], capture_output=True)
            time.sleep(0.2)
            result = subprocess.run(['pbpaste'], capture_output=True, text=True)
            content = result.stdout
        else:
            # Только видимая часть (быстрее)
            script = f'''
            tell application "Terminal"
                set targetWin to window id {self.window_id}
                return contents of selected tab of targetWin
            end tell
            '''
            result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
            content = result.stdout

        if tail_lines:
            lines = content.split('\n')
            content = '\n'.join(lines[-tail_lines:])

        return content

    def get_status(self) -> Dict:
        """Получить статус Claude Code в окне"""
        if not self.window_id:
            return {"status": "error", "details": "No window", "is_busy": False}

        content = self.read_content(tail_lines=None, full_history=False)
        content_lower = content.lower()

        # Главный индикатор работы — "(esc to interrupt)"
        if 'esc to interrupt' in content_lower:
            if 'thought' in content_lower or 'thinking' in content_lower:
                return {"status": "thinking", "details": "Думает", "is_busy": True}
            else:
                return {"status": "working", "details": "Работает", "is_busy": True}

        # Ожидание подтверждения
        waiting_patterns = ['(y/n)', '(Y/n)', 'confirm', '[Y/n]', '[y/N]']
        for pattern in waiting_patterns:
            if pattern in content:
                return {"status": "waiting_confirm", "details": "Ожидает Y/N", "is_busy": False}

        # Проверяем промпт ввода
        lines = content.strip().split('\n')
        if lines:
            last_line = lines[-1].strip()
            if last_line.startswith('>') or '↵ send' in content:
                return {"status": "idle", "details": "Готов к вводу", "is_busy": False}

        return {"status": "idle", "details": "Завершил", "is_busy": False}

    def send_message(self, message: str, press_enter: bool = True) -> bool:
        """Отправить сообщение в окно"""
        if not self.window_id:
            return False

        # Экранируем кавычки
        escaped = message.replace('\\', '\\\\').replace('"', '\\"')

        script = f'''
        tell application "Terminal"
            set targetWin to window id {self.window_id}
            set targetTab to selected tab of targetWin
            do script "{escaped}" in targetTab
        end tell
        '''
        result = subprocess.run(['osascript', '-e', script], capture_output=True)

        if result.returncode != 0:
            return False

        if press_enter:
            time.sleep(0.2)
            enter_script = f'''
            tell application "Terminal"
                activate
                set frontmost of window id {self.window_id} to true
            end tell
            delay 0.3
            tell application "System Events"
                tell process "Terminal"
                    key code 36
                end tell
            end tell
            '''
            subprocess.run(['osascript', '-e', enter_script], capture_output=True)

        return True

    def get_last_exchanges(self, n: int = 5) -> List[Dict]:
        """Получить последние N обменов user→assistant"""
        # Используем contents вместо full_history для скорости
        content = self.read_content(tail_lines=200, full_history=False)

        exchanges = []
        current_user = None
        current_assistant = []

        # Служебные паттерны которые пропускаем
        skip_patterns = ['───', '💭', '/Users/', 'checkpoint', 'bypass',
                        '↵ send', '⎿', 'Thinking', 'Tinkering',
                        'ctrl+o', '⏵⏵', 'Claude Code', 'MCP', 'Ran Playwright',
                        'Image]', 'lines (ctrl']

        for line in content.split('\n'):
            stripped = line.strip()

            # Пропускаем пустые и служебные
            if not stripped:
                continue
            if any(p in stripped for p in skip_patterns):
                continue

            # Запрос пользователя (начинается с > или ⏵)
            if stripped.startswith('>') and '─' not in stripped:
                if current_user is not None and current_assistant:
                    exchanges.append({
                        "user": current_user,
                        "assistant": '\n'.join(current_assistant).strip()
                    })
                current_user = stripped[1:].replace('\xa0', ' ').strip()
                current_assistant = []
            # Ответ Claude (начинается с ⏺)
            elif stripped.startswith('⏺'):
                text = stripped[1:].strip()
                if text and current_user is not None:
                    current_assistant.append(text)
            # Продолжение ответа
            elif current_user is not None and current_assistant:
                # Добавляем только если это осмысленный текст
                if len(stripped) > 3 and not stripped.startswith('['):
                    current_assistant.append(stripped)

        # Добавляем последний обмен
        if current_user is not None and current_assistant:
            exchanges.append({
                "user": current_user,
                "assistant": '\n'.join(current_assistant).strip()
            })

        return exchanges[-n:] if n else exchanges

    def get_last_response(self) -> str:
        """Получить последний ответ Claude (быстро)"""
        content = self.read_content(tail_lines=50, full_history=False)
        lines = []

        for line in content.split('\n'):
            stripped = line.strip()
            if stripped.startswith('⏺'):
                text = stripped[1:].strip()
                if text:
                    lines.append(text)

        return '\n'.join(lines[-5:]) if lines else ""

    def wait_for_idle(self, timeout: float = THINK_TIMEOUT, poll: float = POLL_INTERVAL) -> bool:
        """Ждать пока Claude закончит работу"""
        start = time.time()
        while time.time() - start < timeout:
            status = self.get_status()
            if not status['is_busy']:
                return True
            time.sleep(poll)
        return False

# ═══════════════════════════════════════════════════════════════
# AUTOPILOT STATE
# ═══════════════════════════════════════════════════════════════

@dataclass
class AutopilotSession:
    """Сессия автопилота"""
    window_id: int
    goal: str
    started_at: str
    messages_sent: int = 0
    status: str = "active"

class AutopilotState:
    """Управление состоянием автопилота"""

    def __init__(self):
        self.sessions: Dict[int, AutopilotSession] = {}
        self.load()

    def load(self):
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                for wid, sess in data.items():
                    self.sessions[int(wid)] = AutopilotSession(**sess)
            except:
                pass

    def save(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {str(wid): {
            "window_id": s.window_id,
            "goal": s.goal,
            "started_at": s.started_at,
            "messages_sent": s.messages_sent,
            "status": s.status
        } for wid, s in self.sessions.items()}
        STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def start_session(self, window_id: int, goal: str) -> AutopilotSession:
        session = AutopilotSession(
            window_id=window_id,
            goal=goal,
            started_at=datetime.now().isoformat()
        )
        self.sessions[window_id] = session
        self.save()
        return session

    def get_session(self, window_id: int) -> Optional[AutopilotSession]:
        return self.sessions.get(window_id)

    def update_session(self, window_id: int, **kwargs):
        if window_id in self.sessions:
            for k, v in kwargs.items():
                setattr(self.sessions[window_id], k, v)
            self.save()

# ═══════════════════════════════════════════════════════════════
# AUTOPILOT CORE
# ═══════════════════════════════════════════════════════════════

class TerminalAutopilot:
    """Автопилот для терминальных окон с Claude"""

    def __init__(self):
        self.state = AutopilotState()
        self.bridge: Optional[TerminalBridge] = None
        self.session: Optional[AutopilotSession] = None

    def display_header(self):
        print(f"""
{Colors.CYAN}╔═══════════════════════════════════════════════════════════════╗
║            🚀 Terminal Autopilot 🚀                             ║
║         Автопилот для Claude Code сессий                        ║
╚═══════════════════════════════════════════════════════════════╝{Colors.RESET}
""")

    def list_windows(self):
        """Показать список окон Terminal"""
        windows = TerminalBridge.list_windows()
        claude_windows = [w for w in windows if w['is_claude']]

        print(f"\n{Colors.BOLD}Окна Terminal:{Colors.RESET}")
        for w in windows:
            icon = "🤖" if w['is_claude'] else "📝"
            session = self.state.get_session(w['id'])
            status = f" {Colors.GREEN}[autopilot: {session.goal[:20]}...]{Colors.RESET}" if session else ""
            print(f"  {icon} ID: {w['id']:5} | {w['name'][:50]}{status}")

        if claude_windows:
            print(f"\n{Colors.GREEN}Найдено {len(claude_windows)} окон с Claude Code{Colors.RESET}")
        else:
            print(f"\n{Colors.YELLOW}Claude Code окна не найдены{Colors.RESET}")

        return windows

    def attach(self, window_id: int) -> bool:
        """Подключиться к окну"""
        self.bridge = TerminalBridge(window_id)

        # Проверяем что окно существует
        status = self.bridge.get_status()
        if status['status'] == 'error':
            print(f"{Colors.RED}❌ Окно {window_id} не найдено{Colors.RESET}")
            return False

        print(f"{Colors.GREEN}✅ Подключено к окну {window_id}{Colors.RESET}")
        print(f"   Статус: {status['details']}")

        # Показываем контекст
        exchanges = self.bridge.get_last_exchanges(3)
        if exchanges:
            print(f"\n{Colors.CYAN}Последние сообщения:{Colors.RESET}")
            for ex in exchanges[-3:]:
                user_short = ex['user'][:50] + "..." if len(ex['user']) > 50 else ex['user']
                asst_short = ex['assistant'][:80] + "..." if len(ex['assistant']) > 80 else ex['assistant']
                print(f"  {Colors.BLUE}>{Colors.RESET} {user_short}")
                print(f"    {Colors.DIM}{asst_short}{Colors.RESET}")

        return True

    def set_goal(self, goal: str):
        """Установить цель для автопилота"""
        if not self.bridge:
            print(f"{Colors.RED}❌ Сначала подключитесь к окну (--attach ID){Colors.RESET}")
            return

        self.session = self.state.start_session(self.bridge.window_id, goal)
        print(f"{Colors.GREEN}✅ Цель установлена: {goal}{Colors.RESET}")

    def generate_next_message(self, context: str, goal: str, exchanges: List[Dict]) -> str:
        """Сгенерировать следующее сообщение для достижения цели"""
        # Формируем контекст для Claude (через текущую сессию)
        last_exchange = exchanges[-1] if exchanges else None

        if not last_exchange:
            # Первое сообщение — просто отправляем цель
            return goal

        last_response = last_exchange['assistant']

        # Простая логика продолжения:
        # - Если Claude спрашивает — отвечаем "да" / "продолжай"
        # - Если Claude завершил — спрашиваем что дальше
        # - Если ошибка — просим исправить

        response_lower = last_response.lower()

        if any(q in response_lower for q in ['?', 'хотите', 'нужно', 'можно']):
            return "да, продолжай"

        if any(w in response_lower for w in ['готово', 'выполнено', 'завершено', 'сделано']):
            return "отлично! что дальше по плану?"

        if any(w in response_lower for w in ['ошибка', 'error', 'failed', 'не удалось']):
            return "исправь ошибку и продолжай"

        # По умолчанию — просим продолжить
        return "продолжай"

    def run_loop(self):
        """Основной цикл автопилота"""
        if not self.bridge or not self.session:
            print(f"{Colors.RED}❌ Сначала подключитесь к окну и установите цель{Colors.RESET}")
            return

        print(f"\n{Colors.CYAN}═══ Автопилот запущен ═══{Colors.RESET}")
        print(f"Цель: {self.session.goal}")
        print(f"Окно: {self.bridge.window_id}")
        print(f"{Colors.DIM}Ctrl+C для остановки{Colors.RESET}\n")

        # Сначала отправляем цель если это новая сессия
        if self.session.messages_sent == 0:
            print(f"{Colors.BLUE}▸ Отправляю цель...{Colors.RESET}")
            self.bridge.send_message(self.session.goal)
            self.state.update_session(self.bridge.window_id, messages_sent=1)

        try:
            while True:
                # 1. Проверяем статус
                status = self.bridge.get_status()
                now = datetime.now().strftime("%H:%M:%S")

                # 2. Если Claude работает — ждём
                if status['is_busy']:
                    sys.stdout.write(f"\r{Colors.DIM}[{now}]{Colors.RESET} 🔄 {status['details']}...")
                    sys.stdout.flush()
                    time.sleep(POLL_INTERVAL)
                    continue

                # 3. Если ждёт подтверждения Y/N
                if status['status'] == 'waiting_confirm':
                    print(f"\n{Colors.YELLOW}⏳ Ожидает подтверждения, отправляю Y{Colors.RESET}")
                    self.bridge.send_message("y")
                    time.sleep(1)
                    continue

                # 4. Claude idle — читаем контекст
                sys.stdout.write(f"\r{Colors.DIM}[{now}]{Colors.RESET} ✅ {status['details']}")
                sys.stdout.flush()

                exchanges = self.bridge.get_last_exchanges(5)
                if not exchanges:
                    time.sleep(POLL_INTERVAL)
                    continue

                # 5. Анализируем последний ответ
                last = exchanges[-1]
                last_response = last['assistant'].lower()

                # Проверяем завершение
                if any(w in last_response for w in ['итог:', 'готово!', 'задача выполнена', 'всё сделано']):
                    print(f"\n\n{Colors.GREEN}🎉 Цель достигнута!{Colors.RESET}")
                    self.state.update_session(self.bridge.window_id, status="completed")
                    break

                # 6. Генерируем и отправляем следующее сообщение
                time.sleep(2)  # Пауза перед следующим сообщением

                next_msg = self.generate_next_message(
                    self.bridge.read_content(tail_lines=50),
                    self.session.goal,
                    exchanges
                )

                print(f"\n{Colors.BLUE}▸{Colors.RESET} {next_msg[:60]}...")
                self.bridge.send_message(next_msg)

                self.state.update_session(
                    self.bridge.window_id,
                    messages_sent=self.session.messages_sent + 1
                )

                # Ждём пока Claude начнёт работать
                time.sleep(1)

        except KeyboardInterrupt:
            print(f"\n\n{Colors.YELLOW}Автопилот остановлен{Colors.RESET}")
            self.state.update_session(self.bridge.window_id, status="paused")

    def interactive_mode(self):
        """Интерактивный режим выбора"""
        self.display_header()
        windows = self.list_windows()

        if not windows:
            print(f"{Colors.RED}Нет доступных окон Terminal{Colors.RESET}")
            return

        # Выбор окна
        claude_windows = [w for w in windows if w['is_claude']]
        if claude_windows:
            print(f"\n{Colors.BOLD}Выберите окно (или Enter для первого Claude):{Colors.RESET}")
            default_id = claude_windows[0]['id']
        else:
            print(f"\n{Colors.BOLD}Введите ID окна:{Colors.RESET}")
            default_id = windows[0]['id']

        try:
            choice = input(f"{Colors.DIM}>{Colors.RESET} ").strip()
            window_id = int(choice) if choice else default_id
        except ValueError:
            window_id = default_id

        if not self.attach(window_id):
            return

        # Проверяем есть ли активная сессия
        existing = self.state.get_session(window_id)
        if existing and existing.status == "active":
            print(f"\n{Colors.YELLOW}Найдена активная сессия:{Colors.RESET}")
            print(f"  Цель: {existing.goal}")
            print(f"  Сообщений: {existing.messages_sent}")
            resume = input(f"\nПродолжить? [Y/n]: ").strip().lower()
            if resume != 'n':
                self.session = existing
                self.run_loop()
                return

        # Новая цель
        print(f"\n{Colors.BOLD}Введите цель для автопилота:{Colors.RESET}")
        goal = input(f"{Colors.DIM}>{Colors.RESET} ").strip()

        if not goal:
            print(f"{Colors.RED}Цель не указана{Colors.RESET}")
            return

        self.set_goal(goal)
        self.run_loop()

# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Terminal Autopilot для Claude Code")
    parser.add_argument("--list", "-l", action="store_true", help="Показать окна Terminal")
    parser.add_argument("--attach", "-a", type=int, help="Подключиться к окну по ID")
    parser.add_argument("--goal", "-g", type=str, help="Установить цель")
    parser.add_argument("--status", "-s", action="store_true", help="Статус текущего окна")
    parser.add_argument("--context", "-c", action="store_true", help="Показать контекст разговора")
    args = parser.parse_args()

    autopilot = TerminalAutopilot()

    if args.list:
        autopilot.list_windows()
        return

    if args.attach:
        if not autopilot.attach(args.attach):
            return

        if args.status:
            status = autopilot.bridge.get_status()
            print(f"\n{Colors.BOLD}Статус:{Colors.RESET} {status['details']}")
            print(f"Busy: {status['is_busy']}")
            return

        if args.context:
            # Показываем последний ответ Claude
            last_response = autopilot.bridge.get_last_response()
            if last_response:
                print(f"\n{Colors.BOLD}Последний ответ Claude:{Colors.RESET}")
                for line in last_response.split('\n')[:10]:
                    print(f"  {Colors.DIM}{line[:80]}{Colors.RESET}")
            else:
                print(f"\n{Colors.YELLOW}Нет ответов в видимой части окна{Colors.RESET}")

            # Показываем обмены если есть
            exchanges = autopilot.bridge.get_last_exchanges(3)
            if exchanges:
                print(f"\n{Colors.BOLD}Обмены:{Colors.RESET}")
                for ex in exchanges:
                    print(f"\n{Colors.BLUE}User:{Colors.RESET} {ex['user'][:100]}")
                    print(f"{Colors.GREEN}Claude:{Colors.RESET} {ex['assistant'][:200]}...")
            return

        if args.goal:
            autopilot.set_goal(args.goal)
            autopilot.run_loop()
            return

        # Просто подключились — показываем статус
        return

    # Интерактивный режим
    autopilot.interactive_mode()


if __name__ == "__main__":
    main()
