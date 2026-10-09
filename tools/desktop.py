"""
Nova Desktop Tool
─────────────────
Real OS control: open/close apps, mouse, keyboard, screenshots.

Requires:
    pip install pyautogui pillow

Actions:
    screenshot      → take a screenshot and save it, return path
    click           → click at (x, y) or on a found image
    move            → move mouse to (x, y)
    type            → type text
    key             → press a key or combo (e.g. ctrl+c)
    scroll          → scroll up/down at position
    open_app        → open an application by name/path
    close_app       → close a window by title
    get_windows     → list open windows
    focus_window    → bring a window to front by title
    find_on_screen  → find image/text on screen, return coordinates

All actions that interact with the screen first take a screenshot
so Nova can verify what happened.
"""

import json
import os
import re
import subprocess
import sys
import time


def _import_pyautogui():
    try:
        import pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE    = 0.3
        return pyautogui, None
    except ImportError:
        return None, (
            "pyautogui is not installed.\n"
            "Run this command to install it:\n"
            "  pip install pyautogui pillow\n"
            "Then restart Nova."
        )


def _import_pil():
    try:
        from PIL import Image
        return Image
    except ImportError:
        return None


class DesktopTool:

    SCREENSHOTS_DIR = os.path.join(
        os.path.expanduser("~"), ".nova", "screenshots"
    )

    def __init__(self):
        os.makedirs(self.SCREENSHOTS_DIR, exist_ok=True)

    # ── Input parser ──────────────────────────────────────────────────────────

    def _parse(self, input_data):
        if isinstance(input_data, dict):
            return input_data
        if isinstance(input_data, str):
            try:
                data = json.loads(input_data.strip())
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
        return {}

    # ── Screenshot helper ─────────────────────────────────────────────────────

    def _screenshot(self, label="action"):
        pyautogui, err = _import_pyautogui()
        if not pyautogui:
            return None, err

        ts   = int(time.time() * 1000)  # milliseconds for uniqueness
        path = os.path.join(
            self.SCREENSHOTS_DIR,
            f"nova_{label}_{ts}.png"
        )

        try:
            img = pyautogui.screenshot()
            img.save(path)
            return path, None
        except Exception as e:
            return None, str(e)

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self, input_data):
        """
        Main entry. Input JSON must have "action" field.

        Actions and their extra fields:

        screenshot:
            {} → takes screenshot, returns path

        click:
            {"x": 100, "y": 200}
            {"x": 100, "y": 200, "button": "left"|"right"|"middle"}
            {"x": 100, "y": 200, "clicks": 2}   ← double click

        move:
            {"x": 100, "y": 200}
            {"x": 100, "y": 200, "duration": 0.5}

        type:
            {"text": "hello world"}
            {"text": "hello", "interval": 0.05}

        key:
            {"key": "enter"}
            {"key": "ctrl+c"}
            {"key": "ctrl+shift+t"}

        scroll:
            {"x": 100, "y": 200, "amount": 3}   ← positive=up, negative=down

        open_app:
            {"app": "firefox"}
            {"app": "/usr/bin/gedit"}
            {"app": "notepad"}   ← Windows

        close_app:
            {"title": "Firefox"}   ← partial match

        get_windows:
            {}

        focus_window:
            {"title": "Firefox"}   ← partial match

        find_on_screen:
            {"image": "/path/to/template.png"}
            {"text": "Submit"}   ← OCR (requires pytesseract)
        """
        data   = self._parse(input_data)
        action = str(data.get("action", "")).strip().lower()

        if not action:
            return "DESKTOP ERROR: 'action' is required."

        dispatch = {
            "screenshot":    self._action_screenshot,
            "click":         self._action_click,
            "move":          self._action_move,
            "type":          self._action_type,
            "key":           self._action_key,
            "scroll":        self._action_scroll,
            "open_app":      self._action_open_app,
            "close_app":     self._action_close_app,
            "get_windows":   self._action_get_windows,
            "focus_window":  self._action_focus_window,
            "find_on_screen":self._action_find_on_screen,
        }

        fn = dispatch.get(action)
        if fn is None:
            return (
                f"DESKTOP ERROR: Unknown action '{action}'.\n"
                "Supported: screenshot, click, move, type, key, scroll, "
                "open_app, close_app, get_windows, focus_window, find_on_screen"
            )

        try:
            return fn(data)
        except Exception as e:
            return f"DESKTOP ERROR: {type(e).__name__}: {e}"

    # ── Actions ───────────────────────────────────────────────────────────────

    def _action_screenshot(self, data):
        path, err = self._screenshot("manual")
        if err:
            return f"DESKTOP ERROR: Screenshot failed: {err}"
        size = os.path.getsize(path)
        return (
            f"STATUS: SUCCESS\n"
            f"Screenshot saved: {path}\n"
            f"Size: {size:,} bytes"
        )

    def _action_click(self, data):
        pyautogui, err = _import_pyautogui()
        if not pyautogui:
            return f"DESKTOP ERROR: {err}"

        x       = data.get("x")
        y       = data.get("y")
        button  = data.get("button", "left")
        clicks  = int(data.get("clicks", 1))

        if x is None or y is None:
            return "DESKTOP ERROR: click requires 'x' and 'y' coordinates."

        x, y = int(x), int(y)

        # Validate coordinates are within screen bounds
        screen_w, screen_h = pyautogui.size()
        if x < 0 or x >= screen_w or y < 0 or y >= screen_h:
            return (
                f"DESKTOP ERROR: coordinates ({x}, {y}) are outside screen bounds "
                f"(screen size: {screen_w}x{screen_h})."
            )

        if button not in {"left", "right", "middle"}:
            button = "left"

        pyautogui.click(x=x, y=y, button=button, clicks=clicks)

        # Screenshot after action for verification
        time.sleep(0.3)
        path, _ = self._screenshot("after_click")

        result = (
            f"STATUS: SUCCESS\n"
            f"Clicked: ({x}, {y}) button={button} clicks={clicks}"
        )
        if path:
            result += f"\nScreenshot: {path}"
        return result

    def _action_move(self, data):
        pyautogui, err = _import_pyautogui()
        if not pyautogui:
            return f"DESKTOP ERROR: {err}"

        x        = data.get("x")
        y        = data.get("y")
        duration = float(data.get("duration", 0.3))

        if x is None or y is None:
            return "DESKTOP ERROR: move requires 'x' and 'y'."

        x, y = int(x), int(y)

        # Validate coordinates are within screen bounds
        screen_w, screen_h = pyautogui.size()
        if x < 0 or x >= screen_w or y < 0 or y >= screen_h:
            return (
                f"DESKTOP ERROR: coordinates ({x}, {y}) are outside screen bounds "
                f"(screen size: {screen_w}x{screen_h})."
            )

        pyautogui.moveTo(x, y, duration=duration)
        actual_x, actual_y = pyautogui.position()

        status = "SUCCESS" if (
            int(actual_x) == int(x)
            and int(actual_y) == int(y)
        ) else "ERROR"

        return (
            f"STATUS: {status}\n"
            f"Mouse moved to: ({actual_x}, {actual_y})\n"
            f"Requested position: ({int(x)}, {int(y)})"
        )

    def _action_type(self, data):
        pyautogui, err = _import_pyautogui()
        if not pyautogui:
            return f"DESKTOP ERROR: {err}"

        text     = data.get("text", "")
        interval = float(data.get("interval", 0.03))

        if not isinstance(text, str) or not text:
            return "DESKTOP ERROR: type requires 'text'."

        # Limit text length to 10000 characters
        if len(text) > 10000:
            return "DESKTOP ERROR: text exceeds maximum length of 10,000 characters."

        pyautogui.typewrite(text, interval=interval)
        time.sleep(0.2)
        screenshot_path, _ = self._screenshot("after_type")

        result = (
            f"STATUS: SUCCESS\n"
            f"Typed: {text[:80]!r}"
        )
        if screenshot_path:
            result += f"\nScreenshot: {screenshot_path}"
        return result

    def _action_key(self, data):
        pyautogui, err = _import_pyautogui()
        if not pyautogui:
            return f"DESKTOP ERROR: {err}"

        key = str(data.get("key", "")).strip()

        if not key:
            return "DESKTOP ERROR: key requires 'key' field."

        # Block dangerous key combinations
        dangerous_combos = [
            "ctrl+alt+delete",
            "ctrl+alt+del",
            "ctrl+shift+esc",
            "ctrl+alt+f4",
            "alt+f4",
        ]
        key_lower = key.lower().replace(" ", "")
        for combo in dangerous_combos:
            if combo in key_lower:
                return f"DESKTOP ERROR: dangerous key combination '{key}' is blocked."

        # Support combos like "ctrl+c", "ctrl+shift+t"
        if "+" in key:
            parts = [k.strip() for k in key.split("+")]
            pyautogui.hotkey(*parts)
        else:
            pyautogui.press(key)

        time.sleep(0.2)
        screenshot_path, _ = self._screenshot("after_key")

        result = (
            f"STATUS: SUCCESS\n"
            f"Key pressed: {key}"
        )
        if screenshot_path:
            result += f"\nScreenshot: {screenshot_path}"
        return result

    def _action_scroll(self, data):
        pyautogui, err = _import_pyautogui()
        if not pyautogui:
            return f"DESKTOP ERROR: {err}"

        x      = data.get("x", None)
        y      = data.get("y", None)
        amount = int(data.get("amount", 3))

        if x is not None and y is not None:
            pyautogui.scroll(amount, x=int(x), y=int(y))
        else:
            pyautogui.scroll(amount)

        direction = "up" if amount > 0 else "down"
        time.sleep(0.2)
        screenshot_path, _ = self._screenshot("after_scroll")

        result = (
            f"STATUS: SUCCESS\n"
            f"Scrolled {direction} by {abs(amount)} clicks"
        )
        if screenshot_path:
            result += f"\nScreenshot: {screenshot_path}"
        return result

    def _get_windows_start_apps(self):
        script = r"""
Get-StartApps | Select-Object Name, AppID | ForEach-Object {
    "$($_.Name)|||$($_.AppID)"
}
"""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return []

        apps = []
        for line in result.stdout.splitlines():
            parts = line.strip().split("|||", 1)
            if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                apps.append((parts[0].strip(), parts[1].strip()))
        return apps

    def _resolve_windows_app(self, app):
        """Resolve an installed Windows application without hardcoded names."""
        import difflib
        import shutil

        candidate = str(app or "").strip()
        if not candidate:
            return None, None, "Application name is required."

        if os.path.isfile(candidate):
            return candidate, candidate, None

        command_path = shutil.which(candidate)
        if command_path:
            return candidate, command_path, None

        apps = self._get_windows_start_apps()
        target = re.sub(r"\s+", " ", candidate).strip().casefold()
        exact_matches = []
        partial_matches = []

        for name, app_id in apps:
            normalized = re.sub(r"\s+", " ", name).strip().casefold()
            if normalized == target:
                exact_matches.append((name, app_id))
            elif target in normalized or normalized in target:
                partial_matches.append((name, app_id))

        if len(exact_matches) == 1:
            return exact_matches[0][0], exact_matches[0][1], None

        matches = exact_matches or partial_matches
        if len(matches) == 1:
            return matches[0][0], matches[0][1], None

        if len(matches) > 1:
            names = ", ".join(name for name, _ in matches[:8])
            suffix = " ..." if len(matches) > 8 else ""
            return None, None, (
                f"Multiple installed applications match '{candidate}': "
                f"{names}{suffix}. Please specify the application more precisely."
            )

        all_names = [name for name, _ in apps]
        suggestions = difflib.get_close_matches(
            candidate, all_names, n=3, cutoff=0.55
        )
        if suggestions:
            joined = ", ".join(suggestions)
            return None, None, (
                f"No installed application matches '{candidate}'. "
                f"Possible matches: {joined}"
            )

        return None, None, f"No installed application matches '{candidate}'."

    def _action_open_app(self, data):
        app = str(data.get("app", "")).strip()
        if not app:
            return "DESKTOP ERROR: open_app requires 'app'."

        is_windows = sys.platform.startswith("win")
        is_mac = sys.platform == "darwin"

        try:
            if is_windows:
                resolved_name, target, error = self._resolve_windows_app(app)
                if error:
                    return f"STATUS: ERROR\n{error}"

                if os.path.isfile(str(target)):
                    subprocess.Popen(
                        [str(target)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                elif target:
                    subprocess.Popen(
                        ["explorer.exe", f"shell:AppsFolder\\{target}"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    return f"STATUS: ERROR\nCould not resolve '{app}'."

            elif is_mac:
                result = subprocess.run(
                    ["open", "-a", app],
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    message = result.stderr.strip() or f"No application named '{app}' was found."
                    return f"STATUS: ERROR\n{message}"
                resolved_name = app

            else:
                import shutil
                command = shutil.which(app)
                if not command:
                    return f"STATUS: ERROR\nNo executable named '{app}' was found on PATH."
                subprocess.Popen(
                    [command],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                resolved_name = app

            time.sleep(1.5)
            path, screenshot_error = self._screenshot("after_open_app")

            result = "STATUS: SUCCESS\nOpened: " + str(resolved_name or app)
            if path:
                result += f"\nScreenshot: {path}"
            elif screenshot_error:
                result += f"\nScreenshot unavailable: {screenshot_error}"
            return result

        except Exception as e:
            return f"STATUS: ERROR\nFailed to open '{app}': {type(e).__name__}: {e}"

    def _action_close_app(self, data):
        title = str(data.get("title", "")).strip()
        if not title:
            return "DESKTOP ERROR: close_app requires 'title'."

        is_windows = sys.platform.startswith("win")
        is_mac     = sys.platform == "darwin"

        try:
            if is_windows:
                # Escape special characters for PowerShell filter
                escaped_title = (
                    title
                    .replace('"', '\"')
                    .replace("'", "\'")
                    .replace("`", "``")
                    .replace("$", "`$")
                    .replace("(", "`(")
                    .replace(")", "`)")
                    .replace("[", "`[")
                    .replace("]", "`]")
                    .replace("{", "`{")
                    .replace("}", "`}")
                    .replace("|", "`|")
                    .replace("&", "`&")
                    .replace("<", "`<")
                    .replace(">", "`>")
                    .replace("*", "`*")
                    .replace("?", "`?")
                )
                filter_value = f'WINDOWTITLE eq *{escaped_title}*'
                result = subprocess.run(
                    ["taskkill", "/F", "/FI", filter_value],
                    capture_output=True, text=True
                )
                success = result.returncode == 0
            elif is_mac:
                escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
                script = f'tell application "{escaped_title}" to quit'
                result = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True, text=True
                )
                success = result.returncode == 0
            else:
                # Linux — use wmctrl if available
                result = subprocess.run(
                    ["wmctrl", "-c", title],
                    capture_output=True, text=True
                )
                success = result.returncode == 0

            if success:
                return (
                    f"STATUS: SUCCESS\n"
                    f"Closed window: {title}"
                )
            else:
                return (
                    f"STATUS: ERROR\n"
                    f"Could not close '{title}'. "
                    f"Make sure the title matches an open window."
                )

        except FileNotFoundError as e:
            return (
                f"DESKTOP ERROR: Required tool not found: {e}\n"
                "Linux: install wmctrl with: sudo apt install wmctrl"
            )
        except Exception as e:
            return f"DESKTOP ERROR: {type(e).__name__}: {e}"

    def _action_get_windows(self, data):
        is_windows = sys.platform.startswith("win")
        is_mac     = sys.platform == "darwin"

        try:
            if is_windows:
                # Use PowerShell to list windows
                result = subprocess.run(
                    ["powershell", "-Command",
                     "Get-Process | Where-Object {$_.MainWindowTitle} | "
                     "Select-Object Name, MainWindowTitle | Format-Table -AutoSize"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode != 0:
                    error_msg = result.stderr.strip() or "Unknown PowerShell error"
                    return f"STATUS: ERROR\nFailed to list windows: {error_msg}"
                windows = result.stdout.strip()
            elif is_mac:
                result = subprocess.run(
                    ["osascript", "-e",
                     'tell application "System Events" to get name of every process '
                     'whose visible is true'],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode != 0:
                    error_msg = result.stderr.strip() or "Unknown osascript error"
                    return f"STATUS: ERROR\nFailed to list windows: {error_msg}"
                windows = result.stdout.strip()
            else:
                # Linux — wmctrl
                result = subprocess.run(
                    ["wmctrl", "-l"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    windows = result.stdout.strip()
                else:
                    # Fallback: xdotool
                    result = subprocess.run(
                        ["xdotool", "search", "--name", ""],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode != 0:
                        error_msg = result.stderr.strip() or "Unknown xdotool error"
                        return f"STATUS: ERROR\nFailed to list windows: {error_msg}"
                    windows = result.stdout.strip()

            if not windows:
                return "STATUS: SUCCESS\nNo windows found."

            return f"STATUS: SUCCESS\nOpen windows:\n{windows}"

        except FileNotFoundError:
            return (
                "DESKTOP ERROR: Window listing tool not found.\n"
                "Linux: install wmctrl with: sudo apt install wmctrl"
            )
        except Exception as e:
            return f"DESKTOP ERROR: {type(e).__name__}: {e}"

    def _action_focus_window(self, data):
        title = str(data.get("title", "")).strip()
        if not title:
            return "DESKTOP ERROR: focus_window requires 'title'."

        is_windows = sys.platform.startswith("win")
        is_mac     = sys.platform == "darwin"

        try:
            if is_windows:
                script = (
                    '$title = $env:NOVA_WINDOW_TITLE; '
                    'Add-Type -AssemblyName Microsoft.VisualBasic; '
                    '[Microsoft.VisualBasic.Interaction]::AppActivate($title)'
                )
                env = os.environ.copy()
                env["NOVA_WINDOW_TITLE"] = title
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", script],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=env,
                )
                success = result.returncode == 0
            elif is_mac:
                escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
                script = f'tell application "{escaped_title}" to activate'
                result = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True, text=True, timeout=10
                )
                success = result.returncode == 0
            else:
                result = subprocess.run(
                    ["wmctrl", "-a", title],
                    capture_output=True, text=True, timeout=10
                )
                success = result.returncode == 0

            time.sleep(0.5)
            path, _ = self._screenshot("after_focus")

            if success:
                result_str = f"STATUS: SUCCESS\nFocused: {title}"
                if path:
                    result_str += f"\nScreenshot: {path}"
                return result_str
            else:
                return (
                    f"STATUS: ERROR\n"
                    f"Could not focus '{title}'."
                )

        except FileNotFoundError:
            return (
                "DESKTOP ERROR: Window tool not found.\n"
                "Linux: install wmctrl with: sudo apt install wmctrl"
            )
        except Exception as e:
            return f"DESKTOP ERROR: {type(e).__name__}: {e}"

    def _action_find_on_screen(self, data):
        pyautogui, err = _import_pyautogui()
        if not pyautogui:
            return f"DESKTOP ERROR: {err}"

        image = data.get("image", "").strip()
        text = data.get("text", "").strip()

        if image:
            if not os.path.isfile(image):
                return f"DESKTOP ERROR: Template image not found: {image}"

            try:
                location = pyautogui.locateOnScreen(image, confidence=0.8)
                if location:
                    center = pyautogui.center(location)
                    return (
                        f"STATUS: SUCCESS\n"
                        f"Found at: x={center.x}, y={center.y}\n"
                        f"Region: {location}"
                    )
                else:
                    return (
                        f"STATUS: ERROR\n"
                        f"Not found on screen: {image}"
                    )
            except Exception as e:
                return f"DESKTOP ERROR: find_on_screen failed: {e}"

        if text:
            # OCR-based text search using pytesseract
            try:
                import pytesseract
                from PIL import Image
            except ImportError:
                return (
                    "DESKTOP ERROR: pytesseract is required for text search.\n"
                    "Install it with: pip install pytesseract\n"
                    "Also install Tesseract OCR: https://github.com/tesseract-ocr/tesseract"
                )

            try:
                screenshot = pyautogui.screenshot()
                # Use pytesseract to get word boxes
                ocr_data = pytesseract.image_to_data(
                    screenshot, output_type=pytesseract.Output.DICT
                )

                text_lower = text.lower()
                matches = []
                n_boxes = len(ocr_data['text'])
                for i in range(n_boxes):
                    word = ocr_data['text'][i].strip()
                    if not word:
                        continue
                    conf = int(ocr_data['conf'][i]) if ocr_data['conf'][i] != '-1' else 0
                    if conf < 30:
                        continue
                    if text_lower in word.lower():
                        x = ocr_data['left'][i]
                        y = ocr_data['top'][i]
                        w = ocr_data['width'][i]
                        h = ocr_data['height'][i]
                        center_x = x + w // 2
                        center_y = y + h // 2
                        matches.append((center_x, center_y, word, conf))

                if matches:
                    # Return the best match (highest confidence)
                    best = max(matches, key=lambda m: m[3])
                    return (
                        f"STATUS: SUCCESS\n"
                        f"Found text '{best[2]}' at: x={best[0]}, y={best[1]}\n"
                        f"Confidence: {best[3]}%\n"
                        f"Total matches: {len(matches)}"
                    )
                else:
                    return (
                        f"STATUS: ERROR\n"
                        f"Text not found on screen: {text!r}"
                    )
            except Exception as e:
                return f"DESKTOP ERROR: OCR text search failed: {e}"

        return "DESKTOP ERROR: find_on_screen requires 'image' or 'text' field."
