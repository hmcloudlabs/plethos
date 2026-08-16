import logging

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config import config

logger = logging.getLogger(__name__)


_SALT = "cluster-invite"
_MAX_AGE_SECONDS = 7 * 24 * 60 * 60  # 7 days

_serializer = URLSafeTimedSerializer(config.session_secret, salt=_SALT)


def generate_invite_token(object_name: str, email: str) -> str:
    return _serializer.dumps({"object_name": object_name, "email": email})


def verify_invite_token(token: str) -> dict | None:
    """Returns the {"object_name", "email"} payload, or None if invalid/expired."""

    try:
        return _serializer.loads(token, max_age=_MAX_AGE_SECONDS)
    except SignatureExpired:
        logger.info("Invite token expired")
        return None
    except BadSignature:
        logger.warning("Invite token failed signature verification")
        return None
