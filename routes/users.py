from uuid import uuid4

from psycopg2.extras import Json
from psycopg2.errors import UniqueViolation
from fastapi import APIRouter, Depends, UploadFile, File
import os

from database.connection import get_pg_cursor
from models.users import (
    OnboardingStepUpdate,
    UserLogin,
    UserCreate,
    UserPreferenceUpdate,
    UserStatusUpdate,
    UserUpdate,
)
from utils.auth_flow import authenticate_user, build_authenticated_response, build_password_login_response
from utils.responses import fail, ok, row_to_dict, rows_to_list
from utils.security import get_current_user, require_admin, require_same_user_or_admin
from utils.user_helpers import build_user_response

router = APIRouter(prefix="/users", tags=["users"])

DEFAULT_ONBOARDING_STEPS = ["choose_role", "basic_profile", "skills", "payment_setup"]


def get_user_or_fail(user_id: str) -> dict:
    with get_pg_cursor() as cursor:
        cursor.execute("SELECT * FROM users WHERE id = %s AND deleted_at IS NULL", (user_id,))
        user = row_to_dict(cursor.fetchone())
    if not user:
        fail(404, "USER_NOT_FOUND", "User not found")
    assert user is not None
    return user


@router.post("", status_code=201)
def create_user(payload: UserCreate):
    if "ADMIN" in payload.roles:
        fail(403, "ADMIN_ROLE_FORBIDDEN", "Admin role cannot be assigned during registration", "roles")

    user_id = str(uuid4())
    preference_id = str(uuid4())

    try:
        with get_pg_cursor(commit=True) as cursor:
            cursor.execute(
                """
                INSERT INTO users (id, email, password, full_name, phone, avatar_url)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (user_id, payload.email, payload.password, payload.full_name, payload.phone, payload.avatar_url),            )
            user = cursor.fetchone()
            if user is None:
                fail(500, "USER_CREATE_FAILED", "User could not be created")

            for role in payload.roles:
                cursor.execute(
                    "INSERT INTO user_roles (user_id, role) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (user_id, role),
                )

            if "APPLICANT" in payload.roles:
                cursor.execute(
                    """
                    INSERT INTO applicant_profiles (
                        id, user_id, headline, bio, city, country,
                        expected_salary_min_minor, expected_salary_max_minor,
                        currency, availability, visibility, cv_url
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    (
                        str(uuid4()), user_id, None, None, None, None,
                        None, None, None, None, "PUBLIC", None,
                    ),
                )

            cursor.execute(
                """
                INSERT INTO user_preferences (id, user_id, notification_settings)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (preference_id, user_id, Json({"email_applications": True, "email_messages": True})),
            )

            for step in DEFAULT_ONBOARDING_STEPS:
                cursor.execute(
                    """
                    INSERT INTO onboarding_steps (id, user_id, step_key, status)
                    VALUES (%s, %s, %s, 'PENDING')
                    ON CONFLICT (user_id, step_key) DO NOTHING
                    """,
                    (str(uuid4()), user_id, step),
                )

            return ok(build_authenticated_response(cursor, user))
    except UniqueViolation:
        fail(409, "EMAIL_ALREADY_EXISTS", "This email is already used", "email")


@router.post("/login")
def login_user(payload: UserLogin):
    with get_pg_cursor() as cursor:
        user = authenticate_user(cursor, payload.email, payload.password)
        response = build_password_login_response(cursor, user, remember_me=payload.remember_me or False)

    return ok(response)


@router.get("")
def list_users(limit: int = 50, current_user=Depends(get_current_user)):
    require_admin(current_user)
    with get_pg_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM users WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        users = []
        for row in cursor.fetchall():
            users.append(build_user_response(cursor, row))
    return ok(users)


@router.get("/{user_id}")
def get_user(user_id: str, current_user=Depends(get_current_user)):
    require_same_user_or_admin(user_id, current_user)
    with get_pg_cursor() as cursor:
        cursor.execute("SELECT * FROM users WHERE id = %s AND deleted_at IS NULL", (user_id,))
        user = cursor.fetchone()
        if not user:
            fail(404, "USER_NOT_FOUND", "User not found")
        response = build_user_response(cursor, user)
    return ok(response)


@router.patch("/{user_id}")
def update_user(user_id: str, payload: UserUpdate, current_user=Depends(get_current_user)):
    require_same_user_or_admin(user_id, current_user)
    get_user_or_fail(user_id)
    values = payload.dict(exclude_unset=True)
    if not values:
        return ok(get_user_or_fail(user_id))

    allowed_fields = ["full_name", "phone", "avatar_url", "preferred_locale"]
    set_parts = []
    params = []
    for field in allowed_fields:
        if field in values:
            set_parts.append(f"{field} = %s")
            params.append(values[field])
    set_parts.append("updated_at = NOW()")
    params.append(user_id)

    with get_pg_cursor(commit=True) as cursor:
        cursor.execute(
            f"UPDATE users SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
            tuple(params),
        )
        user = cursor.fetchone()
        response = build_user_response(cursor, user)
    return ok(response)


@router.post("/{user_id}/avatar")
def upload_avatar(user_id: str, file: UploadFile = File(...), current_user=Depends(get_current_user)):
    require_same_user_or_admin(user_id, current_user)
    get_user_or_fail(user_id)

    uploads_dir = os.path.join(os.getcwd(), "static", "uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    # preserve extension, generate unique filename
    _, ext = os.path.splitext(file.filename or "")
    filename = f"{uuid4().hex}{ext}"
    path = os.path.join(uploads_dir, filename)

    with open(path, "wb") as out_file:
        out_file.write(file.file.read())

    avatar_url = f"/static/uploads/{filename}"

    with get_pg_cursor(commit=True) as cursor:
        cursor.execute(
            "UPDATE users SET avatar_url = %s, updated_at = NOW() WHERE id = %s RETURNING *",
            (avatar_url, user_id),
        )
        user = cursor.fetchone()
        response = build_user_response(cursor, user)

    return ok(response)


@router.patch("/{user_id}/status")
def update_user_status(user_id: str, payload: UserStatusUpdate, current_user=Depends(get_current_user)):
    require_admin(current_user)
    get_user_or_fail(user_id)
    with get_pg_cursor(commit=True) as cursor:
        cursor.execute(
            "UPDATE users SET status = %s, updated_at = NOW() WHERE id = %s RETURNING *",
            (payload.status, user_id),
        )
        updated_user = cursor.fetchone()
        if updated_user is None:
            fail(500, "USER_UPDATE_FAILED", "User status could not be updated")
        assert updated_user is not None
        response = build_user_response(cursor, updated_user)
    return ok(response)


@router.patch("/{user_id}/preferences")
def update_preferences(user_id: str, payload: UserPreferenceUpdate, current_user=Depends(get_current_user)):
    require_same_user_or_admin(user_id, current_user)
    get_user_or_fail(user_id)
    values = payload.dict(exclude_unset=True)

    with get_pg_cursor(commit=True) as cursor:
        cursor.execute("SELECT * FROM user_preferences WHERE user_id = %s", (user_id,))
        current = cursor.fetchone()
        if not current:
            cursor.execute(
                "INSERT INTO user_preferences (id, user_id) VALUES (%s, %s)",
                (str(uuid4()), user_id),
            )

        set_parts = []
        params = []
        if "hide_taken_jobs" in values:
            set_parts.append("hide_taken_jobs = %s")
            params.append(values["hide_taken_jobs"])
        if "profile_visibility" in values:
            set_parts.append("profile_visibility = %s")
            params.append(values["profile_visibility"])
        if "notification_settings" in values:
            set_parts.append("notification_settings = %s")
            params.append(Json(values["notification_settings"]))

        if set_parts:
            set_parts.append("updated_at = NOW()")
            params.append(user_id)
            cursor.execute(
                f"UPDATE user_preferences SET {', '.join(set_parts)} WHERE user_id = %s RETURNING *",
                tuple(params),
            )
        else:
            cursor.execute("SELECT * FROM user_preferences WHERE user_id = %s", (user_id,))
        return ok(row_to_dict(cursor.fetchone()))


@router.get("/{user_id}/onboarding/status")
def get_onboarding_status(user_id: str, current_user=Depends(get_current_user)):
    require_same_user_or_admin(user_id, current_user)
    user = get_user_or_fail(user_id)
    with get_pg_cursor() as cursor:
        cursor.execute(
            """
            SELECT step_key AS key, status
            FROM onboarding_steps
            WHERE user_id = %s
            ORDER BY step_key
            """,
            (user_id,),
        )
        steps = rows_to_list(cursor.fetchall())
    return ok({"status": user["onboarding_status"], "steps": steps})


@router.patch("/{user_id}/onboarding/steps/{step_key}")
def update_onboarding_step(user_id: str, step_key: str, payload: OnboardingStepUpdate, current_user=Depends(get_current_user)):
    require_same_user_or_admin(user_id, current_user)
    get_user_or_fail(user_id)
    completed_sql = "NOW()" if payload.status == "COMPLETED" else "NULL"
    with get_pg_cursor(commit=True) as cursor:
        cursor.execute(
            f"""
            INSERT INTO onboarding_steps (id, user_id, step_key, status, data, completed_at)
            VALUES (%s, %s, %s, %s, %s, {completed_sql})
            ON CONFLICT (user_id, step_key)
            DO UPDATE SET status = EXCLUDED.status, data = EXCLUDED.data, completed_at = {completed_sql}
            RETURNING *
            """,
            (str(uuid4()), user_id, step_key, payload.status, Json(payload.data)),
        )
        step = row_to_dict(cursor.fetchone())
    return ok(step)


@router.post("/{user_id}/onboarding/complete")
def complete_onboarding(user_id: str, current_user=Depends(get_current_user)):
    require_same_user_or_admin(user_id, current_user)
    get_user_or_fail(user_id)
    with get_pg_cursor(commit=True) as cursor:
        cursor.execute(
            """
            UPDATE users
            SET status = 'ACTIVE', onboarding_status = 'COMPLETED', updated_at = NOW()
            WHERE id = %s
            RETURNING status, onboarding_status
            """,
            (user_id,),
        )
        user = row_to_dict(cursor.fetchone())
        if user is None:
            fail(500, "USER_UPDATE_FAILED", "User onboarding status could not be updated")
        assert user is not None
    return ok({"user_status": user["status"], "onboarding_status": user["onboarding_status"]})


@router.get("/{user_id}/ratings")
def get_user_ratings(user_id: str):
    get_user_or_fail(user_id)
    with get_pg_cursor() as cursor:
        cursor.execute(
            """
            SELECT rating, comment, role_context, created_at
            FROM ratings
            WHERE ratee_user_id = %s
            ORDER BY created_at DESC
            """,
            (user_id,),
        )
        items = rows_to_list(cursor.fetchall())
        cursor.execute(
            "SELECT COALESCE(AVG(rating), 0) AS average, COUNT(*) AS count FROM ratings WHERE ratee_user_id = %s",
            (user_id,),
        )
        summary = row_to_dict(cursor.fetchone())
        if summary is None:
            fail(500, "RATING_SUMMARY_FAILED", "Rating summary could not be loaded")
        assert summary is not None
    return ok({"average": summary["average"], "count": summary["count"], "items": items})
