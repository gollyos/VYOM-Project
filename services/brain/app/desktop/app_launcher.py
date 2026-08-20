from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import psutil
import yaml

from .schemas import ApplicationHealth, ApplicationRecord, ApplicationTrust, AppStatus, IntegrationType


class ApplicationRegistry:
    """Known installed applications. Executable paths are resolved from
    PATH at load time; VYOM never assumes a hard-coded filesystem path
    exists without checking (see docs/NATIVE_APP_AUTOMATION.md)."""

    #: Spoken/typed names for an application -> app_id. One resolution
    #: table for the whole runtime; the planner, the classifier and the
    #: tool layer all come through `resolve` below rather than each
    #: keeping their own alias list.
    ALIASES: dict[str, str] = {
        "calculator": "calculator", "calc": "calculator", "kalkulator": "calculator",
        "notepad": "notepad", "note pad": "notepad",
        "file explorer": "file_explorer", "explorer": "file_explorer",
        "files": "file_explorer", "my computer": "file_explorer", "this pc": "file_explorer",
        "chrome": "chrome", "google chrome": "chrome",
        "edge": "edge", "microsoft edge": "edge",
        "visual studio code": "vscode", "vs code": "vscode", "vscode": "vscode", "code": "vscode",
        "windows terminal": "terminal", "terminal": "terminal",
        "paint": "paint", "ms paint": "paint",
        "settings": "settings", "setting": "settings", "control panel": "settings",
        "task manager": "task_manager",
    }

    #: Names Get-StartApps lists that must never be launched by a fuzzy
    #: voice match: uninstalling something is not "opening" it, and no
    #: spoken "open X" should ever be able to trigger it by accident.
    _UNINSTALL_PREFIX = "uninstall "
    #: Below this a spoken reference is not a real match to any
    #: dynamically-discovered app at all.
    APP_MATCH_FLOOR = 0.74
    #: Two discovered apps closer together than this are genuinely
    #: ambiguous - guessing between them is worse than not resolving.
    APP_AMBIGUITY_MARGIN = 0.08

    def __init__(
        self,
        applications: list[ApplicationRecord] | None = None,
        settings_pages: dict[str, str] | None = None,
    ):
        self._apps: dict[str, ApplicationRecord] = {app.app_id: app for app in (applications or [])}
        self.settings_pages: dict[str, str] = dict(settings_pages or {})
        # Every app Windows itself lists in Start > All apps - populated by
        # discover_installed_apps(), empty (and therefore inert) until then.
        # This is what lets "open X" work for anything actually installed
        # on the machine, not only the curated apps above.
        self._discovered_index: list[tuple[str, str]] = []

    def resolve(self, text: str) -> str | None:
        """Resolve a spoken application reference to a registered app_id.

        Longest alias first so "visual studio code" never resolves as
        "code", and so "file explorer" beats "explorer". Falls back to a
        confident fuzzy match against every app actually installed on this
        machine (see discover_installed_apps()) only when the curated alias
        table has nothing - the curated table is deliberately checked
        first so a well-known app never becomes a fuzzy-match guess."""
        lowered = f" {text.lower().strip()} "
        for alias in sorted(self.ALIASES, key=len, reverse=True):
            if f" {alias} " in lowered or lowered.strip() == alias:
                app_id = self.ALIASES[alias]
                if app_id in self._apps:
                    return app_id
        return self._resolve_discovered(text)

    def _resolve_discovered(self, text: str) -> str | None:
        match = self._match_discovered(text)
        if match is None:
            return None
        name, start_app_id = match
        return self._register_discovered(name, start_app_id).app_id

    def _match_discovered(self, text: str) -> tuple[str, str] | None:
        """Confidently match spoken/typed text against every real app
        Windows lists, the same "score, then floor + ambiguity margin"
        shape as match_browser_profiles - a guess between two plausible
        apps is worse than admitting the name did not resolve."""
        import difflib

        if not self._discovered_index:
            return None
        target = self._normalise(text)
        if not target:
            return None
        ranked: list[tuple[float, str, str]] = []
        for name, app_id_value in self._discovered_index:
            normalised_name = self._normalise(name)
            if not normalised_name:
                continue
            # A short, real app name that is wholly contained in what was
            # said ("Antigravity IDE kholo" contains "antigravityide") is
            # the strongest signal there is. Names under 4 characters are
            # excluded from this shortcut - too easy to appear inside an
            # unrelated word by coincidence - and fall through to the
            # ratio comparison below instead.
            if len(normalised_name) >= 4 and normalised_name in target:
                score = 1.0
            else:
                score = difflib.SequenceMatcher(None, normalised_name, target).ratio()
            ranked.append((score, name, app_id_value))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if not ranked or ranked[0][0] < self.APP_MATCH_FLOOR:
            return None
        if len(ranked) > 1 and (ranked[0][0] - ranked[1][0]) < self.APP_AMBIGUITY_MARGIN:
            return None
        return ranked[0][1], ranked[0][2]

    def _register_discovered(self, name: str, start_app_id: str) -> ApplicationRecord:
        """Turn a Get-StartApps hit into a real, launchable ApplicationRecord
        the first time it is actually matched - lazily, so a machine with
        128 installed apps does not pre-build 128 records nobody asked
        for. Registered as UNKNOWN trust: VYOM found this app itself, no
        one vetted it the way the curated list in applications.yaml is."""
        app_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or f"app-{abs(hash(start_app_id))}"
        existing = self._apps.get(app_id)
        if existing is not None:
            return existing
        process_hint = self._process_name_from_app_id(start_app_id)
        record = ApplicationRecord(
            app_id=app_id, name=name, launch_method="native",
            supported_actions=["open", "focus", "close", "status"],
            integration_type=IntegrationType.ACCESSIBILITY,
            trust=ApplicationTrust.UNKNOWN,
            health=ApplicationHealth.AVAILABLE,
            # shell:AppsFolder\<AppID> is the same activation route the
            # Start Menu itself uses for both packaged (UWP) apps and the
            # GUID-keyed shell items Get-StartApps also returns for
            # ordinary .exe shortcuts - one launch mechanism, no need to
            # tell the two apart.
            aumid=start_app_id,
            window_title=name,
            process_names=[process_hint] if process_hint else [],
        )
        return self.register(record)

    @staticmethod
    def _process_name_from_app_id(app_id_value: str) -> str | None:
        """Best-effort real process name from a Get-StartApps AppID.

        `{GUID}\\program.exe`-shaped ids (ordinary .exe shortcuts) name
        their own process directly. Packaged (UWP) ids
        (`PackageFamilyName!AppId`) do not expose one this way - status/
        close for those falls back to the app_id-derived guess in
        AppLauncher._image_names, which is honestly imperfect until a
        given app is actually opened once and observed."""
        tail = app_id_value.rsplit("\\", 1)[-1]
        return tail.lower() if tail.lower().endswith(".exe") else None

    def discover_installed_apps(self) -> int:
        """Populate the fuzzy-match index from every app Windows itself
        lists in Start > All apps (`Get-StartApps`) - ordinary .exe
        shortcuts and packaged/Store apps alike, since both surface
        through the same Start Menu resolver Windows uses. Returns how
        many apps were indexed.

        This shells out to PowerShell and reliably takes over a second -
        call it exactly ONCE, at Brain startup, via `asyncio.to_thread`.
        It must never run on the event loop or be triggered per-request;
        `resolve()` only ever reads the already-built index synchronously.
        Safe to call again later to pick up newly-installed apps; each
        call replaces the index with a fresh read."""
        if os.name != "nt":
            return 0
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-StartApps | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x0800_0000),
            )
            raw = json.loads(completed.stdout or "[]")
        except (OSError, subprocess.SubprocessError, ValueError):
            return 0
        if isinstance(raw, dict):
            raw = [raw]
        seen: set[str] = set()
        index: list[tuple[str, str]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("Name") or "").strip()
            app_id_value = str(entry.get("AppID") or "").strip()
            if not name or not app_id_value:
                continue
            if name.lower().startswith(self._UNINSTALL_PREFIX):
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            index.append((name, app_id_value))
        self._discovered_index = index
        return len(index)

    # -- browser profiles --------------------------------------------------
    #
    # A Chrome PROFILE is a distinct signed-in identity with its own tabs,
    # history and logins - not an app and not a window. "Open the Goli
    # AIOS profile" names one, and answering it with a directory listing
    # (because "profile" scored well against the filesystem capability)
    # was a wrong-domain answer dressed up as a result.

    @staticmethod
    def browser_profiles() -> list[dict[str, str]]:
        """Chrome profiles registered on this machine.

        Read from Chrome's own `Local State`, so the display name, the
        signed-in account name and the on-disk directory all come from the
        browser rather than being guessed."""
        if os.name != "nt":
            return []
        root = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
        state = root / "Local State"
        if not state.is_file():
            return []
        try:
            cache = json.loads(state.read_text(encoding="utf-8"))["profile"]["info_cache"]
        except (OSError, ValueError, KeyError):
            return []
        return [
            {
                "directory": directory,
                "name": str(meta.get("name") or ""),
                "account": str(meta.get("gaia_name") or ""),
            }
            for directory, meta in cache.items()
        ]

    #: Words that are the COMMAND, never part of the profile's name. They
    #: are removed before matching so "Chrome pe X open karo" compares X
    #: against the profile list rather than the whole sentence.
    _PROFILE_STOPWORDS = frozenset({
        "open", "kholo", "khol", "karo", "kar", "do", "kijiye", "chrome",
        "browser", "profile", "profiles", "the", "my", "mera", "meri", "me",
        "mein", "pe", "par", "on", "in", "switch", "to", "okay", "ok", "please",
        "vyom", "wala", "wali", "account", "user", "जाओ", "खोलो", "करो",
    })

    @staticmethod
    def _normalise(text: str) -> str:
        """Lowercase, alphanumeric only.

        Speech-to-text does not agree with Chrome about where the spaces
        in a proper noun go: the account "Golly AiOs" was transcribed
        "Woolly AI OS". Comparing word-by-word made that unmatchable -
        "aios" against "ai" scores 0.67, and "golly" against "woolly"
        scores 0.73, so both fell under the threshold and VYOM opened a
        generic Chrome window instead of the user's profile. With the
        spaces removed, "gollyaios" against "woollyaios" scores 0.84."""
        return "".join(character for character in text.lower() if character.isalnum())

    @classmethod
    def match_browser_profiles(cls, text: str) -> list[tuple[float, dict[str, str]]]:
        """Rank real Chrome profiles against a spoken reference.

        Returns (score, profile) sorted best-first. Scores are comparable
        across profiles, so the caller can tell a confident match from a
        genuinely ambiguous one and ask rather than guess."""
        import difflib

        candidates = cls.browser_profiles()
        if not candidates:
            return []
        lowered = text.lower()
        # The spoken name, with the command words taken out.
        tokens = [
            token.strip(".,!?।'\"")
            for token in lowered.split()
            if token.strip(".,!?।'\"") and token.strip(".,!?।'\"") not in cls._PROFILE_STOPWORDS
        ]

        ranked: list[tuple[float, dict[str, str]]] = []
        for profile in candidates:
            best_score = 0.0
            for field in ("name", "account", "directory"):
                value = profile[field].strip()
                if not value:
                    continue
                target = cls._normalise(value)
                if not target:
                    continue
                # Exact containment of the real name is the strongest signal.
                if target and target in cls._normalise(lowered):
                    best_score = max(best_score, 1.0)
                    continue
                # Otherwise slide a window over the spoken tokens, joining
                # them WITHOUT spaces, so a name the transcript split or
                # fused still lines up against the real one.
                span = max(1, len(value.split()))
                for width in range(1, span + 3):
                    for start in range(0, max(1, len(tokens) - width + 1)):
                        window = cls._normalise("".join(tokens[start:start + width]))
                        if not window:
                            continue
                        ratio = difflib.SequenceMatcher(None, target, window).ratio()
                        best_score = max(best_score, ratio)
            if best_score > 0:
                ranked.append((best_score, profile))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked

    #: Below this a spoken reference is not a profile name at all.
    PROFILE_MATCH_FLOOR = 0.78
    #: Two candidates closer together than this are genuinely ambiguous.
    PROFILE_AMBIGUITY_MARGIN = 0.08

    @classmethod
    def resolve_browser_profile(cls, text: str) -> dict[str, str] | None:
        """Match a spoken profile reference to a real Chrome profile.

        Returns None when nothing matches confidently OR when two profiles
        match about equally well - guessing between "Business Luxora" and
        "Simrran Boutique" is worse than asking."""
        ranked = cls.match_browser_profiles(text)
        if not ranked or ranked[0][0] < cls.PROFILE_MATCH_FLOOR:
            return None
        if len(ranked) > 1 and (ranked[0][0] - ranked[1][0]) < cls.PROFILE_AMBIGUITY_MARGIN:
            return None
        return ranked[0][1]

    @classmethod
    def ambiguous_browser_profiles(cls, text: str) -> list[dict[str, str]]:
        """The profiles a reference could equally mean, when it is unclear.

        Empty when the reference resolves confidently or matches nothing."""
        ranked = cls.match_browser_profiles(text)
        if not ranked or ranked[0][0] < cls.PROFILE_MATCH_FLOOR:
            return []
        top = ranked[0][0]
        tied = [profile for score, profile in ranked
                if top - score < cls.PROFILE_AMBIGUITY_MARGIN]
        return tied if len(tied) > 1 else []

    def resolve_settings_page(self, text: str) -> str | None:
        """Resolve "bluetooth settings" / "wifi ka page" to its ms-settings
        URI. Returns None when no specific page was named."""
        lowered = text.lower()
        for page, uri in self.settings_pages.items():
            if page in lowered:
                return uri
        return None

    @classmethod
    def from_config(cls, path: Path) -> "ApplicationRegistry":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        apps = []
        for entry in data.get("applications", []):
            executable = cls._resolve(entry.get("executable_candidates", []))
            aumid = entry.get("aumid")
            uri = entry.get("uri")
            # An app is available when ANY launch route resolves, not only
            # when an .exe sits on PATH. Settings has no executable at all
            # and Calculator's is a stub; both are perfectly launchable.
            available = bool(executable) or bool(uri) or bool(aumid and cls._aumid_installed(aumid))
            apps.append(ApplicationRecord(
                app_id=entry["app_id"],
                name=entry["name"],
                executable=executable,
                launch_method=entry.get("launch_method", "native"),
                supported_actions=list(entry.get("supported_actions", [])),
                integration_type=IntegrationType(entry.get("integration_type", "visual_fallback")),
                trust=ApplicationTrust(entry.get("trust", "unknown")),
                health=ApplicationHealth.AVAILABLE if available else ApplicationHealth.NOT_FOUND,
                aumid=aumid,
                uri=uri,
                window_title=entry.get("window_title") or entry["name"],
                process_names=[name.lower() for name in entry.get("process_names", [])],
            ))
        return cls(apps, settings_pages=dict(data.get("settings_pages", {}) or {}))

    @staticmethod
    def _aumid_installed(aumid: str) -> bool:
        """Is this packaged application actually registered on this PC?

        Checked once at load so the registry reports real availability
        instead of assuming a Store app exists."""
        if os.name != "nt":
            return False
        package = aumid.split("!", 1)[0]
        family = package.split("_", 1)[0] if "_" in package else package
        root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WindowsApps"
        try:
            if root.is_dir() and any(child.name.startswith(family) for child in root.iterdir()):
                return True
        except OSError:
            pass
        # WindowsApps is ACL-protected; the per-user package registration
        # is readable and is the authoritative record.
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Classes\ActivatableClasses\Package",
            ) as key:
                index = 0
                while True:
                    try:
                        if winreg.EnumKey(key, index).startswith(family):
                            return True
                    except OSError:
                        break
                    index += 1
        except OSError:
            return False
        return False

    #: Where Windows itself looks for an application that is not on PATH.
    #: Chrome, Edge and VS Code all install here rather than onto PATH, so
    #: a PATH-only lookup reported them as "not registered with a
    #: resolvable executable" while the user could see them installed.
    _APP_PATHS_KEYS = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths",
    )

    @staticmethod
    def _from_app_paths(candidate: str) -> str | None:
        """Resolve through the Windows App Paths registry, the mechanism
        Start > Run uses. Returns None on non-Windows or when absent."""
        if os.name != "nt":
            return None
        try:
            import winreg
        except ImportError:  # pragma: no cover - non-Windows
            return None
        name = candidate if candidate.lower().endswith(".exe") else f"{candidate}.exe"
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for base in ApplicationRegistry._APP_PATHS_KEYS:
                try:
                    with winreg.OpenKey(root, f"{base}\\{name}") as key:
                        value, _ = winreg.QueryValueEx(key, None)
                except OSError:
                    continue
                path = Path(str(value).strip('"'))
                if path.is_file():
                    return str(path)
        return None

    @staticmethod
    def _from_common_locations(candidate: str) -> str | None:
        """Last resort: the standard per-machine and per-user install
        roots. Only an exact existing file is ever returned."""
        name = candidate if candidate.lower().endswith(".exe") else f"{candidate}.exe"
        roots = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        known = {
            "chrome.exe": [r"Google\Chrome\Application"],
            "msedge.exe": [r"Microsoft\Edge\Application"],
            "code.exe": [r"Microsoft VS Code", r"Programs\Microsoft VS Code"],
            "firefox.exe": [r"Mozilla Firefox"],
        }
        for root in filter(None, roots):
            for relative in known.get(name.lower(), []):
                path = Path(root) / relative / name
                if path.is_file():
                    return str(path)
        return None

    @staticmethod
    def _from_start_menu(candidate: str) -> str | None:
        """Resolve through the Start Menu, which is where Windows itself
        records what the user considers an installed application.

        PATH is the wrong index for GUI software: the user can see an app
        in their Start Menu while `shutil.which` reports it does not
        exist, which is exactly how VYOM came to claim an installed
        application was 'not registered with a resolvable executable'."""
        if os.name != "nt":
            return None
        stem = Path(candidate).stem.lower()
        roots = [
            Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
            Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
        ]
        for root in roots:
            if not root.is_dir():
                continue
            try:
                for shortcut in root.rglob("*.lnk"):
                    if not ApplicationRegistry._shortcut_matches(shortcut.stem.lower(), stem):
                        continue
                    target = ApplicationRegistry._shortcut_target(shortcut)
                    if target and Path(target).is_file():
                        return target
            except OSError:
                continue
        return None

    @staticmethod
    def _shortcut_matches(shortcut_stem: str, wanted: str) -> bool:
        """Match a Start Menu entry to a candidate on WORD boundaries.

        A bare substring test resolved "code" to an unrelated "ZCode"
        shortcut and would have launched the wrong application entirely.
        The name must be the whole shortcut or one of its words."""
        if shortcut_stem == wanted:
            return True
        words = re.split(r"[\s\-_.]+", shortcut_stem)
        return wanted in words

    @staticmethod
    def _shortcut_target(shortcut: Path) -> str | None:
        try:
            import win32com.client

            shell = win32com.client.Dispatch("WScript.Shell")
            return str(shell.CreateShortCut(str(shortcut)).Targetpath) or None
        except Exception:
            return None

    @staticmethod
    def _resolve(candidates: list[str]) -> str | None:
        for candidate in candidates:
            found = (
                shutil.which(candidate)
                or ApplicationRegistry._from_app_paths(candidate)
                or ApplicationRegistry._from_common_locations(candidate)
                or ApplicationRegistry._from_start_menu(candidate)
            )
            if found:
                return found
        return None

    def get(self, app_id: str) -> ApplicationRecord | None:
        return self._apps.get(app_id)

    def list(self) -> list[ApplicationRecord]:
        return list(self._apps.values())

    def register(self, record: ApplicationRecord) -> ApplicationRecord:
        self._apps[record.app_id] = record
        return record

    def discover(self, name: str, candidates: list[str]) -> ApplicationRecord | None:
        """Best-effort discovery of a not-yet-known application by probing
        common executable names on PATH. Registers it as untrusted/unknown
        so it does not automatically receive sensitive automation."""
        executable = self._resolve(candidates)
        if not executable:
            return None
        app_id = name.lower().replace(" ", "-")
        record = ApplicationRecord(
            app_id=app_id, name=name, executable=executable, launch_method="native",
            supported_actions=["open", "focus", "close", "status"],
            integration_type=IntegrationType.VISUAL_FALLBACK, trust=ApplicationTrust.UNKNOWN,
            health=ApplicationHealth.AVAILABLE,
        )
        return self.register(record)


