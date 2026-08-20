from __future__ import annotations

import re
import shlex
from pathlib import PureWindowsPath
from dataclasses import dataclass

from app.schemas.approvals import PermissionLevel
from app.tools.errors import ToolPermissionError, ToolValidationError


@dataclass(frozen=True, slots=True)
class CommandDecision:
    executable: str
    permission: PermissionLevel
    allowed: bool
    reason: str


class CommandPolicy:
    BLOCKED_PATTERNS = (
        re.compile(r"\brm\s+(-[^\s]*r[^\s]*f|-[^\s]*f[^\s]*r)\b", re.I),
        # `format` here means the disk command. The negative lookbehind
        # stops a PowerShell parameter such as `Get-Date -Format ...` from
        # being misread as a request to format a volume.
        re.compile(r"(?<![-\w])(format|diskpart|mkfs|shutdown|reboot)\b", re.I),
        re.compile(r"\b(reg\s+(add|delete)|set-mppreference|net\s+user)\b", re.I),
        re.compile(r"\b(mimikatz|credential|sam\s+save|lsass)\b", re.I),
        re.compile(r"\b(git\s+push\s+.*--force|git\s+reset\s+--hard)\b", re.I),
        # Phase 13 hardening: destructive recursive deletion on Windows
        # must be blocked just like `rm -rf` — `rd /s /q`, `rmdir /s`,
        # and recursive forced `del` can destroy whole trees.
        re.compile(r"\b(rd|rmdir)(\.\w+)?\s+(/-[^\s]*s[^\s]*|/[^\s]*s)\b", re.I),
        re.compile(r"\bdel\s+(/[^\s]*s[^\s]*q|/[^\s]*q[^\s]*s)\b", re.I),
        re.compile(r"\bcipher\s+/w\b", re.I),
    )
    READ_ONLY = {"git", "rg", "dir", "ls", "pwd", "where", "python", "python.exe", "node", "npm", "cargo"}

    #: PowerShell hosts. A shell host is L2 by default because it can do
    #: anything; a host invoking ONLY read-only cmdlets with no chaining,
    #: piping, redirection or subexpressions is L1. This narrows the
    #: permission to what the command can actually do rather than granting
    #: PowerShell blanket read-only status.
    POWERSHELL_HOSTS = {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}
    READ_ONLY_CMDLETS = {
        "get-date", "get-location", "get-childitem", "get-content", "get-process",
        "get-computerinfo", "get-volume", "get-psdrive", "get-host", "get-command",
        "get-item", "get-itemproperty", "get-help", "test-path", "get-culture",
        "get-timezone", "get-random", "measure-object", "select-object",
    }
    #: Anything that could chain into, or evaluate into, a non-allowlisted
    #: operation. Parentheses are included because `-Format (Get-Foo)`
    #: would evaluate a nested command as a parameter value.
    _SHELL_COMPOSITION = re.compile(r"[;&|><`$(){}]|\bInvoke-\w+\b|\bStart-Process\b|\biex\b", re.I)

    #: Host switches that carry no value; `-Command`/`-c`/`-File` end the
    #: switch list and everything after them is the script body.
    _HOST_SWITCHES = {
        "-noprofile", "-noninteractive", "-nologo", "-noexit", "-sta", "-mta",
        "-windowstyle", "-executionpolicy",
    }
    _BODY_SWITCHES = {"-command", "-c", "-file", "-encodedcommand"}

    #: ffmpeg/ffprobe flags that only report and never write a file.
    FFMPEG_INFO_FLAGS = {
        "-version", "-h", "-help", "-formats", "-codecs", "-encoders",
        "-decoders", "-filters", "-muxers", "-demuxers", "-devices", "-buildconf",
    }

    def _media_permission(self, tokens: list[str]) -> PermissionLevel:
        """ffmpeg can write anywhere, so it is L2 by default. It is L1 when
        it only reports (`-version`), or when every path it touches is
        relative - which keeps the write inside the working directory the
        Terminal Tool has already constrained to an allowed root."""
        arguments = [token.strip('"') for token in tokens[1:]]
        if not arguments:
            return PermissionLevel.L1
        if all(argument.lower() in self.FFMPEG_INFO_FLAGS for argument in arguments):
            return PermissionLevel.L1
        for argument in arguments:
            if argument.startswith("-"):
                continue
            path = PureWindowsPath(argument)
            if path.is_absolute() or argument.startswith(("\\\\", "/")) or ".." in path.parts:
                return PermissionLevel.L2
        return PermissionLevel.L1

    def _powershell_permission(self, tokens: list[str]) -> PermissionLevel:
        rest = [token.strip('"') for token in tokens[1:]]
        body_parts: list[str] = []
        index = 0
        while index < len(rest):
            token = rest[index].lower()
            if token in self._BODY_SWITCHES:
                body_parts = rest[index + 1:]
                break
            if token in self._HOST_SWITCHES:
                # -WindowStyle/-ExecutionPolicy take a value; the rest do not.
                index += 2 if token in {"-windowstyle", "-executionpolicy"} else 1
                continue
            body_parts = rest[index:]
            break
        body = " ".join(body_parts).strip()
        # An -EncodedCommand body cannot be inspected, so it is never L1.
        if any(token.lower() == "-encodedcommand" for token in rest):
            return PermissionLevel.L2
        if not body or self._SHELL_COMPOSITION.search(body):
            return PermissionLevel.L2
        # Composition characters are already rejected above, so the body is
        # a single command: only the token in COMMAND POSITION is a cmdlet,
        # and everything after it is parameters and values. Scanning the
        # whole body instead would misread a value like `yyyy-MM-dd` as a
        # cmdlet named "yyyy-MM".
        leading = re.match(r"\s*([A-Za-z]+-[A-Za-z]+)\b", body)
        if leading is None or leading.group(1).lower() not in self.READ_ONLY_CMDLETS:
            return PermissionLevel.L2
        return PermissionLevel.L1

    def assess(self, command: str) -> CommandDecision:
        if not command.strip():
            raise ToolValidationError("Command cannot be empty")
        for pattern in self.BLOCKED_PATTERNS:
            if pattern.search(command):
                return CommandDecision("blocked", PermissionLevel.L3, False, "Command matches a prohibited destructive capability")
        try:
            tokens = shlex.split(command, posix=False)
        except ValueError as error:
            raise ToolValidationError("Command could not be parsed") from error
        executable = tokens[0].strip('"').lower() if tokens else ""
        executable_name = PureWindowsPath(executable).name
        if executable_name in self.POWERSHELL_HOSTS:
            permission = self._powershell_permission(tokens)
            reason = (
                "PowerShell invoking only allowlisted read-only cmdlets"
                if permission == PermissionLevel.L1
                else "PowerShell host with a composable or non-allowlisted body"
            )
            return CommandDecision(executable, permission, True, reason)
        if executable_name in {"ffmpeg", "ffmpeg.exe", "ffprobe", "ffprobe.exe"}:
            permission = self._media_permission(tokens)
            return CommandDecision(
                executable, permission, True,
                "Media command confined to the working directory" if permission == PermissionLevel.L1
                else "Media command references an absolute or escaping path",
            )
        permission = PermissionLevel.L1 if executable_name in self.READ_ONLY else PermissionLevel.L2
        return CommandDecision(executable, permission, True, "Command passed structured executable and argument policy")

    def require_allowed(self, command: str) -> CommandDecision:
        decision = self.assess(command)
        if not decision.allowed:
            raise ToolPermissionError(decision.reason)
        return decision

    # -- argv execution ----------------------------------------------------
    #
    # VYOM runs the ACTUAL executable, never a shell that then runs it.
    # `create_subprocess_shell` on Windows means `cmd.exe /c <string>` for
    # every single command, which is how the shell became VYOM's universal
    # PC tool: `dir` for listing files, `dir C:\ /s /b | findstr` to search
    # a whole disk, `powershell -Command Get-Date` to read the clock. Each
    # of those has a direct native answer.

    #: Characters that only mean something to a shell. Their presence means
    #: the request genuinely IS a shell job, not a program invocation.
    SHELL_METACHARACTERS = re.compile(r"[|&;<>^`]|\$\(|\$\{|\breg\b\s")

    #: Shell hosts. Running one of these is only legitimate when the user
    #: explicitly asked for a shell.
    SHELL_HOSTS = POWERSHELL_HOSTS | {"cmd", "cmd.exe"}

    #: `cmd.exe` builtins - they are not executables and cannot be exec'd.
    #: Every one of them has a native equivalent VYOM already owns, so
    #: reaching for them is itself the bug.
    SHELL_BUILTINS = {
        "dir": "the filesystem capability (pathlib)",
        "type": "the filesystem capability (read_text)",
        "copy": "the filesystem capability (shutil.copy)",
        "move": "the filesystem capability (shutil.move)",
        "del": "the filesystem capability",
        "cd": "the working directory argument",
        "echo": "a direct response",
        "set": "the environment argument",
        "cls": "nothing - it is a console affordance",
        "findstr": "the filesystem search capability (glob/regex)",
        "tasklist": "the system capability (psutil)",
        "taskkill": "the desktop capability (graceful close, then psutil)",
        "systeminfo": "the system capability (psutil/platform)",
        "ver": "the system capability (platform)",
    }

    def requires_shell(self, command: str) -> bool:
        """Does this command actually need a shell to run?

        Only UNQUOTED operators count. `python -c "import time; time.sleep(2)"`
        contains a semicolon, but it is Python source inside a quoted
        argument - treating it as shell chaining would reject a perfectly
        ordinary direct invocation."""
        try:
            tokens = shlex.split(command, posix=False)
        except ValueError:
            return False
        for token in tokens:
            if token[:1] in "\"'":
                continue  # a quoted argument is literal data, not syntax
            if self.SHELL_METACHARACTERS.search(token):
                return True
        return False

    def argv_for(self, command: str) -> list[str]:
        """Turn a command line into an argv array for direct execution.

        Raises when the command can only run under a shell, so the caller
        has to make that an explicit, auditable decision rather than
        silently wrapping everything in `cmd.exe`."""
        if self.requires_shell(command):
            raise ToolValidationError(
                "This command uses shell operators (pipes, redirection or chaining). "
                "VYOM runs executables directly; a genuine shell job must be requested "
                "as one explicitly."
            )
        try:
            tokens = shlex.split(command, posix=False)
        except ValueError as error:
            raise ToolValidationError("Command could not be parsed") from error
        if not tokens:
            raise ToolValidationError("Command cannot be empty")

        head = PureWindowsPath(tokens[0].strip('"').lower()).name
        stem = head[:-4] if head.endswith(".exe") else head
        if stem in self.SHELL_BUILTINS:
            raise ToolValidationError(
                f"'{stem}' is a shell builtin, not a program. Use {self.SHELL_BUILTINS[stem]} instead."
            )
        return [self._unquote(token) for token in tokens]

    # -- shell tripwire ----------------------------------------------------
    #
    # Section 20: normal operation must produce ZERO shell invocations for
    # desktop / filesystem / system / registry / screen work. Every one of
    # those has a native capability. A violation here is a routing bug, not
    # a runtime inconvenience, so it is recorded loudly and the test suite
    # asserts the count is zero.

    #: Recorded violations, newest last. Read by the audit and by tests.
    violations: list[dict] = []

    #: The only legitimate reasons to run a shell host.
    ALLOWED_SHELL_REASONS = {
        "explicit_user_shell",       # the user asked for PowerShell/cmd by name
        "development_cli",           # git / pytest / npm where a shell was genuinely requested
    }

    @classmethod
    def record_shell_use(cls, command: str, *, category: str, reason: str) -> dict | None:
        """Flag a shell invocation made on behalf of a non-shell category.

        Returns the violation record, or None when the use was legitimate."""
        if reason in cls.ALLOWED_SHELL_REASONS:
            return None
        violation = {
            "severity": "high",
            "policy": "no-shell-for-native-capability",
            "category": category,
            "reason": reason,
            "command": command[:200],
        }
        cls.violations.append(violation)
        return violation

    @classmethod
    def reset_violations(cls) -> None:
        cls.violations.clear()

    @staticmethod
    def _unquote(token: str) -> str:
        """shlex(posix=False) keeps quotes; exec must not receive them.

        Only a MATCHED surrounding pair is removed, so an argument that
        legitimately contains a quote is passed through untouched."""
        if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
            return token[1:-1]
        return token
