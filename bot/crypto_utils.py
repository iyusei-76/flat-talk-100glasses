import os

from cryptography.fernet import Fernet


def _get_fernet():
    key = os.environ.get("GOOGLE_TOKEN_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "GOOGLE_TOKEN_ENCRYPTION_KEY が設定されていません。"
            '`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` '
            "で生成した値を .env に設定してください。"
        )
    return Fernet(key.encode())


def encrypt(value):
    if value is None:
        return None
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(value):
    if value is None:
        return None
    return _get_fernet().decrypt(value.encode()).decode()
