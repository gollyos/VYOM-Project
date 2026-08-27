"""Open and Close application & website intent handlers for JARVIS.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import webbrowser
from typing import Optional

from jarvis.backend.db import get_app_path
from jarvis.backend.helper import extract_app_name

logger = logging.getLogger(__name__)

# Common system applications
SYSTEM_APPS: dict[str, str] = {
    "notepad": "notepad.exe",
    "calc": "calc.exe",
    "calculator": "calc.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "terminal": "wt.exe",
    "paint": "mspaint.exe",
    "mspaint": "mspaint.exe",
    "task manager": "taskmgr.exe",
    "taskmgr": "taskmgr.exe",
    "control panel": "control.exe",
    "settings": "ms-settings:",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "camera": "microsoft.windows.camera:",
    "clock": "ms-clock:",
    "spotify": "spotify.exe",
    "vscode": "code",
    "code": "code",
    "visual studio code": "code",
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "brave": "brave",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
}

# Known websites
WEBSITES: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "github": "https://www.github.com",
    "gmail": "https://mail.google.com",
    "chatgpt": "https://chat.openai.com",
    "openai": "https://openai.com",
    "netflix": "https://www.netflix.com",
    "twitter": "https://www.twitter.com",
    "x": "https://www.x.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "reddit": "https://www.reddit.com",
    "linkedin": "https://www.linkedin.com",
    "amazon": "https://www.amazon.in",
    "flipkart": "https://www.flipkart.com",
    "wikipedia": "https://www.wikipedia.org",
    "hotstar": "https://www.hotstar.com",
    "spotify web": "https://open.spotify.com",
    "whatsapp": "https://web.whatsapp.com",
    "telegram": "https://web.telegram.org",
}

# Strict allowlist for closing processes safely
CLOSE_ALLOWLIST: dict[str, str] = {
    "notepad": "notepad.exe",
    "calc": "calc.exe",
    "calculator": "calc.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "brave": "brave.exe",
    "spotify": "Spotify.exe",
    "vscode": "Code.exe",
    "code": "Code.exe",
    "paint": "mspaint.exe",
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
    "cmd": "cmd.exe",
    "taskmgr": "taskmgr.exe",
    "task manager": "taskmgr.exe",
}


def handle_open(query: str) -> str:
    """Handle intent to open an application or website."""
    target = extract_app_name(query).strip()
    if not target:
        return "Please specify what you want me to open, sir."

    # 1. Check custom DB registered application paths
    custom_path = get_app_path(target)
    if custom_path:
        try:
            if sys.platform == "win32" and hasattr(os, "startfile"):
                os.startfile(custom_path)
            else:
                subprocess.Popen([custom_path], shell=True)
            return f"Opening {target} from registered path."
        except Exception as exc:
            logger.error("Failed to open custom path %s: %s", custom_path, exc)
            return f"Error opening {target}: {exc}"

    # 2. Check known websites
    if target in WEBSITES:
        url = WEBSITES[target]
        webbrowser.open(url)
        return f"Opening {target} in your browser, sir."

    # 3. Check system applications
    if target in SYSTEM_APPS:
        app_cmd = SYSTEM_APPS[target]
        try:
            if app_cmd.startswith("http://") or app_cmd.startswith("https://") or ":" in app_cmd:
                if hasattr(os, "startfile"):
                    os.startfile(app_cmd)
                else:
                    webbrowser.open(app_cmd)
            else:
                if sys.platform == "win32":
                    subprocess.Popen(f"start {app_cmd}", shell=True)
                else:
                    subprocess.Popen([app_cmd], shell=True)
            return f"Opening {target}, sir."
        except Exception as exc:
            logger.error("Failed to start system app %s: %s", app_cmd, exc)
            return f"Could not open {target}: {exc}"

    # 4. Fallback: try Windows start / open as website domain
    if "." in target or " " not in target:
        domain_url = f"https://www.{target.replace(' ', '')}.com"
        try:
            webbrowser.open(domain_url)
            return f"Opening {target} as {domain_url}."
        except Exception as exc:
            logger.error("Failed to open domain URL %s: %s", domain_url, exc)

    # 5. Generic start attempt
    try:
        if sys.platform == "win32":
            subprocess.Popen(f"start {target}", shell=True)
            return f"Attempting to launch {target}, sir."
    except Exception as exc:
        logger.error("Generic start failed for %s: %s", target, exc)

    return f"I could not locate application or website for '{target}', sir."


def handle_close(query: str) -> str:
    """Safely terminate an application from the allowlist."""
    target = extract_app_name(query).strip()
    if not target:
        return "Please specify what application you want me to close, sir."

    proc_name = CLOSE_ALLOWLIST.get(target)
    if not proc_name:
        # Check partial match in allowlist
        for key, val in CLOSE_ALLOWLIST.items():
            if key in target or target in key:
                proc_name = val
                break

    if not proc_name:
        return f"Closing '{target}' is not permitted or unrecognized for safety reasons."

    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["taskkill", "/f", "/im", proc_name],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                return f"Closed {target} successfully, sir."
            else:
                return f"{target} does not appear to be currently running."
        except Exception as exc:
            return f"Failed to close {target}: {exc}"
    else:
        try:
            subprocess.run(["pkill", "-f", proc_name], check=False)
            return f"Closed {target} successfully."
        except Exception as exc:
            return f"Failed to close {target}: {exc}"
