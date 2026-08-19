import logging

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config import config

logger = logging.getLogger(__name__)


class TokenSigner:
    """
    Signs and verifies short-lived tokens carrying an arbitrary payload, e.g. for links
    emailed to a user that must work without them being logged in. Scoped to a `purpose` so
    a token generated for one flow can't be replayed against another. Validity is governed by
    `config.token_max_age_seconds`, shared by every purpose.
    """

    def __init__(self, purpose: str) -> None:
        self._purpose = purpose
        self._serializer = URLSafeTimedSerializer(config.session_secret, salt=purpose)

    def generate(self, payload: dict) -> str:
        return self._serializer.dumps(payload)

    def verify(self, token: str) -> dict | None:
        """Returns the original payload, or None if the token is invalid/expired."""

        try:
            return self._serializer.loads(token, max_age=config.token_max_age_seconds)
        except SignatureExpired:
            logger.info(f"'{self._purpose}' token expired")
            return None
        except BadSignature:
            logger.warning(f"'{self._purpose}' token failed signature verification")
            return None


invite_tokens = TokenSigner(purpose="cluster-invite")
keep_alive_tokens = TokenSigner(purpose="cluster-keep-alive")
