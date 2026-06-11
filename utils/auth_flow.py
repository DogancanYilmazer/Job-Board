from typing import Any, Dict, Optional

from utils.responses import fail
from utils.security import create_access_token, create_temp_token
from utils.user_helpers import build_user_response


def authenticate_user(cursor: Any, email: Optional[str] = None, username: Optional[str] = None, password: Optional[str] = None):
    if not email and not username:
        fail(401, "INVALID_CREDENTIALS", "Please enter an email or username")
    if not password:
        fail(401, "INVALID_CREDENTIALS", "Please enter a password")

    if email:
        cursor.execute(
            "SELECT * FROM users WHERE email = %s AND deleted_at IS NULL",
            (email,),
        )
    else:
        cursor.execute(
            "SELECT * FROM users WHERE username = %s AND deleted_at IS NULL",
            (username,),
        )
    user = cursor.fetchone()
    if user is None or user["password"] != password:
        fail(401, "INVALID_CREDENTIALS", "Invalid email, username, or password")
    return user


def build_authenticated_response(cursor: Any, user: Any, remember_me: bool = False) -> Dict[str, Any]:
    safe_user = build_user_response(cursor, user)
    return {
        **safe_user,
        "user": safe_user,
        "access_token": create_access_token(safe_user["id"], remember_me=remember_me),
        "requires_2fa": False,
    }


def build_password_login_response(cursor: Any, user: Any, remember_me: bool = False) -> Dict[str, Any]:
    if user.get("otp_enabled") and user.get("otp_verified"):
        return {
            "requires_2fa": True,
            "temp_token": create_temp_token(user["id"]),
            "remember_me": remember_me,
        }
    return build_authenticated_response(cursor, user, remember_me=remember_me)
