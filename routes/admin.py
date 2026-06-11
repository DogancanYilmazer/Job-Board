from uuid import uuid4

from fastapi import APIRouter, Depends
from psycopg2.extras import Json

from database.connection import get_pg_cursor
from models.admin import (
    AdminLogCreate,
    ApplicationStatusAdminUpdate,
    JobStatusAdminUpdate,
    SiteSettingsUpdate,
    UserBlockUpdate,
    UserRoleUpdate,
    UserStatusAdminUpdate,
)
from utils.admin_helpers import log_admin_action
from utils.responses import fail, ok, row_to_dict, rows_to_list
from utils.security import get_current_user, require_admin
from utils.user_helpers import build_user_response

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Dashboard ──

@router.get("/dashboard/stats")
def dashboard_stats(current_user=Depends(get_current_user)):
    require_admin(current_user)
    with get_pg_cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS total FROM users WHERE deleted_at IS NULL"
        )
        total_users = cursor.fetchone()["total"]

        cursor.execute(
            "SELECT COUNT(*) AS total FROM users WHERE deleted_at IS NULL AND created_at >= NOW() - INTERVAL '7 days'"
        )
        new_users_7d = cursor.fetchone()["total"]

        cursor.execute(
            "SELECT COUNT(*) AS total FROM users WHERE deleted_at IS NULL AND status = 'ACTIVE'"
        )
        active_users = cursor.fetchone()["total"]

        cursor.execute(
            "SELECT COUNT(*) AS total FROM users WHERE deleted_at IS NULL AND is_blocked = TRUE"
        )
        blocked_users = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM jobs")
        total_jobs = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM applications")
        total_applications = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM contracts")
        total_contracts = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM offers")
        total_offers = cursor.fetchone()["total"]

    return ok(
        {
            "total_users": total_users,
            "new_users_7d": new_users_7d,
            "active_users": active_users,
            "blocked_users": blocked_users,
            "total_jobs": total_jobs,
            "total_applications": total_applications,
            "total_contracts": total_contracts,
            "total_offers": total_offers,
        }
    )


# ── Users ──

