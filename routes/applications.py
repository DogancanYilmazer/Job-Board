from uuid import uuid4

from fastapi import APIRouter, Depends
from psycopg2.errors import UniqueViolation
from psycopg2.extras import Json

from database.connection import get_pg_cursor
from models.applications import ApplicationCreate, ApplicationStatusUpdate, WithdrawApplication
from routes.jobs import enrich_job
from utils.match_score import calculate_match_score
from utils.responses import fail, ok, row_to_dict, rows_to_list
from utils.security import get_current_user, is_admin, require_same_user_or_admin, same_user

router = APIRouter(tags=["applications"])

ALLOWED_APPLICATION_TRANSITIONS = {
    "APPLIED": ["REVIEWED", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"],
    "REVIEWED": ["INTERVIEW", "OFFER", "REJECTED"],
    "INTERVIEW": ["OFFER", "REJECTED"],
    "OFFER": ["ACCEPTED", "REJECTED"],
}


def application_exists(cursor, application_id: str):
    cursor.execute(
        """
        SELECT a.*, j.owner_user_id AS job_owner_user_id
        FROM applications a
        JOIN jobs j ON j.id = a.job_id
        WHERE a.id = %s
        """,
        (application_id,),
    )
    app = row_to_dict(cursor.fetchone())
    if not app:
        fail(404, "APPLICATION_NOT_FOUND", "Application not found")
    return app


def require_application_participant(app, current_user) -> None:
    if is_admin(current_user):
        return
    if same_user(app["applicant_user_id"], current_user["id"]):
        return
    if same_user(app["job_owner_user_id"], current_user["id"]):
        return
    fail(403, "FORBIDDEN", "You are not allowed to access this application")


def require_application_owner(app, current_user) -> None:
    if not same_user(app["job_owner_user_id"], current_user["id"]) and not is_admin(current_user):
        fail(403, "FORBIDDEN", "Only the job owner can manage this application")


@router.post("/jobs/{job_id}/applications", status_code=201)
def submit_application(job_id: str, payload: ApplicationCreate, current_user=Depends(get_current_user)):
    if "APPLICANT" not in current_user.get("roles", []):
        fail(403, "FORBIDDEN", "Only job seekers can apply to jobs")
    application_id = str(uuid4())
    applicant_user_id = payload.applicant_user_id or str(current_user["id"])
    require_same_user_or_admin(applicant_user_id, current_user)

    try:
        with get_pg_cursor(commit=True) as cursor:
            cursor.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
            job = row_to_dict(cursor.fetchone())
            if not job:
                fail(404, "JOB_NOT_FOUND", "Job not found")
            if job["status"] not in ["OPEN", "NEGOTIATING"]:
                fail(409, "JOB_NOT_AVAILABLE", "Job must be OPEN or NEGOTIATING")
            if str(job["owner_user_id"]) == str(applicant_user_id):
                fail(409, "OWNER_CANNOT_APPLY", "Owner cannot apply to own job")

            cursor.execute(
                "SELECT * FROM applicant_profiles WHERE user_id = %s",
                (applicant_user_id,),
            )
            applicant_profile = row_to_dict(cursor.fetchone())
            if not applicant_profile:
                # Auto-create empty applicant profile if missing
                profile_id = str(uuid4())
                cursor.execute(
                    """
                    INSERT INTO applicant_profiles (
                        id, user_id, headline, bio, city, country,
                        expected_salary_min_minor, expected_salary_max_minor,
                        currency, availability, visibility, cv_url
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        profile_id, applicant_user_id, None, None, None, None,
                        None, None, None, None, "PUBLIC", None,
                    ),
                )
                applicant_profile = row_to_dict(cursor.fetchone())

            score, breakdown = calculate_match_score(cursor, job_id, applicant_profile["id"])
            cursor.execute(
                """
                INSERT INTO applications (
                    id, job_id, applicant_user_id, applicant_profile_id,
                    cover_letter, proposed_amount_minor, proposed_currency,
                    status, match_score, match_snapshot
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'APPLIED', %s, %s)
                RETURNING *
                """,
                (
                    application_id,
                    job_id,
                    applicant_user_id,
                    applicant_profile["id"],
                    payload.cover_letter,
                    payload.proposed_amount_minor,
                    payload.proposed_currency,
                    score,
                    Json(breakdown),
                ),
            )
            application = row_to_dict(cursor.fetchone())

            cursor.execute(
                """
                INSERT INTO application_status_history (
                    id, application_id, from_status, to_status, changed_by_user_id
                )
                VALUES (%s, %s, NULL, 'APPLIED', %s)
                """,
                (str(uuid4()), application_id, applicant_user_id),
            )
    except UniqueViolation:
        fail(409, "APPLICATION_ALREADY_EXISTS", "Same user cannot apply twice to same job")

    return ok(
        {
            "id": application["id"],
            "job_id": application["job_id"],
            "status": application["status"],
            "match_score": application["match_score"],
            "match_score_breakdown": application["match_snapshot"],
            "submitted_at": application["submitted_at"],
        }
    )


def _is_employer(user: dict) -> bool:
    return "EMPLOYER" in user.get("roles", [])


@router.get("/users/{user_id}/applications")
def list_user_applications(
    user_id: str,
    status: str = "",
    q: str = "",
    page: int = 1,
    limit: int = 20,
    current_user=Depends(get_current_user),
):
    require_same_user_or_admin(user_id, current_user)
    page = max(page, 1)
    limit = min(max(limit, 1), 100)
    offset = (page - 1) * limit
    q = q.strip()

    where = ["a.applicant_user_id = %s"]
    params = [user_id]
    if status:
        where.append("a.status = %s")
        params.append(status)
    if q:
        where.append("(j.title ILIKE %s OR COALESCE(a.cover_letter, '') ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    where_sql = " AND ".join(where)

    with get_pg_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            WHERE {where_sql}
            """,
            tuple(params),
        )
        total = cursor.fetchone()["total"]
        cursor.execute(
            """
            SELECT status, COUNT(*) AS total
            FROM applications
            WHERE applicant_user_id = %s
            GROUP BY status
            """,
            (user_id,),
        )
        status_counts = {row["status"]: row["total"] for row in cursor.fetchall()}
        application_total = sum(status_counts.values())
        cursor.execute(
            f"""
            SELECT a.*, j.title AS job_title
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            WHERE {where_sql}
            ORDER BY a.submitted_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params + [limit, offset]),
        )
        applications = rows_to_list(cursor.fetchall())
    return ok(
        applications,
        meta={
            "page": page,
            "limit": limit,
            "total": total,
            "application_total": application_total,
            "status_counts": status_counts,
        },
    )


@router.get("/users/{user_id}/job-applications")
def list_user_job_applications(
    user_id: str,
    status: str = "",
    q: str = "",
    page: int = 1,
    limit: int = 20,
    current_user=Depends(get_current_user),
):
    require_same_user_or_admin(user_id, current_user)
    if not _is_employer(current_user) and not is_admin(current_user):
        fail(403, "FORBIDDEN", "Only employers can view applications to their jobs")
    page = max(page, 1)
    limit = min(max(limit, 1), 100)
    offset = (page - 1) * limit
    q = q.strip()

    where = ["j.owner_user_id = %s"]
    params = [user_id]
    if status:
        where.append("a.status = %s")
        params.append(status)
    if q:
        where.append("(j.title ILIKE %s OR COALESCE(u.full_name, '') ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    where_sql = " AND ".join(where)

    with get_pg_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            LEFT JOIN users u ON u.id = a.applicant_user_id
            WHERE {where_sql}
            """,
            tuple(params),
        )
        total = cursor.fetchone()["total"]
        cursor.execute(
            """
            SELECT a.status, COUNT(*) AS total
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            WHERE j.owner_user_id = %s
            GROUP BY a.status
            """,
            (user_id,),
        )
        status_counts = {row["status"]: row["total"] for row in cursor.fetchall()}
        application_total = sum(status_counts.values())
        cursor.execute(
            f"""
            SELECT a.*, j.title AS job_title, u.full_name AS applicant_name
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            LEFT JOIN users u ON u.id = a.applicant_user_id
            WHERE {where_sql}
            ORDER BY a.submitted_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params + [limit, offset]),
        )
        applications = rows_to_list(cursor.fetchall())
    return ok(
        applications,
        meta={
            "page": page,
            "limit": limit,
            "total": total,
            "application_total": application_total,
            "status_counts": status_counts,
        },
    )


@router.get("/applications/{application_id}")
def get_application(application_id: str, current_user=Depends(get_current_user)):
    with get_pg_cursor() as cursor:
        cursor.execute(
            """
            SELECT a.*, j.title AS job_title, j.owner_user_id AS job_owner_user_id, u.full_name AS applicant_name
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            JOIN users u ON u.id = a.applicant_user_id
            WHERE a.id = %s
            """,
            (application_id,),
        )
        app = row_to_dict(cursor.fetchone())
    if not app:
        fail(404, "APPLICATION_NOT_FOUND", "Application not found")
    require_application_participant(app, current_user)
    return ok(app)


@router.patch("/applications/{application_id}/status")
def update_application_status(application_id: str, payload: ApplicationStatusUpdate, current_user=Depends(get_current_user)):
    with get_pg_cursor(commit=True) as cursor:
        app = application_exists(cursor, application_id)
        require_application_owner(app, current_user)
        current_status = app["status"]
        allowed_next = ALLOWED_APPLICATION_TRANSITIONS.get(current_status, [])
        if payload.status != current_status and payload.status not in allowed_next:
            fail(
                422,
                "INVALID_STATE_TRANSITION",
                f"Cannot change application status from {current_status} to {payload.status}",
                "status",
            )
        cursor.execute(
            """
            UPDATE applications
            SET status = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (payload.status, application_id),
        )
        updated = row_to_dict(cursor.fetchone())
        cursor.execute(
            """
            INSERT INTO application_status_history (
                id, application_id, from_status, to_status, changed_by_user_id, note
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                str(uuid4()),
                application_id,
                current_status,
                payload.status,
                current_user["id"],
                payload.note,
            ),
        )
    return ok(updated)


@router.get("/applications/{application_id}/status-history")
def get_status_history(application_id: str, current_user=Depends(get_current_user)):
    with get_pg_cursor() as cursor:
        app = application_exists(cursor, application_id)
        require_application_participant(app, current_user)
        cursor.execute(
            """
            SELECT from_status, to_status, changed_by_user_id, note, created_at
            FROM application_status_history
            WHERE application_id = %s
            ORDER BY created_at ASC
            """,
            (application_id,),
        )
        history = rows_to_list(cursor.fetchall())
    return ok(history)


@router.post("/applications/{application_id}/withdraw")
def withdraw_application(application_id: str, payload: WithdrawApplication, current_user=Depends(get_current_user)):
    with get_pg_cursor(commit=True) as cursor:
        app = application_exists(cursor, application_id)
        if payload.applicant_user_id and not same_user(payload.applicant_user_id, current_user["id"]) and not is_admin(current_user):
            fail(403, "FORBIDDEN", "You are not allowed to act as another applicant")
        if not same_user(app["applicant_user_id"], current_user["id"]) and not is_admin(current_user):
            fail(403, "NOT_APPLICATION_OWNER", "Only applicant can withdraw this application")
        if app["status"] in ["ACCEPTED", "REJECTED", "WITHDRAWN"]:
            fail(409, "APPLICATION_ALREADY_CLOSED", "Application is already closed")
        cursor.execute(
            "UPDATE applications SET status = 'WITHDRAWN', updated_at = NOW() WHERE id = %s RETURNING *",
            (application_id,),
        )
        updated = row_to_dict(cursor.fetchone())
        cursor.execute(
            """
            INSERT INTO application_status_history (
                id, application_id, from_status, to_status, changed_by_user_id, note
            )
            VALUES (%s, %s, %s, 'WITHDRAWN', %s, %s)
            """,
            (
                str(uuid4()),
                application_id,
                app["status"],
                current_user["id"],
                payload.reason,
            ),
        )
    return ok(updated)


@router.get("/users/{user_id}/jobs")
def list_user_jobs(
    user_id: str,
    status: str = "",
    q: str = "",
    page: int = 1,
    limit: int = 20,
    current_user=Depends(get_current_user),
):
    require_same_user_or_admin(user_id, current_user)
    if not _is_employer(current_user) and not is_admin(current_user):
        fail(403, "FORBIDDEN", "Only employers can view their job listings")
    page = max(page, 1)
    limit = min(max(limit, 1), 100)
    offset = (page - 1) * limit
    q = q.strip()

    where = ["j.owner_user_id = %s"]
    params = [user_id]
    if status:
        where.append("j.status = %s")
        params.append(status)
    if q:
        where.append("(j.title ILIKE %s OR j.description ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    where_sql = " AND ".join(where)

    with get_pg_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM jobs j
            WHERE {where_sql}
            """,
            tuple(params),
        )
        total = cursor.fetchone()["total"]
        cursor.execute(
            """
            SELECT status, COUNT(*) AS total
            FROM jobs
            WHERE owner_user_id = %s
            GROUP BY status
            """,
            (user_id,),
        )
        status_counts = {row["status"]: row["total"] for row in cursor.fetchall()}
        cursor.execute(
            f"""
            SELECT j.*
            FROM jobs j
            WHERE {where_sql}
            ORDER BY j.created_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params + [limit, offset]),
        )
        jobs = []
        for row in cursor.fetchall():
            job = enrich_job(cursor, row, current_user)
            cursor.execute(
                "SELECT COUNT(*) AS total FROM applications WHERE job_id = %s",
                (job["id"],),
            )
            job["application_count"] = cursor.fetchone()["total"]
            jobs.append(job)
    return ok(
        jobs,
        meta={
            "page": page,
            "limit": limit,
            "total": total,
            "status_counts": status_counts,
        },
    )
