import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, Optional

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from database.connection import get_pg_cursor
from utils.responses import fail, row_to_dict
from utils.user_helpers import load_roles


ACCESS_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 1       # 1 day (session)
ACCESS_TOKEN_TTL_REMEMBER_SECONDS = 60 * 60 * 24 * 30  # 30 days (remember me)
TEMP_TOKEN_TTL_SECONDS = 60 * 5

bearer_scheme = HTTPBearer(auto_error=False)


def _app_secret() -> bytes:
    secret = os.getenv("AUTH_TOKEN_SECRET") or os.getenv("SECRET_KEY") or "job-board-dev-secret"
    return secret.encode("utf-8")


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def _sign(value: str) -> str:
    digest = hmac.new(_app_secret(), value.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(digest)


def create_token(user_id: Any, token_type: str, ttl_seconds: int) -> str:
    payload = {
        "sub": str(user_id),
        "typ": token_type,
        "exp": int(time.time()) + ttl_seconds,
        "nonce": secrets.token_urlsafe(12),
    }
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_sign(body)}"


def create_access_token(user_id: Any, remember_me: bool = False) -> str:
    ttl = ACCESS_TOKEN_TTL_REMEMBER_SECONDS if remember_me else ACCESS_TOKEN_TTL_SECONDS
    return create_token(user_id, "access", ttl)


def create_temp_token(user_id: Any) -> str:
    return create_token(user_id, "2fa", TEMP_TOKEN_TTL_SECONDS)


def decode_token(token: str, expected_type: str) -> Dict[str, Any]:
    try:
        body, signature = token.split(".", 1)
    except ValueError:
        fail(401, "INVALID_TOKEN", "Invalid authentication token")

    if not hmac.compare_digest(signature, _sign(body)):
        fail(401, "INVALID_TOKEN", "Invalid authentication token")

    try:
        payload = json.loads(_b64decode(body).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        fail(401, "INVALID_TOKEN", "Invalid authentication token")

    if payload.get("typ") != expected_type:
        fail(401, "INVALID_TOKEN", "Invalid authentication token")
    if int(payload.get("exp", 0)) < int(time.time()):
        fail(401, "TOKEN_EXPIRED", "Authentication token has expired")
    if not payload.get("sub"):
        fail(401, "INVALID_TOKEN", "Invalid authentication token")
    return payload


def decode_temp_token(token: str) -> str:
    return str(decode_token(token, "2fa")["sub"])


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Dict[str, Any]:
    if credentials is None:
        fail(401, "AUTH_REQUIRED", "Authentication is required")

    return _load_user_from_credentials(credentials)


def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[Dict[str, Any]]:
    if credentials is None:
        return None

    return _load_user_from_credentials(credentials)


def _load_user_from_credentials(credentials: HTTPAuthorizationCredentials) -> Dict[str, Any]:
    payload = decode_token(credentials.credentials, "access")
    with get_pg_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM users WHERE id = %s AND deleted_at IS NULL",
            (payload["sub"],),
        )
        user = row_to_dict(cursor.fetchone())
        if user is not None:
            user["roles"] = load_roles(cursor, user["id"])

    if user is None:
        fail(401, "AUTH_REQUIRED", "Authentication is required")
    return user


def is_admin(user: Optional[Dict[str, Any]]) -> bool:
    return bool(user and "ADMIN" in user.get("roles", []))


def require_admin(current_user: Dict[str, Any]) -> None:
    if not is_admin(current_user):
        fail(403, "ADMIN_REQUIRED", "Admin authorization is required")


def same_user(left: Any, right: Any) -> bool:
    return str(left) == str(right)


def require_same_user_or_admin(target_user_id: Any, current_user: Dict[str, Any]) -> None:
    if not same_user(target_user_id, current_user["id"]) and not is_admin(current_user):
        fail(403, "FORBIDDEN", "You are not allowed to access this resource")


def _totp_secret_key() -> bytes:
    key_material = os.getenv("OTP_SECRET_ENCRYPTION_KEY") or _app_secret().decode("utf-8")
    return hashlib.sha256(key_material.encode("utf-8")).digest()


def _totp_stream(nonce: bytes, length: int) -> bytes:
    blocks = []
    counter = 0
    key = _totp_secret_key()
    while sum(len(block) for block in blocks) < length:
        counter_bytes = counter.to_bytes(4, "big")
        blocks.append(hmac.new(key, nonce + counter_bytes, hashlib.sha256).digest())
        counter += 1
    return b"".join(blocks)[:length]


def encrypt_totp_secret(secret: str) -> str:
    nonce = secrets.token_bytes(16)
    plaintext = secret.encode("utf-8")
    stream = _totp_stream(nonce, len(plaintext))
    ciphertext = bytes(left ^ right for left, right in zip(plaintext, stream))
    payload = f"v1.{_b64encode(nonce)}.{_b64encode(ciphertext)}"
    signature = hmac.new(_totp_secret_key(), payload.encode("ascii"), hashlib.sha256).digest()
    return f"{payload}.{_b64encode(signature)}"


def decrypt_totp_secret(encrypted_secret: Optional[str]) -> Optional[str]:
    if not encrypted_secret:
        return None

    parts = encrypted_secret.split(".")
    if len(parts) != 4 or parts[0] != "v1":
        # Backward compatibility for older local databases that stored the Base32 secret directly.
        # Existing values from the previous external-encryption format cannot be decoded here.
        if encrypted_secret.startswith("gAAAA"):
            return None
        return encrypted_secret

    payload = ".".join(parts[:3])
    expected_signature = hmac.new(_totp_secret_key(), payload.encode("ascii"), hashlib.sha256).digest()
    try:
        signature = _b64decode(parts[3])
        nonce = _b64decode(parts[1])
        ciphertext = _b64decode(parts[2])
    except ValueError:
        return None

    if not hmac.compare_digest(signature, expected_signature):
        return None

    stream = _totp_stream(nonce, len(ciphertext))
    plaintext = bytes(left ^ right for left, right in zip(ciphertext, stream))
    return plaintext.decode("utf-8")