@router.get("/users")
def list_admin_users(
    q: str = "",
    role: str = "",
    status: str = "",
    is_blocked: str = "",
    page: int = 1,
    limit: int = 20,
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    page = max(page, 1)
    limit = min(max(limit, 1), 100)
    offset = (page - 1) * limit

    where = ["deleted_at IS NULL"]
    params = []
    if q:
        where.append(
            "(email ILIKE %s OR full_name ILIKE %s OR phone ILIKE %s)"
        )
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if status:
        where.append("status = %s")
        params.append(status)
    if is_blocked:
        where.append("is_blocked = %s")
        params.append(is_blocked.lower() == "true")

    where_sql = " AND ".join(where)

    with get_pg_cursor() as cursor:
        cursor.execute(
            f"SELECT COUNT(*) AS total FROM users WHERE {where_sql}",
            tuple(params),
        )
        total = cursor.fetchone()["total"]

        cursor.execute(
            f"""
            SELECT * FROM users
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params + [limit, offset]),
        )
        users = []
        for row in cursor.fetchall():
            user = build_user_response(cursor, row)
            users.append(user)

        if role:
            users = [u for u in users if role.upper() in u.get("roles", [])]
            total = len(users)
            users = users[offset : offset + limit]

    return ok(users, meta={"page": page, "limit": limit, "total": total})


@router.get("/users/{user_id}")
def get_admin_user(user_id: str, current_user=Depends(get_current_user)):
    require_admin(current_user)
    with get_pg_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM users WHERE id = %s AND deleted_at IS NULL", (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            fail(404, "USER_NOT_FOUND", "User not found")
        user = build_user_response(cursor, row)
    return ok(user)


@router.patch("/users/{user_id}/role")
def update_user_role(
    user_id: str,
    payload: UserRoleUpdate,
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    with get_pg_cursor(commit=True) as cursor:
        cursor.execute(
            "SELECT * FROM users WHERE id = %s AND deleted_at IS NULL", (user_id,)
        )
        if not cursor.fetchone():
            fail(404, "USER_NOT_FOUND", "User not found")

        if payload.action == "add":
            cursor.execute(
                "INSERT INTO user_roles (user_id, role) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (user_id, payload.role),
            )
        else:
            cursor.execute(
                "DELETE FROM user_roles WHERE user_id = %s AND role = %s",
                (user_id, payload.role),
            )

        cursor.execute(
            "SELECT * FROM users WHERE id = %s AND deleted_at IS NULL", (user_id,)
        )
        user = build_user_response(cursor, cursor.fetchone())

        log_admin_action(
            cursor,
            current_user["id"],
            "UPDATE_USER_ROLE",
            "USER",
            user_id,
            f"Role {payload.role} {payload.action}ed by admin",
        )

    return ok(user)


@router.patch("/users/{user_id}/block")
def update_user_block(
    user_id: str,
    payload: UserBlockUpdate,
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    with get_pg_cursor(commit=True) as cursor:
        cursor.execute(
            "SELECT * FROM users WHERE id = %s AND deleted_at IS NULL", (user_id,)
        )
        if not cursor.fetchone():
            fail(404, "USER_NOT_FOUND", "User not found")

        cursor.execute(
            "UPDATE users SET is_blocked = %s, updated_at = NOW() WHERE id = %s RETURNING *",
            (payload.is_blocked, user_id),
        )
        user = build_user_response(cursor, cursor.fetchone())

        action = "BLOCK_USER" if payload.is_blocked else "UNBLOCK_USER"
        log_admin_action(
            cursor,
            current_user["id"],
            action,
            "USER",
            user_id,
            f"User {'blocked' if payload.is_blocked else 'unblocked'} by admin",
        )

    return ok(user)


@router.patch("/users/{user_id}/status")
def update_user_status_admin(
    user_id: str,
    payload: UserStatusAdminUpdate,
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    with get_pg_cursor(commit=True) as cursor:
        cursor.execute(
            "SELECT * FROM users WHERE id = %s AND deleted_at IS NULL", (user_id,)
        )
        if not cursor.fetchone():
            fail(404, "USER_NOT_FOUND", "User not found")

        cursor.execute(
            "UPDATE users SET status = %s, updated_at = NOW() WHERE id = %s RETURNING *",
            (payload.status, user_id),
        )
        user = build_user_response(cursor, cursor.fetchone())

        log_admin_action(
            cursor,
            current_user["id"],
            "UPDATE_USER_STATUS",
            "USER",
            user_id,
            f"User status changed to {payload.status} by admin",
        )

    return ok(user)


@router.delete("/users/{user_id}")
def delete_user_admin(user_id: str, current_user=Depends(get_current_user)):
    require_admin(current_user)
    if str(user_id) == str(current_user["id"]):
        fail(403, "SELF_DELETE_FORBIDDEN", "You cannot delete yourself")

    with get_pg_cursor(commit=True) as cursor:
        cursor.execute(
            "UPDATE users SET deleted_at = NOW(), updated_at = NOW() WHERE id = %s RETURNING *",
            (user_id,),
        )
        if not cursor.fetchone():
            fail(404, "USER_NOT_FOUND", "User not found")

        log_admin_action(
            cursor,
            current_user["id"],
            "DELETE_USER",
            "USER",
            user_id,
            "User soft-deleted by admin",
        )

    return ok({"message": "User deleted successfully"})


# ── Jobs ──

@router.get("/jobs")
def list_admin_jobs(
    q: str = "",
    status: str = "",
    page: int = 1,
    limit: int = 20,
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    page = max(page, 1)
    limit = min(max(limit, 1), 100)
    offset = (page - 1) * limit

    where = []
    params = []
    if q:
        where.append("(title ILIKE %s OR description ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if status:
        where.append("status = %s")
        params.append(status)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    with get_pg_cursor() as cursor:
        cursor.execute(
            f"SELECT COUNT(*) AS total FROM jobs j {where_sql}",
            tuple(params),
        )
        total = cursor.fetchone()["total"]

        cursor.execute(
            f"""
            SELECT j.*, u.full_name AS owner_name
            FROM jobs j
            LEFT JOIN users u ON u.id = j.owner_user_id
            {where_sql}
            ORDER BY j.created_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params + [limit, offset]),
        )
        jobs = rows_to_list(cursor.fetchall())

    return ok(jobs, meta={"page": page, "limit": limit, "total": total})


