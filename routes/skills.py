from uuid import uuid4

from fastapi import APIRouter, Depends

from database.connection import get_pg_cursor
from models.skills import SkillCreate
from utils.responses import fail, ok, row_to_dict, rows_to_list
from utils.security import get_current_user, require_admin

router = APIRouter(prefix="/skills", tags=["skills"])


def normalize(value: str) -> str:
    return value.strip().lower().replace(" ", "-")


@router.get("")
def search_skills(q: str = ""):
    with get_pg_cursor() as cursor:
        if q:
            pattern = f"%{q}%"
            cursor.execute(
                """
                SELECT DISTINCT s.id, s.canonical_name, s.category
                FROM skills s
                LEFT JOIN skill_aliases a ON a.skill_id = s.id
                WHERE s.canonical_name ILIKE %s OR a.alias ILIKE %s
                ORDER BY s.canonical_name
                LIMIT 50
                """,
                (pattern, pattern),
            )
        else:
            cursor.execute(
                "SELECT id, canonical_name, category FROM skills ORDER BY canonical_name LIMIT 50"
            )
        return ok(rows_to_list(cursor.fetchall()))


@router.post("", status_code=201)
def create_skill(payload: SkillCreate, current_user=Depends(get_current_user)):
    require_admin(current_user)
    skill_id = str(uuid4())
    try:
        with get_pg_cursor(commit=True) as cursor:
            cursor.execute(
                """
                INSERT INTO skills (id, canonical_name, normalized_name, category)
                VALUES (%s, %s, %s, %s)
                RETURNING id, canonical_name, category
                """,
                (skill_id, payload.canonical_name, normalize(payload.canonical_name), payload.category),
            )
            skill = row_to_dict(cursor.fetchone())
            for alias in payload.aliases:
                cursor.execute(
                    """
                    INSERT INTO skill_aliases (id, skill_id, alias, normalized_alias)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (normalized_alias) DO NOTHING
                    """,
                    (str(uuid4()), skill_id, alias, normalize(alias)),
                )
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            fail(409, "SKILL_ALREADY_EXISTS", "Skill already exists", "canonical_name")
        raise
    return ok(skill)
