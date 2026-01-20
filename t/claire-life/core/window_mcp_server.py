#!/usr/bin/env python3
"""
Window Control MCP Server — Claude может управлять окнами macOS
"""

import asyncio
import json
import sys
import os
from pathlib import Path
from typing import Any

# Добавляем путь к модулю
sys.path.insert(0, str(Path(__file__).parent))
from window_control import WindowController


class WindowMCPServer:
    """MCP Server для управления окнами"""

    def __init__(self):
        self.wc = WindowController()

    async def handle_request(self, request: dict) -> dict:
        """Обработка MCP запроса"""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")

        if method == "initialize":
            return self._response(request_id, {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "window-control", "version": "1.0.0"},
                "capabilities": {"tools": {}}
            })

        elif method == "tools/list":
            return self._response(request_id, {"tools": self._get_tools()})

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            result = await self._call_tool(tool_name, arguments)
            return self._response(request_id, {"content": [{"type": "text", "text": result}]})

        elif method == "notifications/initialized":
            return None  # Уведомление, не требует ответа

        return self._error(request_id, -32601, "Method not found")

    def _response(self, request_id: Any, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _error(self, request_id: Any, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def _get_tools(self) -> list:
        """Список доступных инструментов"""
        return [
            {
                "name": "get_screen_context",
                "description": "Получить полный контекст: активное приложение, окно, рабочий стол, все окна. Используй это чтобы понять что сейчас на экране.",
                "inputSchema": {"type": "object", "properties": {}}
            },
            {
                "name": "list_windows",
                "description": "Список всех открытых окон с информацией о приложениях и рабочих столах",
                "inputSchema": {"type": "object", "properties": {}}
            },
            {
                "name": "focus_window",
                "description": "Активировать окно по ID (переключиться на него)",
                "inputSchema": {
                    "type": "object",
                    "properties": {"window_id": {"type": "integer", "description": "ID окна"}},
                    "required": ["window_id"]
                }
            },
            {
                "name": "switch_to_app",
                "description": "Переключиться на приложение по имени. Найдёт окно и активирует его.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"app_name": {"type": "string", "description": "Имя приложения (Safari, Chrome, Terminal и т.д.)"}},
                    "required": ["app_name"]
                }
            },
            {
                "name": "launch_app",
                "description": "Запустить приложение",
                "inputSchema": {
                    "type": "object",
                    "properties": {"app_name": {"type": "string", "description": "Имя приложения"}},
                    "required": ["app_name"]
                }
            },
            {
                "name": "type_text",
                "description": "Набрать текст в активном окне (как с клавиатуры)",
                "inputSchema": {
                    "type": "object",
                    "properties": {"text": {"type": "string", "description": "Текст для ввода"}},
                    "required": ["text"]
                }
            },
            {
                "name": "press_key",
                "description": "Нажать клавишу. Для горячих клавиш используй modifiers.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Клавиша (return, tab, escape, space, a-z, 0-9, f1-f12)"},
                        "modifiers": {"type": "array", "items": {"type": "string"}, "description": "Модификаторы: command, control, option, shift"}
                    },
                    "required": ["key"]
                }
            },
            {
                "name": "click_at",
                "description": "Клик мышью по координатам экрана",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "X координата"},
                        "y": {"type": "integer", "description": "Y координата"}
                    },
                    "required": ["x", "y"]
                }
            },
            {
                "name": "take_screenshot",
                "description": "Сделать скриншот экрана или окна. Возвращает путь к файлу.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "region": {"type": "string", "description": "'screen' для всего экрана, 'window' для активного окна, или 'x,y,w,h' для области", "default": "screen"}
                    }
                }
            },
            {
                "name": "go_to_space",
                "description": "Перейти на рабочий стол по номеру (1, 2, 3...)",
                "inputSchema": {
                    "type": "object",
                    "properties": {"space_index": {"type": "integer", "description": "Номер рабочего стола (начиная с 1)"}},
                    "required": ["space_index"]
                }
            },
            {
                "name": "move_window_to_space",
                "description": "Переместить окно на другой рабочий стол",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "window_id": {"type": "integer", "description": "ID окна"},
                        "space_index": {"type": "integer", "description": "Номер рабочего стола"}
                    },
                    "required": ["window_id", "space_index"]
                }
            },
            {
                "name": "arrange_windows",
                "description": "Автоматически расположить окна",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "layout": {"type": "string", "description": "'side-by-side' - два окна рядом", "default": "side-by-side"}
                    }
                }
            },
            {
                "name": "close_window",
                "description": "Закрыть активное окно (Cmd+W)",
                "inputSchema": {"type": "object", "properties": {}}
            },
            {
                "name": "minimize_window",
                "description": "Свернуть активное окно (Cmd+M)",
                "inputSchema": {"type": "object", "properties": {}}
            }
        ]

    async def _call_tool(self, name: str, args: dict) -> str:
        """Вызов инструмента"""
        try:
            if name == "get_screen_context":
                ctx = self.wc.get_context()
                return json.dumps(ctx, indent=2, ensure_ascii=False)

            elif name == "list_windows":
                windows = self.wc.get_all_windows()
                formatted = []
                for w in windows:
                    formatted.append(f"[{w.get('id')}] {w.get('app')}: {w.get('title', '')[:50]} (Space {w.get('spaceIndex', '?')})")
                return "\n".join(formatted) if formatted else "Нет открытых окон"

            elif name == "focus_window":
                success = self.wc.focus_window(args["window_id"])
                return f"Окно активировано: {success}"

            elif name == "switch_to_app":
                success = self.wc.switch_to_app(args["app_name"])
                return f"Переключение на {args['app_name']}: {'успешно' if success else 'не найдено'}"

            elif name == "launch_app":
                success = self.wc.launch_app(args["app_name"])
                return f"Запуск {args['app_name']}: {'успешно' if success else 'ошибка'}"

            elif name == "type_text":
                success = self.wc.type_text(args["text"])
                return f"Текст введён: {success}"

            elif name == "press_key":
                modifiers = args.get("modifiers", [])
                success = self.wc.press_key(args["key"], modifiers)
                return f"Клавиша нажата: {success}"

            elif name == "click_at":
                success = self.wc.click_at(args["x"], args["y"])
                return f"Клик по ({args['x']}, {args['y']}): {success}"

            elif name == "take_screenshot":
                region = args.get("region", "screen")
                path = self.wc.take_screenshot(region)
                return f"Скриншот сохранён: {path}" if path else "Ошибка создания скриншота"

            elif name == "go_to_space":
                success = self.wc.go_to_space(args["space_index"])
                return f"Переход на рабочий стол {args['space_index']}: {success}"

            elif name == "move_window_to_space":
                success = self.wc.move_window_to_space(args["window_id"], args["space_index"])
                return f"Перемещение окна: {success}"

            elif name == "arrange_windows":
                layout = args.get("layout", "side-by-side")
                success = self.wc.arrange_windows(layout)
                return f"Расположение окон ({layout}): {success}"

            elif name == "close_window":
                success = self.wc.close_frontmost_window()
                return f"Окно закрыто: {success}"

            elif name == "minimize_window":
                success = self.wc.minimize_frontmost_window()
                return f"Окно свёрнуто: {success}"

            else:
                return f"Неизвестный инструмент: {name}"

        except Exception as e:
            return f"Ошибка: {str(e)}"

    async def run(self):
        """Запуск сервера"""
        while True:
            try:
                line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
                if not line:
                    break

                request = json.loads(line.strip())
                response = await self.handle_request(request)

                if response:
                    print(json.dumps(response), flush=True)

            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(json.dumps({
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32603, "message": str(e)}
                }), flush=True)


if __name__ == "__main__":
    server = WindowMCPServer()
    asyncio.run(server.run())