@router.get("/jobs/{job_id}")
def get_admin_job(job_id: str, current_user=Depends(get_current_user)):
    require_admin(current_user)
    with get_pg_cursor() as cursor:
        cursor.execute(
            """
            SELECT j.*, u.full_name AS owner_name
            FROM jobs j
            LEFT JOIN users u ON u.id = j.owner_user_id
            WHERE j.id = %s
            """,
            (job_id,),
        )
        job = row_to_dict(cursor.fetchone())
        if not job:
            fail(404, "JOB_NOT_FOUND", "Job not found")
    return ok(job)


@router.patch("/jobs/{job_id}/status")
def update_job_status_admin(
    job_id: str,
    payload: JobStatusAdminUpdate,
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    with get_pg_cursor(commit=True) as cursor:
        cursor.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
        job = row_to_dict(cursor.fetchone())
        if not job:
            fail(404, "JOB_NOT_FOUND", "Job not found")

        published_sql = ", published_at = NOW()" if payload.status == "OPEN" else ""
        cursor.execute(
            f"""
            UPDATE jobs
            SET status = %s, updated_at = NOW() {published_sql}
            WHERE id = %s
            RETURNING *
            """,
            (payload.status, job_id),
        )
        updated = row_to_dict(cursor.fetchone())

        cursor.execute(
            """
            INSERT INTO job_status_history (id, job_id, from_status, to_status, changed_by_user_id, note)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                str(uuid4()),
                job_id,
                job["status"],
                payload.status,
                current_user["id"],
                payload.note or "Updated by admin",
            ),
        )

        log_admin_action(
            cursor,
            current_user["id"],
            "UPDATE_JOB_STATUS",
            "JOB",
            job_id,
            f"Job status changed from {job['status']} to {payload.status} by admin",
        )

    return ok(updated)


@router.delete("/jobs/{job_id}")
def delete_job_admin(job_id: str, current_user=Depends(get_current_user)):
    require_admin(current_user)
    with get_pg_cursor(commit=True) as cursor:
        cursor.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
        if not cursor.fetchone():
            fail(404, "JOB_NOT_FOUND", "Job not found")

        # Soft delete by setting status to HIDDEN and updating title
        cursor.execute(
            "UPDATE jobs SET status = 'HIDDEN', title = CONCAT(title, ' [DELETED]'), updated_at = NOW() WHERE id = %s RETURNING *",
            (job_id,),
        )
        cursor.fetchone()

        log_admin_action(
            cursor,
            current_user["id"],
            "DELETE_JOB",
            "JOB",
            job_id,
            "Job deleted by admin",
        )

    return ok({"message": "Job deleted successfully"})


# ── Applications ──

@router.get("/applications")
def list_admin_applications(
    q: str = "",
    status: str = "",
    page: int = 1,
    limit: int = 20,
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    page = max(page, 1)
    limit = min(max(limit, 1), 100)
    offset = (page - 1) * limit

    where = []
    params = []
    if status:
        where.append("a.status = %s")
        params.append(status)
    if q:
        where.append("(j.title ILIKE %s OR u.full_name ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    with get_pg_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            JOIN users u ON u.id = a.applicant_user_id
            {where_sql}
            """,
            tuple(params),
        )
        total = cursor.fetchone()["total"]

        cursor.execute(
            f"""
            SELECT a.*, j.title AS job_title, u.full_name AS applicant_name
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            JOIN users u ON u.id = a.applicant_user_id
            {where_sql}
            ORDER BY a.submitted_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params + [limit, offset]),
        )
        applications = rows_to_list(cursor.fetchall())

    return ok(applications, meta={"page": page, "limit": limit, "total": total})


@router.patch("/applications/{application_id}/status")
def update_application_status_admin(
    application_id: str,
    payload: ApplicationStatusAdminUpdate,
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    with get_pg_cursor(commit=True) as cursor:
        cursor.execute(
            "SELECT * FROM applications WHERE id = %s", (application_id,)
        )
        app = row_to_dict(cursor.fetchone())
        if not app:
            fail(404, "APPLICATION_NOT_FOUND", "Application not found")

        cursor.execute(
            "UPDATE applications SET status = %s, updated_at = NOW() WHERE id = %s RETURNING *",
            (payload.status, application_id),
        )
        updated = row_to_dict(cursor.fetchone())

        cursor.execute(
            """
            INSERT INTO application_status_history (id, application_id, from_status, to_status, changed_by_user_id, note)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                str(uuid4()),
                application_id,
                app["status"],
                payload.status,
                current_user["id"],
                payload.note or "Updated by admin",
            ),
        )

        log_admin_action(
            cursor,
            current_user["id"],
            "UPDATE_APPLICATION_STATUS",
            "APPLICATION",
            application_id,
            f"Application status changed from {app['status']} to {payload.status} by admin",
        )

    return ok(updated)


