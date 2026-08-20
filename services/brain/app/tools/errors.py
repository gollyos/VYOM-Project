class ToolError(Exception):
    """Base error for controlled tool execution."""


class ToolValidationError(ToolError):
    pass


class ToolPermissionError(ToolError):
    pass


class ToolCancelledError(ToolError):
    pass


class ToolTimeoutError(ToolError):
    pass


class ToolUnavailableError(ToolError):
    pass
