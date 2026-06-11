from uuid import uuid4

from database.connection import get_pg_cursor
from models.profiles import ApplicantProfileUpsert, EmployerProfileUpsert
from utils.responses import fail, ok, row_to_dict, rows_to_list

from fastapi import APIRouter, Depends

from utils.security import get_current_user, get_optional_current_user, require_same_user_or_admin

router = APIRouter(tags=["profiles"])


def user_exists(cursor, user_id: str) -> bool:
    cursor.execute("SELECT id FROM users WHERE id = %s AND deleted_at IS NULL", (user_id,))
    return cursor.fetchone() is not None


def require_profile_view(profile, current_user) -> None:
    visibility = (profile.get("visibility") or "PUBLIC").upper()
    if visibility == "PUBLIC":
        return
    if visibility == "REGISTERED" and current_user is not None:
        return
    if current_user is None:
        fail(401, "AUTH_REQUIRED", "Authentication is required")
    require_same_user_or_admin(profile["user_id"], current_user)


@router.get("/applicant-profile/{user_id}")
def get_applicant_profile(user_id: str, current_user=Depends(get_optional_current_user)):
    with get_pg_cursor() as cursor:
        cursor.execute("SELECT * FROM applicant_profiles WHERE user_id = %s", (user_id,))
        profile = row_to_dict(cursor.fetchone())
        if not profile:
            fail(404, "APPLICANT_PROFILE_NOT_FOUND", "Applicant profile not found")
        require_profile_view(profile, current_user)

        cursor.execute(
            """
            SELECT s.id AS skill_id, s.canonical_name, aps.proficiency_level, aps.years_experience
            FROM applicant_skills aps
            JOIN skills s ON s.id = aps.skill_id
            WHERE aps.applicant_profile_id = %s
            ORDER BY s.canonical_name
            """,
            (profile["id"],),
        )
        profile["skills"] = rows_to_list(cursor.fetchall())
    return ok(profile)


@router.put("/applicant-profile/{user_id}")
def upsert_applicant_profile(user_id: str, payload: ApplicantProfileUpsert, current_user=Depends(get_current_user)):
    require_same_user_or_admin(user_id, current_user)
    if "APPLICANT" not in current_user.get("roles", []):
        fail(403, "FORBIDDEN", "Only job seekers can create or update an applicant profile")
    if (
        payload.expected_salary_min_minor is not None
        and payload.expected_salary_max_minor is not None
        and payload.expected_salary_min_minor > payload.expected_salary_max_minor
    ):
        fail(400, "VALIDATION_ERROR", "expected_salary_min_minor must be less than expected_salary_max_minor", "expected_salary_min_minor")

    with get_pg_cursor(commit=True) as cursor:
        if not user_exists(cursor, user_id):
            fail(404, "USER_NOT_FOUND", "User not found")

        profile_id = str(uuid4())
        cursor.execute(
            """
            INSERT INTO applicant_profiles (
                id, user_id, headline, bio, city, country,
                expected_salary_min_minor, expected_salary_max_minor,
                currency, availability, visibility, cv_url
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id)
            DO UPDATE SET
                headline = EXCLUDED.headline,
                bio = EXCLUDED.bio,
                city = EXCLUDED.city,
                country = EXCLUDED.country,
                expected_salary_min_minor = EXCLUDED.expected_salary_min_minor,
                expected_salary_max_minor = EXCLUDED.expected_salary_max_minor,
                currency = EXCLUDED.currency,
                availability = EXCLUDED.availability,
                visibility = EXCLUDED.visibility,
                cv_url = EXCLUDED.cv_url,
                updated_at = NOW()
            RETURNING *
            """,
            (
                profile_id,
                user_id,
                payload.headline,
                payload.bio,
                payload.city,
                payload.country,
                payload.expected_salary_min_minor,
                payload.expected_salary_max_minor,
                payload.currency,
                payload.availability,
                payload.visibility,
                payload.cv_url,
            ),
        )
        profile = row_to_dict(cursor.fetchone())

        if payload.skills:
            cursor.execute(
                "DELETE FROM applicant_skills WHERE applicant_profile_id = %s",
                (profile["id"],),
            )
            for skill in payload.skills:
                cursor.execute(
                    """
                    INSERT INTO applicant_skills (
                        id, applicant_profile_id, skill_id, proficiency_level, years_experience
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (applicant_profile_id, skill_id)
                    DO UPDATE SET
                        proficiency_level = EXCLUDED.proficiency_level,
                        years_experience = EXCLUDED.years_experience
                    """,
                    (
                        str(uuid4()),
                        profile["id"],
                        skill.skill_id,
                        skill.proficiency_level,
                        skill.years_experience,
                    ),
                )

        cursor.execute(
            """
            SELECT s.id AS skill_id, s.canonical_name, aps.proficiency_level, aps.years_experience
            FROM applicant_skills aps
            JOIN skills s ON s.id = aps.skill_id
            WHERE aps.applicant_profile_id = %s
            ORDER BY s.canonical_name
            """,
            (profile["id"],),
        )
        profile["skills"] = rows_to_list(cursor.fetchall())
    return ok(profile)


@router.get("/employer-profile/{user_id}")
def get_employer_profile(user_id: str):
    with get_pg_cursor() as cursor:
        cursor.execute("SELECT * FROM employer_profiles WHERE user_id = %s", (user_id,))
        profile = row_to_dict(cursor.fetchone())
    if not profile:
        fail(404, "EMPLOYER_PROFILE_NOT_FOUND", "Employer profile not found")
    return ok(profile)


@router.put("/employer-profile/{user_id}")
def upsert_employer_profile(user_id: str, payload: EmployerProfileUpsert, current_user=Depends(get_current_user)):
    require_same_user_or_admin(user_id, current_user)
    if "EMPLOYER" not in current_user.get("roles", []):
        fail(403, "FORBIDDEN", "Only employers can create or update an employer profile")
    with get_pg_cursor(commit=True) as cursor:
        if not user_exists(cursor, user_id):
            fail(404, "USER_NOT_FOUND", "User not found")

        cursor.execute(
            """
            INSERT INTO employer_profiles (
                id, user_id, display_name, company_name, website_url, bio
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id)
            DO UPDATE SET
                display_name = EXCLUDED.display_name,
                company_name = EXCLUDED.company_name,
                website_url = EXCLUDED.website_url,
                bio = EXCLUDED.bio,
                updated_at = NOW()
            RETURNING *
            """,
            (
                str(uuid4()),
                user_id,
                payload.display_name,
                payload.company_name,
                payload.website_url,
                payload.bio,
            ),
        )
        profile = row_to_dict(cursor.fetchone())
    return ok(profile)