class AppLauncherError(Exception):
    pass


class AppLauncher:
    """app.open / app.close / app.focus / app.status. Prefers the
    registered executable identity over shell-string guessing."""

    def __init__(self, registry: ApplicationRegistry):
        self.registry = registry
        self._launched_pids: dict[str, int] = {}

    #: Silent, console-free, detached launch. Spawning through a shell made
    #: Windows flash a console window for what should be an invisible
    #: native launch -- the "unrequested PowerShell window" the user saw.
    @staticmethod
    def _creation_flags() -> dict:
        if os.name != "nt":
            return {}
        return {"creationflags": (
            getattr(subprocess, "CREATE_NO_WINDOW", 0x0800_0000)
            | getattr(subprocess, "DETACHED_PROCESS", 0x0000_0008)
        )}

    def open_browser_profile(self, app_id: str, profile: dict[str, str],
                             *, url: str | None = None) -> AppStatus:
        """Open a browser in a SPECIFIC signed-in profile.

        `--profile-directory` is Chrome's own documented switch; this is
        the same thing the profile picker does, so the user gets their
        real logged-in identity rather than a fresh window."""
        app = self.registry.get(app_id)
        if app is None or not app.executable:
            raise AppLauncherError(f"'{app_id}' has no resolvable executable to open a profile with")
        arguments = [f"--profile-directory={profile['directory']}"]
        if url:
            arguments.append(url)
        process = subprocess.Popen(
            [app.executable, *arguments],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **self._creation_flags(),
        )
        self._launched_pids[app_id] = process.pid
        return AppStatus(app_id=app_id, running=True, pid=process.pid,
                         window_title=profile.get("name"))

    def open(self, app_id: str, *, args: list[str] | None = None) -> AppStatus:
        """Launch through the most native route this application offers.

        Order: protocol URI -> packaged app identity -> executable. Each is
        a real Windows activation mechanism; none of them is a shell
        command, and none of them opens a console."""
        app = self.registry.get(app_id)
        if app is None:
            raise AppLauncherError(f"Application '{app_id}' is not registered")

        target = (args or [None])[0]

        # 1. Protocol handler (ms-settings:, mailto:, etc). For Settings
        #    this is the whole launch -- no executable is involved at all.
        if app.uri and not target:
            return self._launch_shell(app_id, app.uri)
        if app.uri and target and str(target).startswith(("ms-settings:", "ms-")):
            return self._launch_shell(app_id, str(target))

        # 2. Packaged (Store/UWP) identity. This is what the Start Menu
        #    uses, and the only route that reliably starts Windows 11
        #    Calculator/Notepad as the user knows them.
        if app.aumid and not target:
            return self._launch_shell(app_id, f"shell:AppsFolder\\{app.aumid}")

        # 3. Classic executable.
        if not app.executable:
            raise AppLauncherError(
                f"Application '{app_id}' has no resolvable executable, packaged identity or URI"
            )
        process = subprocess.Popen(
            [app.executable, *(args or [])],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **self._creation_flags(),
        )
        self._launched_pids[app_id] = process.pid
        return AppStatus(app_id=app_id, running=True, pid=process.pid)

    def _launch_shell(self, app_id: str, target: str) -> AppStatus:
        """Activate a URI or packaged app through Explorer.

        `explorer.exe <target>` is the documented activation path and runs
        without a console window. The PID returned belongs to the Explorer
        hand-off, not the app, so liveness is always confirmed from the
        real window/process afterwards rather than from this pid."""
        process = subprocess.Popen(
            ["explorer.exe", target],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **self._creation_flags(),
        )
        # Deliberately NOT recorded as the app's pid: it is a launcher
        # hand-off that exits immediately, and treating it as the
        # application is what produced "launched but not running".
        return AppStatus(app_id=app_id, running=True, pid=None)

    def _image_names(self, app_id: str) -> set[str]:
        """Process image names this application actually runs as."""
        app = self.registry.get(app_id)
        if app and app.process_names:
            return set(app.process_names)
        if app and app.executable:
            return {Path(app.executable).name.lower()}
        return {f"{app_id}.exe"}

    def find_processes(self, app_id: str) -> list[psutil.Process]:
        """Every live process belonging to this application, whoever
        started it.

        VYOM operates the user's real desktop, not a private sandbox: the
        Chrome the user wants closed is almost never the Chrome VYOM
        launched. Tracking only self-launched pids is what made "band
        karo" impossible to satisfy."""
        wanted = self._image_names(app_id)
        found: list[psutil.Process] = []
        for process in psutil.process_iter(["name", "pid"]):
            try:
                name = (process.info.get("name") or "").lower()
            except psutil.Error:
                continue
            if name in wanted:
                found.append(process)
        return found

    def status(self, app_id: str) -> AppStatus:
        """Liveness read from the real process table.

        The launcher's own pid is not the answer: a packaged app's launch
        stub exits within a second of handing off, and a user-started
        instance was never tracked here at all."""
        processes = self.find_processes(app_id)
        if processes:
            return AppStatus(app_id=app_id, running=True, pid=processes[0].pid)
        pid = self._launched_pids.get(app_id)
        if pid is not None and psutil.pid_exists(pid):
            return AppStatus(app_id=app_id, running=True, pid=pid)
        return AppStatus(app_id=app_id, running=False)

    def close(self, app_id: str, *, force: bool = False) -> AppStatus:
        """Close the application the USER can see.

        Closing an app with unsaved data requires L2 approval upstream (the
        `desktop` tool marks close L2); this performs the bounded
        terminate/kill once approved, and reports the honest post-state
        rather than assuming the terminate worked."""
        processes = self.find_processes(app_id)
        if not processes:
            pid = self._launched_pids.get(app_id)
            if pid is None:
                raise AppLauncherError(f"'{app_id}' is not running, so there is nothing to close")
            try:
                processes = [psutil.Process(pid)]
            except psutil.NoSuchProcess:
                self._launched_pids.pop(app_id, None)
                return AppStatus(app_id=app_id, running=False)

        for process in processes:
            try:
                process.kill() if force else process.terminate()
            except psutil.Error:
                continue
        # Give the applications a moment to actually exit, then re-read the
        # process table. The verdict is observed, never assumed.
        psutil.wait_procs(processes, timeout=5)
        self._launched_pids.pop(app_id, None)
        remaining = self.find_processes(app_id)
        return AppStatus(
            app_id=app_id,
            running=bool(remaining),
            pid=remaining[0].pid if remaining else None,
        )

    def managed_app_ids(self) -> list[str]:
        return list(self._launched_pids.keys())
