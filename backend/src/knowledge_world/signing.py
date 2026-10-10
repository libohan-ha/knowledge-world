"""Shared local signatures for quotes, history and restore previews."""
import secrets
from itsdangerous import URLSafeTimedSerializer


def signer(settings):
    path = settings.data_dir / ".signing-key"
    if not path.exists():
        try:
            with path.open("x", encoding="ascii") as file:
                file.write(secrets.token_hex(32))
        except FileExistsError:
            pass
    return URLSafeTimedSerializer(path.read_text(encoding="ascii"), salt="knowledge-world-v1")