# ── Settings ──

@router.get("/settings")
def get_site_settings(current_user=Depends(get_current_user)):
    require_admin(current_user)
    with get_pg_cursor() as cursor:
        cursor.execute("SELECT * FROM site_settings ORDER BY created_at DESC LIMIT 1")
        settings = row_to_dict(cursor.fetchone())
        if not settings:
            # Insert default row
            cursor.execute(
                "INSERT INTO site_settings DEFAULT VALUES RETURNING *"
            )
            settings = row_to_dict(cursor.fetchone())
    return ok(settings)


@router.put("/settings")
def update_site_settings(
    payload: SiteSettingsUpdate,
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    values = payload.dict(exclude_unset=True)
    if not values:
        return get_site_settings(current_user)

    with get_pg_cursor(commit=True) as cursor:
        cursor.execute("SELECT * FROM site_settings ORDER BY created_at DESC LIMIT 1")
        existing = cursor.fetchone()
        if not existing:
            cursor.execute("INSERT INTO site_settings DEFAULT VALUES RETURNING id")
            existing = cursor.fetchone()

        set_parts = []
        params = []
        for key, val in values.items():
            set_parts.append(f"{key} = %s")
            params.append(val)
        set_parts.append("updated_at = NOW()")
        params.append(existing["id"])

        cursor.execute(
            f"UPDATE site_settings SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
            tuple(params),
        )
        settings = row_to_dict(cursor.fetchone())

        log_admin_action(
            cursor,
            current_user["id"],
            "UPDATE_SETTINGS",
            "SETTINGS",
            str(existing["id"]),
            "Site settings updated by admin",
            metadata=values,
        )

    return ok(settings)


# ── Logs ──

@router.get("/logs")
def list_admin_logs(
    page: int = 1,
    limit: int = 50,
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    page = max(page, 1)
    limit = min(max(limit, 1), 100)
    offset = (page - 1) * limit

    with get_pg_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS total FROM admin_activity_logs")
        total = cursor.fetchone()["total"]

        cursor.execute(
            """
            SELECT l.*, u.full_name AS admin_name
            FROM admin_activity_logs l
            LEFT JOIN users u ON u.id = l.admin_user_id
            ORDER BY l.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        logs = rows_to_list(cursor.fetchall())

    return ok(logs, meta={"page": page, "limit": limit, "total": total})


@router.post("/logs")
def create_admin_log(
    payload: AdminLogCreate,
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    with get_pg_cursor(commit=True) as cursor:
        log_admin_action(
            cursor,
            current_user["id"],
            payload.action_type,
            payload.target_type,
            payload.target_id,
            payload.description,
            payload.metadata,
        )
    return ok({"message": "Log created"})
