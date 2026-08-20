import logging
import re

#: Anything that can carry a credential. Applied to every log record
#: before it is emitted, so a secret cannot reach a log file even if some
#: library writes a full URL or header. This exists because the Gemini key
#: was being written verbatim into HTTP access lines as `?key=...`.
_SECRET_PATTERNS = (
    # Credential-bearing query parameters.
    re.compile(r"([?&](?:key|api_key|apikey|access_token|token|secret|password)=)[^&\s\"']+", re.I),
    # Authorization / provider key headers, in dict or header-line form.
    re.compile(r"((?:authorization|x-goog-api-key|x-api-key|api-key)['\"]?\s*[:=]\s*['\"]?)[^,\s'\"}\]]+", re.I),
    # Bearer tokens anywhere.
    re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}", re.I),
    # Recognisable provider key shapes, as a last resort.
    re.compile(r"\b(AIza)[A-Za-z0-9_-]{20,}"),
    re.compile(r"\b(sk-)[A-Za-z0-9]{16,}"),
)

_REDACTED = "<redacted>"


def redact_secrets(text: str) -> str:
    """Replace credential values with a placeholder, keeping the key name
    so a log line stays diagnosable."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda match: match.group(1) + _REDACTED, text)
    return text


class SecretRedactingFilter(logging.Filter):
    """Redacts credentials from the formatted message and its arguments.

    Installed on the root logger so it covers third-party libraries
    (httpx logs the full request URL at INFO) as well as VYOM's own code.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: redact_secrets(value) if isinstance(value, str) else value
                    for key, value in record.args.items()
                }
            else:
                record.args = tuple(
                    redact_secrets(value) if isinstance(value, str) else value
                    for value in record.args
                )
        return True


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    redactor = SecretRedactingFilter()
    root = logging.getLogger()
    if not any(isinstance(existing, SecretRedactingFilter) for existing in root.filters):
        root.addFilter(redactor)
    # Handlers are consulted independently of the logger's own filters, so
    # attach there too - otherwise records that bypass the root logger's
    # filter chain would still be written with the secret intact.
    for handler in root.handlers:
        if not any(isinstance(existing, SecretRedactingFilter) for existing in handler.filters):
            handler.addFilter(redactor)
