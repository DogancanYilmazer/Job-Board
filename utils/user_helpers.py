from typing import Any, Dict


def load_roles(cursor: Any, user_id: str):
    cursor.execute(
        "SELECT role FROM user_roles WHERE user_id = %s ORDER BY role",
        (user_id,),
    )
    return [row["role"] for row in cursor.fetchall()]


def build_user_response(cursor: Any, user: Any) -> Dict[str, Any]:
    user_data = dict(user)
    user_data.pop("password", None)
    user_data.pop("otp_secret", None)
    user_data["roles"] = load_roles(cursor, user_data["id"])
    return user_data
