from uuid import uuid4

from fastapi import APIRouter, Depends

from database.connection import get_pg_cursor
from models.jobs import JobCreate, JobStatusUpdate, JobUpdate, TakenVisibilityUpdate
from utils.match_score import get_match_score_for_user
from utils.responses import fail, ok, row_to_dict, rows_to_list
from utils.security import (
    get_current_user,
    get_optional_current_user,
    is_admin,
    require_same_user_or_admin,
    same_user,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])

ALLOWED_JOB_TRANSITIONS = {
    "DRAFT": ["PENDING_REVIEW", "OPEN", "CANCELLED"],
    "PENDING_REVIEW": ["OPEN", "CANCELLED"],
    "OPEN": ["NEGOTIATING", "EXPIRED", "CANCELLED", "HIDDEN"],
    "NEGOTIATING": ["IN_PROGRESS", "OPEN", "CANCELLED"],
    "IN_PROGRESS": ["FILLED", "COMPLETED", "CANCELLED"],
    "FILLED": ["COMPLETED"],
}


def validate_salary(min_minor, max_minor) -> None:
    if min_minor is not None and max_minor is not None and min_minor > max_minor:
        fail(400, "VALIDATION_ERROR", "salary_min_minor must be less than salary_max_minor", "salary_min_minor")


def job_exists(cursor, job_id: str):
    cursor.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
    job = row_to_dict(cursor.fetchone())
    if not job:
        fail(404, "JOB_NOT_FOUND", "Job not found")
    return job


def can_manage_job(job, current_user) -> bool:
    return bool(current_user and (same_user(job["owner_user_id"], current_user["id"]) or is_admin(current_user)))


def require_job_manager(job, current_user) -> None:
    if not can_manage_job(job, current_user):
        fail(403, "FORBIDDEN", "Only the job owner can manage this listing")


def can_view_job(job, current_user) -> bool:
    if can_manage_job(job, current_user):
        return True

    status = (job.get("status") or "").upper()
    visibility = (job.get("visibility") or "PUBLIC").upper()
    if status in {"DRAFT", "HIDDEN"}:
        return False
    if visibility == "PUBLIC":
        return True
    if visibility == "REGISTERED" and current_user is not None:
        return True
    return False


def require_job_view(job, current_user) -> None:
    if not can_view_job(job, current_user):
        fail(403, "FORBIDDEN", "You are not allowed to access this listing")


def get_job_required_skills(cursor, job_id: str):
    cursor.execute(
        """
        SELECT
            s.id AS skill_id,
            s.canonical_name AS name,
            jrs.importance_weight,
            jrs.required_level,
            jrs.must_have
        FROM job_required_skills jrs
        JOIN skills s ON s.id = jrs.skill_id
        WHERE jrs.job_id = %s
        ORDER BY s.canonical_name
        """,
        (job_id,),
    )
    return rows_to_list(cursor.fetchall())


def enrich_job(cursor, job, current_user=None):
    if not job:
        return None
    job = dict(job)
    cursor.execute(
        """
        SELECT ja.assigned_to_user_id, ja.visibility, u.full_name
        FROM job_assignments ja
        LEFT JOIN users u ON u.id = ja.assigned_to_user_id
        WHERE ja.job_id = %s AND ja.status = 'ASSIGNED'
        ORDER BY ja.assigned_at DESC
        LIMIT 1
        """,
        (job["id"],),
    )
    assignment = row_to_dict(cursor.fetchone())
    job_status = (job.get("status") or "").upper()
    availability = {"status": "AVAILABLE", "taken_by": None}
    if assignment:
        availability = {
            "status": "TAKEN",
            "visibility": assignment["visibility"],
            "taken_by": None,
        }
        if assignment["visibility"] == "SHOW_TAKEN_AND_ASSIGNEE":
            availability["taken_by"] = {
                "user_id": assignment["assigned_to_user_id"],
                "display_name": assignment["full_name"],
            }
    elif job_status not in ("OPEN", "NEGOTIATING"):
        availability = {"status": "UNAVAILABLE", "taken_by": None}
    job["availability"] = availability
    job["required_skills"] = get_job_required_skills(cursor, job["id"])
    job["salary"] = {
        "min_minor": job.pop("salary_min_minor", None),
        "max_minor": job.pop("salary_max_minor", None),
        "currency": job.pop("currency", None),
        "period": job.pop("salary_period", None),
        "price_negotiable": job.get("price_negotiable"),
    }

    # Attach match score for logged-in applicants
    if current_user is not None and "APPLICANT" in current_user.get("roles", []):
        match_payload = get_match_score_for_user(cursor, job["id"], str(current_user["id"]))
        if match_payload is not None:
            job["match_score"] = match_payload["match_score"]
            job["match_score_breakdown"] = match_payload["match_score_breakdown"]
        else:
            job["match_score"] = None
            job["match_score_breakdown"] = None
    else:
        job["match_score"] = None
        job["match_score_breakdown"] = None

    return job


