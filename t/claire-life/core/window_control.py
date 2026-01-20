#!/usr/bin/env python3
"""
Window Control Module — Управление окнами macOS
Интеграция с Hammerspoon для работы с любыми приложениями
"""

import subprocess
import json
import time
import os
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from datetime import datetime


class WindowController:
    """Управление окнами через Hammerspoon IPC + AppleScript"""

    def __init__(self):
        self.screenshot_dir = Path(__file__).parent.parent / "memory" / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    # ═══════════════════════════════════════════════════════════════
    # HAMMERSPOON IPC
    # ═══════════════════════════════════════════════════════════════

    def _hs_command(self, lua_code: str) -> Optional[str]:
        """Выполнить Lua код через Hammerspoon IPC"""
        try:
            result = subprocess.run(
                ["hs", "-c", lua_code],
                capture_output=True,
                text=True,
                timeout=3
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except subprocess.TimeoutExpired:
            # Hammerspoon не отвечает — возможно не запущен
            return None
        except Exception as e:
            return None

    def _is_hammerspoon_running(self) -> bool:
        """Проверить запущен ли Hammerspoon"""
        try:
            result = subprocess.run(["pgrep", "-x", "Hammerspoon"], capture_output=True)
            return result.returncode == 0
        except:
            return False

    def get_all_windows(self) -> List[Dict]:
        """Получить список всех окон"""
        # Попробуем Hammerspoon
        if self._is_hammerspoon_running():
            result = self._hs_command("return getWindowsJSON()")
            if result:
                try:
                    return json.loads(result)
                except:
                    pass

        # Fallback через AppleScript
        return self._get_windows_applescript()

    def _get_windows_applescript(self) -> List[Dict]:
        """Получить список окон через AppleScript"""
        # Сначала получаем список видимых приложений
        apps_script = '''
        tell application "System Events"
            set procs to name of every application process whose visible is true
            set AppleScript's text item delimiters to ":::"
            return procs as text
        end tell
        '''
        apps_result = self._run_applescript(apps_script)
        if not apps_result:
            return []

        apps = [a.strip() for a in apps_result.split(":::") if a.strip()]
        windows = []
        idx = 0

        # Получаем окна для каждого приложения
        for app in apps[:20]:  # Лимит чтобы не зависнуть
            script = f'''
            tell application "System Events"
                try
                    tell process "{app}"
                        set winNames to name of every window
                        set AppleScript's text item delimiters to "|||"
                        return winNames as text
                    end tell
                on error
                    return ""
                end try
            end tell
            '''
            result = self._run_applescript(script)
            if result:
                for title in result.split("|||"):
                    title = title.strip()
                    if title:
                        idx += 1
                        windows.append({
                            "app": app,
                            "title": title,
                            "id": idx,
                            "spaceIndex": None,
                            "visible": True
                        })

        return windows

    def get_spaces_info(self) -> Dict:
        """Информация о рабочих столах"""
        result = self._hs_command("return getSpacesJSON()")
        if result:
            try:
                return json.loads(result)
            except:
                pass
        return {}

    def get_current_space(self) -> int:
        """Текущий рабочий стол (1-based)"""
        result = self._hs_command("return getFocusedSpaceIndex()")
        if result:
            try:
                return int(result)
            except:
                pass
        return 1

    def focus_window(self, window_id: int) -> bool:
        """Активировать окно по ID"""
        result = self._hs_command(f"return focusWindow({window_id})")
        if result:
            try:
                data = json.loads(result)
                return data.get("success", False)
            except:
                pass
        return False

    def move_window_to_space(self, window_id: int, space_index: int) -> bool:
        """Переместить окно на другой рабочий стол"""
        result = self._hs_command(f"return moveWindowToSpace({window_id}, {space_index})")
        if result:
            try:
                data = json.loads(result)
                return data.get("success", False)
            except:
                pass
        return False

    def go_to_space(self, space_index: int) -> bool:
        """Перейти на рабочий стол"""
        result = self._hs_command(f"return gotoSpace({space_index})")
        if result:
            try:
                data = json.loads(result)
                return data.get("success", False)
            except:
                pass
        return False

    # ═══════════════════════════════════════════════════════════════
    # APPLESCRIPT AUTOMATION
    # ═══════════════════════════════════════════════════════════════

    def _run_applescript(self, script: str) -> Optional[str]:
        """Выполнить AppleScript"""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception as e:
            print(f"AppleScript error: {e}")
            return None

    def get_frontmost_app(self) -> str:
        """Получить имя активного приложения"""
        script = '''
        tell application "System Events"
            return name of first application process whose frontmost is true
        end tell
        '''
        return self._run_applescript(script) or "unknown"

    def get_frontmost_window_title(self) -> str:
        """Получить заголовок активного окна"""
        script = '''
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            try
                return name of front window of frontApp
            on error
                return ""
            end try
        end tell
        '''
        return self._run_applescript(script) or ""

    def activate_app(self, app_name: str) -> bool:
        """Активировать приложение по имени"""
        script = f'tell application "{app_name}" to activate'
        result = self._run_applescript(script)
        return result is not None

    def launch_app(self, app_name: str) -> bool:
        """Запустить приложение"""
        script = f'''
        tell application "{app_name}"
            activate
        end tell
        '''
        return self._run_applescript(script) is not None

    def close_frontmost_window(self) -> bool:
        """Закрыть активное окно"""
        script = '''
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            try
                click button 1 of front window of frontApp
                return "closed"
            on error
                keystroke "w" using command down
                return "keystroke"
            end try
        end tell
        '''
        return self._run_applescript(script) is not None

    def minimize_frontmost_window(self) -> bool:
        """Свернуть активное окно"""
        script = '''
        tell application "System Events"
            keystroke "m" using command down
        end tell
        '''
        return self._run_applescript(script) is not None

    # ═══════════════════════════════════════════════════════════════
    # KEYBOARD & MOUSE
    # ═══════════════════════════════════════════════════════════════

    def type_text(self, text: str, delay: float = 0.05) -> bool:
        """Набрать текст (как будто с клавиатуры)"""
        # Экранируем специальные символы для AppleScript
        escaped = text.replace('\\', '\\\\').replace('"', '\\"')
        script = f'''
        tell application "System Events"
            keystroke "{escaped}"
        end tell
        '''
        return self._run_applescript(script) is not None

    def press_key(self, key: str, modifiers: List[str] = None) -> bool:
        """Нажать клавишу с модификаторами

        key: имя клавиши (return, tab, escape, space, delete, etc)
             или код клавиши (число)
        modifiers: list из "command", "control", "option", "shift"
        """
        mod_str = ""
        if modifiers:
            mod_str = " using {" + ", ".join(f"{m} down" for m in modifiers) + "}"

        # Специальные клавиши
        key_codes = {
            "return": 36, "enter": 36, "tab": 48, "escape": 53,
            "space": 49, "delete": 51, "backspace": 51,
            "up": 126, "down": 125, "left": 123, "right": 124,
            "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96,
            "home": 115, "end": 119, "pageup": 116, "pagedown": 121
        }

        if key.lower() in key_codes:
            code = key_codes[key.lower()]
            script = f'''
            tell application "System Events"
                key code {code}{mod_str}
            end tell
            '''
        else:
            script = f'''
            tell application "System Events"
                keystroke "{key}"{mod_str}
            end tell
            '''

        return self._run_applescript(script) is not None

    def click_at(self, x: int, y: int) -> bool:
        """Клик мышью по координатам"""
        script = f'''
        tell application "System Events"
            click at {{{x}, {y}}}
        end tell
        '''
        # Альтернативный метод через cliclick если установлен
        try:
            subprocess.run(["cliclick", f"c:{x},{y}"], timeout=2)
            return True
        except:
            return self._run_applescript(script) is not None

    def move_mouse(self, x: int, y: int) -> bool:
        """Переместить мышь"""
        try:
            subprocess.run(["cliclick", f"m:{x},{y}"], timeout=2)
            return True
        except:
            # Fallback через Hammerspoon
            self._hs_command(f"hs.mouse.absolutePosition({{x={x}, y={y}}})")
            return True

    def get_mouse_position(self) -> Tuple[int, int]:
        """Получить позицию мыши"""
        result = self._hs_command("local p = hs.mouse.absolutePosition(); return p.x .. ',' .. p.y")
        if result:
            try:
                x, y = result.split(",")
                return (int(float(x)), int(float(y)))
            except:
                pass
        return (0, 0)

    # ═══════════════════════════════════════════════════════════════
    # SCREENSHOTS
    # ═══════════════════════════════════════════════════════════════

    def take_screenshot(self, region: str = "screen") -> Optional[Path]:
        """Сделать скриншот

        region: "screen" - весь экран
                "window" - активное окно
                "x,y,w,h" - область
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = self.screenshot_dir / f"screen_{timestamp}.png"

        try:
            if region == "screen":
                subprocess.run(["screencapture", "-x", str(filename)], timeout=5)
            elif region == "window":
                subprocess.run(["screencapture", "-x", "-w", str(filename)], timeout=5)
            else:
                # Область x,y,w,h
                try:
                    x, y, w, h = map(int, region.split(","))
                    subprocess.run([
                        "screencapture", "-x", "-R", f"{x},{y},{w},{h}", str(filename)
                    ], timeout=5)
                except:
                    return None

            if filename.exists():
                return filename
        except Exception as e:
            print(f"Screenshot error: {e}")

        return None

    def take_window_screenshot(self, window_id: int = None) -> Optional[Path]:
        """Скриншот конкретного окна"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = self.screenshot_dir / f"window_{timestamp}.png"

        try:
            if window_id:
                # Сначала активируем окно
                self.focus_window(window_id)
                time.sleep(0.3)

            subprocess.run(["screencapture", "-x", "-w", str(filename)], timeout=10)

            if filename.exists():
                return filename
        except Exception as e:
            print(f"Window screenshot error: {e}")

        return None

    # ═══════════════════════════════════════════════════════════════
    # HIGH-LEVEL ACTIONS
    # ═══════════════════════════════════════════════════════════════

    def get_context(self) -> Dict:
        """Получить полный контекст текущего состояния"""
        return {
            "frontmost_app": self.get_frontmost_app(),
            "frontmost_window": self.get_frontmost_window_title(),
            "current_space": self.get_current_space(),
            "spaces_info": self.get_spaces_info(),
            "mouse_position": self.get_mouse_position(),
            "all_windows": self.get_all_windows()
        }

    def find_window(self, app_name: str = None, title_contains: str = None) -> Optional[Dict]:
        """Найти окно по приложению или заголовку"""
        windows = self.get_all_windows()

        for win in windows:
            if app_name and app_name.lower() not in win.get("app", "").lower():
                continue
            if title_contains and title_contains.lower() not in win.get("title", "").lower():
                continue
            return win

        return None

    def switch_to_app(self, app_name: str) -> bool:
        """Переключиться на приложение (найти и активировать)"""
        # Сначала ищем окно
        window = self.find_window(app_name=app_name)

        if window:
            # Если окно на другом рабочем столе — переходим туда
            space_idx = window.get("spaceIndex")
            if space_idx and space_idx != self.get_current_space():
                self.go_to_space(space_idx)
                time.sleep(0.3)

            # Активируем окно
            return self.focus_window(window["id"])
        else:
            # Пытаемся просто активировать приложение
            return self.activate_app(app_name)

    def arrange_windows(self, layout: str = "side-by-side") -> bool:
        """Расположить окна

        layout: "side-by-side" - два окна рядом
                "stack" - все в стопку
                "grid" - сетка
        """
        windows = self.get_all_windows()
        visible = [w for w in windows if w.get("visible") and not w.get("minimized")]

        if not visible:
            return False

        # Получаем размер экрана через Hammerspoon
        screen_result = self._hs_command("local s = hs.screen.mainScreen():frame(); return s.w .. ',' .. s.h")
        if not screen_result:
            return False

        try:
            screen_w, screen_h = map(int, screen_result.split(","))
        except:
            return False

        if layout == "side-by-side" and len(visible) >= 2:
            # Первые два окна рядом
            w1, w2 = visible[0], visible[1]
            half_w = screen_w // 2

            # Изменяем размер через Hammerspoon
            self._hs_command(f'''
                local w1 = hs.window.get({w1["id"]})
                local w2 = hs.window.get({w2["id"]})
                if w1 then w1:setFrame({{x=0, y=25, w={half_w}, h={screen_h-25}}}) end
                if w2 then w2:setFrame({{x={half_w}, y=25, w={half_w}, h={screen_h-25}}}) end
            ''')
            return True

        return False


# ═══════════════════════════════════════════════════════════════
# ТЕСТ
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    wc = WindowController()

    print("=== Window Controller Test ===\n")

    # Контекст
    ctx = wc.get_context()
    print(f"Active app: {ctx['frontmost_app']}")
    print(f"Window: {ctx['frontmost_window']}")
    print(f"Space: {ctx['current_space']}")
    print(f"Mouse: {ctx['mouse_position']}")
    print(f"Windows count: {len(ctx['all_windows'])}")

    # Список окон
    print("\n=== Windows ===")
    for w in ctx['all_windows'][:5]:
        print(f"  [{w.get('id')}] {w.get('app')}: {w.get('title', '')[:40]}")

    # Скриншот
    print("\n=== Screenshot ===")
    screenshot = wc.take_screenshot("screen")
    if screenshot:
        print(f"Saved: {screenshot}")
