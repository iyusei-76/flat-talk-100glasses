import os
import time
import secrets
import threading
import logging
from datetime import timezone

os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials

from . import token_store
from . import crypto_utils

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

# CSRF対策のstateトークン -> {slack_user_id, code_verifier, expires_at} の一時保持（プロセス内メモリ）
_pending_states = {}
_pending_states_lock = threading.Lock()
_STATE_TTL_SECONDS = 600


def check_config():
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"):
        if not os.environ.get(key):
            raise RuntimeError(f"{key} が設定されていません。")
    return True


def _client_config():
    return {
        "web": {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [os.environ["GOOGLE_REDIRECT_URI"]],
        }
    }


def _build_flow():
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = os.environ["GOOGLE_REDIRECT_URI"]
    return flow


def _cleanup_expired_states_locked():
    now = time.time()
    expired = [s for s, v in _pending_states.items() if v["expires_at"] < now]
    for s in expired:
        _pending_states.pop(s, None)


def create_authorization_url(slack_user_id):
    flow = _build_flow()
    state_token = secrets.token_urlsafe(24)

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state_token,
    )

    # authorization_url()実行時にPKCEのcode_verifierが自動生成される。
    # トークン交換時は別のFlowインスタンスを使うため、ここで一緒に保持しておく。
    with _pending_states_lock:
        _cleanup_expired_states_locked()
        _pending_states[state_token] = {
            "slack_user_id": slack_user_id,
            "code_verifier": flow.code_verifier,
            "expires_at": time.time() + _STATE_TTL_SECONDS,
        }

    return auth_url


def resolve_state(state_token):
    with _pending_states_lock:
        _cleanup_expired_states_locked()
        entry = _pending_states.pop(state_token, None)
    if not entry:
        return None
    return {"slack_user_id": entry["slack_user_id"], "code_verifier": entry["code_verifier"]}


def exchange_code_for_credentials(code, code_verifier):
    flow = _build_flow()
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    return flow.credentials


def save_credentials(slack_user_id, credentials):
    access_token_enc = crypto_utils.encrypt(credentials.token)
    refresh_token_enc = (
        crypto_utils.encrypt(credentials.refresh_token) if credentials.refresh_token else None
    )
    scope = " ".join(credentials.scopes) if credentials.scopes else None
    token_store.save_google_credentials(
        slack_user_id, access_token_enc, refresh_token_enc, credentials.expiry, scope
    )


def load_credentials(slack_user_id):
    row = token_store.get_google_credentials(slack_user_id)
    if not row:
        return None

    creds = Credentials(
        token=crypto_utils.decrypt(row["access_token"]),
        refresh_token=crypto_utils.decrypt(row["refresh_token"]) if row["refresh_token"] else None,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=row["scope"].split(" ") if row["scope"] else SCOPES,
    )
    expiry = row["token_expiry"]
    if expiry is not None and expiry.tzinfo is not None:
        # google-authはexpiryをtzなし(naive UTC)前提で比較するため、DBから読んだaware datetimeを変換する
        expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
    creds.expiry = expiry

    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
        save_credentials(slack_user_id, creds)

    return creds
