import base64
import io

import pyotp
import qrcode
from fastapi import APIRouter, Depends

from database.connection import get_pg_cursor
from models.users import TwoFactorCode, TwoFactorLogin, UserLogin
from utils.auth_flow import (
    authenticate_user,
    build_authenticated_response,
    build_password_login_response,
)
from utils.responses import fail, ok
from utils.security import (
    decode_temp_token,
    decrypt_totp_secret,
    encrypt_totp_secret,
    get_current_user,
)
from utils.user_helpers import build_user_response


router = APIRouter(prefix="/auth", tags=["auth"])
ISSUER_NAME = "JobBoard"


def _get_totp_secret(user) -> str:
    secret = decrypt_totp_secret(user.get("otp_secret"))
    if not secret:
        fail(400, "TWO_FACTOR_NOT_STARTED", "2FA setup has not been started")
    return secret


def _verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


@router.post("/login")
def login(payload: UserLogin):
    with get_pg_cursor() as cursor:
        user = authenticate_user(
            cursor,
            email=payload.email,
            username=payload.username,
            password=payload.password,
        )
        response = build_password_login_response(cursor, user, remember_me=payload.remember_me or False)
    return ok(response)


@router.post("/2fa/enable")
def enable_2fa(current_user=Depends(get_current_user)):
    secret = pyotp.random_base32()
    encrypted_secret = encrypt_totp_secret(secret)

    with get_pg_cursor(commit=True) as cursor:
        cursor.execute(
            """
            UPDATE users
            SET otp_secret = %s,
                otp_enabled = FALSE,
                otp_verified = FALSE,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (encrypted_secret, current_user["id"]),
        )
        user = cursor.fetchone()
        if user is None:
            fail(404, "USER_NOT_FOUND", "User not found")

    uri = pyotp.TOTP(secret).provisioning_uri(
        name=current_user["email"],
        issuer_name=ISSUER_NAME,
    )
    qr = qrcode.make(uri)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode("ascii")

    return ok(
        {
            "qr_code": qr_base64,
            "secret": secret,
            "otpauth_url": uri,
            "message": "Scan the QR code with your authenticator app, then verify the setup code.",
        }
    )


@router.post("/2fa/verify-setup")
def verify_2fa_setup(payload: TwoFactorCode, current_user=Depends(get_current_user)):
    secret = _get_totp_secret(current_user)
    if not _verify_totp(secret, payload.code):
        fail(400, "INVALID_2FA_CODE", "Invalid code. Make sure your authenticator app is synced.")

    with get_pg_cursor(commit=True) as cursor:
        cursor.execute(
            """
            UPDATE users
            SET otp_enabled = TRUE,
                otp_verified = TRUE,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (current_user["id"],),
        )
        user = cursor.fetchone()
        if user is None:
            fail(404, "USER_NOT_FOUND", "User not found")
        response = build_user_response(cursor, user)

    return ok({"message": "2FA enabled successfully", "user": response})


@router.post("/2fa/validate")
def validate_2fa(payload: TwoFactorLogin):
    user_id = decode_temp_token(payload.temp_token)

    with get_pg_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM users WHERE id = %s AND deleted_at IS NULL",
            (user_id,),
        )
        user = cursor.fetchone()
        if user is None:
            fail(401, "INVALID_TOKEN", "Invalid authentication token")
        if not (user.get("otp_enabled") and user.get("otp_verified")):
            fail(401, "TWO_FACTOR_NOT_ENABLED", "2FA is not enabled for this account")

        secret = _get_totp_secret(user)
        if not _verify_totp(secret, payload.code):
            fail(401, "INVALID_2FA_CODE", "Invalid 2FA code")

        response = build_authenticated_response(cursor, user, remember_me=payload.remember_me or False)

    return ok(response)


@router.post("/2fa/disable")
def disable_2fa(payload: TwoFactorCode, current_user=Depends(get_current_user)):
    if not (current_user.get("otp_enabled") and current_user.get("otp_verified")):
        fail(400, "TWO_FACTOR_NOT_ENABLED", "2FA is not enabled for this account")

    secret = _get_totp_secret(current_user)
    if not _verify_totp(secret, payload.code):
        fail(401, "INVALID_2FA_CODE", "Invalid 2FA code")

    with get_pg_cursor(commit=True) as cursor:
        cursor.execute(
            """
            UPDATE users
            SET otp_secret = NULL,
                otp_enabled = FALSE,
                otp_verified = FALSE,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (current_user["id"],),
        )
        user = cursor.fetchone()
        if user is None:
            fail(404, "USER_NOT_FOUND", "User not found")
        response = build_user_response(cursor, user)

    return ok({"message": "2FA disabled successfully", "user": response})
