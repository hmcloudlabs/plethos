"""
Signed, stateless cluster-invite tokens (itsdangerous). No server-side storage:
the token itself embeds the target claim and invited email, signed and
time-limited, so accepting an invite needs nothing beyond decoding it.
"""

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config import config

_SALT = "cluster-invite"
_MAX_AGE_SECONDS = 7 * 24 * 60 * 60  # 7 days

_serializer = URLSafeTimedSerializer(config.session_secret, salt=_SALT)


def generate_invite_token(object_name: str, email: str) -> str:
    return _serializer.dumps({"object_name": object_name, "email": email})


def verify_invite_token(token: str) -> dict | None:
    """Returns the {"object_name", "email"} payload, or None if invalid/expired."""

    try:
        return _serializer.loads(token, max_age=_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
