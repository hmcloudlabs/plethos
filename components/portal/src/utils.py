import re
from typing import Literal

from starlette.requests import Request


def is_valid_email(email: str) -> bool:
    EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    return EMAIL_RE.match(email) is not None


FlashLevel = Literal["error", "warning", "success"]


def set_flash(request: Request, message: str, level: FlashLevel = "error") -> None:
    """Queues a one-time flash message, shown as a toast (see `base.html`) on the next page
    that reads it via `pop_flash`. Any router can call this ahead of a redirect."""

    request.session["flash_message"] = message
    request.session["flash_level"] = level


def pop_flash(request: Request) -> tuple[str, FlashLevel] | None:
    """Pops the queued flash message (if any), so it's shown at most once."""

    message = request.session.pop("flash_message", None)
    if message is None:
        return None

    level: FlashLevel = request.session.pop("flash_level", "error")
    return message, level
