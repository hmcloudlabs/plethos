import re


def is_valid_email(email: str) -> bool:
    EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    return EMAIL_RE.match(email) is not None