@router.post("", status_code=201)
def create_job(payload: JobCreate, current_user=Depends(get_current_user)):
    require_same_user_or_admin(payload.owner_user_id, current_user)
    if "EMPLOYER" not in current_user.get("roles", []):
        fail(403, "FORBIDDEN", "Only employers can create job listings")
    validate_salary(payload.salary_min_minor, payload.salary_max_minor)
    job_id = str(uuid4())

    with get_pg_cursor(commit=True) as cursor:
        cursor.execute("SELECT id FROM users WHERE id = %s", (payload.owner_user_id,))
        if not cursor.fetchone():
            fail(404, "OWNER_NOT_FOUND", "Owner user not found", "owner_user_id")

        cursor.execute("SELECT id, user_id FROM employer_profiles WHERE id = %s", (payload.employer_profile_id,))
        employer_profile = row_to_dict(cursor.fetchone())
        if not employer_profile:
            fail(404, "EMPLOYER_PROFILE_NOT_FOUND", "Employer profile not found", "employer_profile_id")
        if not same_user(employer_profile["user_id"], payload.owner_user_id):
            fail(403, "FORBIDDEN", "Employer profile does not belong to the job owner", "employer_profile_id")

        cursor.execute(
            """
            INSERT INTO jobs (
                id, owner_user_id, employer_profile_id, title, description,
                country, city, area, remote_allowed, workplace_type, job_type,
                career_level, salary_min_minor, salary_max_minor, currency,
                salary_period, price_negotiable, visibility, taken_visibility, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                job_id,
                payload.owner_user_id,
                payload.employer_profile_id,
                payload.title,
                payload.description,
                payload.country,
                payload.city,
                payload.area,
                payload.remote_allowed,
                payload.workplace_type,
                payload.job_type,
                payload.career_level,
                payload.salary_min_minor,
                payload.salary_max_minor,
                payload.currency,
                payload.salary_period,
                payload.price_negotiable,
                payload.visibility,
                payload.taken_visibility,
                payload.status,
            ),
        )
        job = row_to_dict(cursor.fetchone())

        for required_skill in payload.required_skills:
            cursor.execute("SELECT id FROM skills WHERE id = %s", (required_skill.skill_id,))
            if not cursor.fetchone():
                fail(404, "SKILL_NOT_FOUND", "Skill not found", "required_skills")
            cursor.execute(
                """
                INSERT INTO job_required_skills (
                    id, job_id, skill_id, importance_weight, required_level, must_have
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (job_id, skill_id)
                DO UPDATE SET
                    importance_weight = EXCLUDED.importance_weight,
                    required_level = EXCLUDED.required_level,
                    must_have = EXCLUDED.must_have
                """,
                (
                    str(uuid4()),
                    job_id,
                    required_skill.skill_id,
                    required_skill.importance_weight,
                    required_skill.required_level,
                    required_skill.must_have,
                ),
            )
        response = {
            "id": job["id"],
            "title": job["title"],
            "status": job["status"],
            "price_negotiable": job["price_negotiable"],
        }
    return ok(response)


@router.get("")
def list_jobs(
    q: str = "",
    country: str = "",
    city: str = "",
    area: str = "",
    salary_min_minor: int = None,
    salary_max_minor: int = None,
    currency: str = "",
    job_type: str = "",
    workplace_type: str = "",
    career_level: str = "",
    skills: str = "",
    status: str = "",
    include_taken: bool = True,
    sort: str = "created_at_desc",
    page: int = 1,
    limit: int = 20,
    current_user=Depends(get_optional_current_user),
):
    page = max(page, 1)
    limit = min(max(limit, 1), 100)
    offset = (page - 1) * limit

    where = []
    params = []

    if not is_admin(current_user):
        visible_status_sql = "j.status NOT IN ('DRAFT', 'HIDDEN')"
        if current_user is None:
            where.append(f"(j.visibility = 'PUBLIC' AND {visible_status_sql})")
        else:
            where.append(
                f"(j.owner_user_id = %s OR (j.visibility IN ('PUBLIC', 'REGISTERED') AND {visible_status_sql}))"
            )
            params.append(current_user["id"])

    if q:
        where.append("(j.title ILIKE %s OR j.description ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if country:
        where.append("j.country = %s")
        params.append(country)
    if city:
        where.append("j.city = %s")
        params.append(city)
    if area:
        where.append("j.area = %s")
        params.append(area)
    if salary_min_minor is not None:
        where.append("j.salary_max_minor >= %s")
        params.append(salary_min_minor)
    if salary_max_minor is not None:
        where.append("j.salary_min_minor <= %s")
        params.append(salary_max_minor)
    if currency:
        where.append("j.currency = %s")
        params.append(currency)
    if job_type:
        where.append("j.job_type = %s")
        params.append(job_type)
    if workplace_type:
        where.append("j.workplace_type = %s")
        params.append(workplace_type)
    if career_level:
        where.append("j.career_level = %s")
        params.append(career_level)
    if status:
        where.append("j.status = %s")
        params.append(status)
    if not include_taken:
        where.append(
            "NOT EXISTS (SELECT 1 FROM job_assignments ja WHERE ja.job_id = j.id AND ja.status = 'ASSIGNED')"
        )
    if skills:
        skill_ids = [item.strip() for item in skills.split(",") if item.strip()]
        for skill_id in skill_ids:
            where.append(
                "EXISTS (SELECT 1 FROM job_required_skills jrs WHERE jrs.job_id = j.id AND jrs.skill_id = %s)"
            )
            params.append(skill_id)

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    order_sql = "ORDER BY j.created_at DESC"
    if sort == "salary_desc":
        order_sql = "ORDER BY j.salary_max_minor DESC NULLS LAST"
    elif sort == "salary_asc":
        order_sql = "ORDER BY j.salary_min_minor ASC NULLS LAST"

    with get_pg_cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) AS total FROM jobs j {where_sql}", tuple(params))
        total = cursor.fetchone()["total"]

        cursor.execute(
            f"""
            SELECT j.*
            FROM jobs j
            {where_sql}
            {order_sql}
            LIMIT %s OFFSET %s
            """,
            tuple(params + [limit, offset]),
        )
        jobs = []
        for row in cursor.fetchall():
            job = enrich_job(cursor, row, current_user)
            jobs.append(job)
    return ok(jobs, meta={"page": page, "limit": limit, "total": total})


@router.get("/{job_id}")
def get_job(job_id: str, current_user=Depends(get_optional_current_user)):
    with get_pg_cursor() as cursor:
        job = job_exists(cursor, job_id)
        require_job_view(job, current_user)
        response = enrich_job(cursor, job, current_user)
    return ok(response)


@router.patch("/{job_id}")
def update_job(job_id: str, payload: JobUpdate, current_user=Depends(get_current_user)):
    values = payload.dict(exclude_unset=True)
    if not values:
        return get_job(job_id, current_user)

    allowed = [
        "title",
        "description",
        "country",
        "city",
        "area",
        "remote_allowed",
        "workplace_type",
        "job_type",
        "career_level",
        "salary_min_minor",
        "salary_max_minor",
        "currency",
        "salary_period",
        "price_negotiable",
        "visibility",
    ]

    with get_pg_cursor(commit=True) as cursor:
        current = job_exists(cursor, job_id)
        require_job_manager(current, current_user)
        next_min = values.get("salary_min_minor", current.get("salary_min_minor"))
        next_max = values.get("salary_max_minor", current.get("salary_max_minor"))
        validate_salary(next_min, next_max)

        set_parts = []
        params = []
        for field in allowed:
            if field in values:
                set_parts.append(f"{field} = %s")
                params.append(values[field])
        set_parts.append("updated_at = NOW()")
        params.append(job_id)
        cursor.execute(
            f"UPDATE jobs SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
            tuple(params),
        )
        job = enrich_job(cursor, cursor.fetchone())
    return ok(job)


@router.patch("/{job_id}/status")
def update_job_status(job_id: str, payload: JobStatusUpdate, current_user=Depends(get_current_user)):
    with get_pg_cursor(commit=True) as cursor:
        job = job_exists(cursor, job_id)
        require_job_manager(job, current_user)
        current_status = job["status"]
        allowed_next = ALLOWED_JOB_TRANSITIONS.get(current_status, [])
        if payload.status != current_status and payload.status not in allowed_next:
            fail(
                422,
                "INVALID_STATE_TRANSITION",
                f"Cannot change job status from {current_status} to {payload.status}",
                "status",
            )
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
        updated_job = row_to_dict(cursor.fetchone())
        cursor.execute(
            """
            INSERT INTO job_status_history (
                id, job_id, from_status, to_status, changed_by_user_id, note
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                str(uuid4()),
                job_id,
                current_status,
                payload.status,
                current_user["id"],
                payload.note,
            ),
        )
    return ok(updated_job)


@router.patch("/{job_id}/taken-visibility")
def update_taken_visibility(job_id: str, payload: TakenVisibilityUpdate, current_user=Depends(get_current_user)):
    with get_pg_cursor(commit=True) as cursor:
        job = job_exists(cursor, job_id)
        require_job_manager(job, current_user)
        cursor.execute(
            "UPDATE jobs SET taken_visibility = %s, updated_at = NOW() WHERE id = %s RETURNING *",
            (payload.taken_visibility, job_id),
        )
        job = row_to_dict(cursor.fetchone())
        cursor.execute(
            "UPDATE job_assignments SET visibility = %s WHERE job_id = %s",
            (payload.taken_visibility, job_id),
        )
    return ok(job)
