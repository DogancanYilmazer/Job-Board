"""Algorithmic match-score calculation between applicant profiles and job postings.

No machine learning is used.  The score is a weighted percentage computed from
set-intersection of the applicant's skills vs. the job's required skills.
"""

from typing import Any, Dict, Optional, Tuple

from utils.responses import rows_to_list


def _positive_weight(value: Any) -> int:
    try:
        weight = int(value)
    except (TypeError, ValueError):
        return 1
    return max(weight, 1)


def _positive_level(value: Any) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError):
        return 1
    return max(level, 1)


def _clamp_percentage(value: float) -> int:
    return max(0, min(100, int(round(value))))


def empty_match_payload(reason: str) -> Dict[str, Any]:
    return {
        "match_score": 0,
        "match_score_breakdown": {
            "matched_skills": [],
            "missing_skills": [],
            "must_have_missing": [],
            "matched_required_skills": 0,
            "total_required_skills": 0,
            "earned_weight": 0,
            "total_weight": 0,
            "formula": "round((earned_weight / total_weight) * 100)",
            "reason": reason,
        },
    }


def calculate_match_score(
    cursor, job_id: str, applicant_profile_id: Optional[str]
) -> Tuple[int, Dict[str, Any]]:
    """Return (score_0_100, breakdown_dict) for a given job + applicant profile.

    The algorithm:
    1. Fetch every required skill for the job (with importance_weight,
       required_level, must_have).
    2. Fetch the applicant's skills as a mapping skill_id -> proficiency_level.
    3. For each required skill:
       - total_weight += importance_weight
       - If the applicant has the skill AND proficiency_level >= required_level:
           earned_weight += importance_weight
         Else:
           skill is missing; if must_have, add to must_have_missing list.
    4. score = round((earned_weight / total_weight) * 100), clamped to 0..100.
    """
    cursor.execute(
        """
        SELECT
            jrs.skill_id,
            jrs.importance_weight,
            jrs.required_level,
            jrs.must_have,
            s.canonical_name
        FROM job_required_skills jrs
        JOIN skills s ON s.id = jrs.skill_id
        WHERE jrs.job_id = %s
        """,
        (job_id,),
    )
    required_skills = rows_to_list(cursor.fetchall())

    cursor.execute(
        """
        SELECT skill_id, proficiency_level
        FROM applicant_skills
        WHERE applicant_profile_id = %s
        """,
        (applicant_profile_id,),
    )
    applicant_skills = {
        str(row["skill_id"]): _positive_level(row["proficiency_level"])
        for row in cursor.fetchall()
    }

    if not required_skills:
        breakdown = empty_match_payload("job_has_no_required_skills")[
            "match_score_breakdown"
        ]
        return 0, breakdown

    total_weight = sum(
        _positive_weight(item.get("importance_weight")) for item in required_skills
    )
    earned_weight = 0
    matched = []
    missing = []
    must_have_missing = []

    for skill in required_skills:
        skill_id = str(skill["skill_id"])
        applicant_level = applicant_skills.get(skill_id)
        required_level = _positive_level(skill.get("required_level"))
        if applicant_level is not None and applicant_level >= required_level:
            earned_weight += _positive_weight(skill.get("importance_weight"))
            matched.append(skill["canonical_name"])
        else:
            missing.append(skill["canonical_name"])
            if skill["must_have"]:
                must_have_missing.append(skill["canonical_name"])

    score = _clamp_percentage((earned_weight / total_weight) * 100)
    return score, {
        "matched_skills": matched,
        "missing_skills": missing,
        "must_have_missing": must_have_missing,
        "matched_required_skills": len(matched),
        "total_required_skills": len(required_skills),
        "earned_weight": earned_weight,
        "total_weight": total_weight,
        "formula": "round((earned_weight / total_weight) * 100)",
    }


def get_match_score_for_user(cursor, job_id: str, user_id: str) -> Dict[str, Any]:
    """Return match-score payload for a job when viewed by a specific user.

    A missing applicant profile is scored as 0 because the user has no skills
    to intersect with the job requirements yet.
    """
    cursor.execute(
        "SELECT id FROM applicant_profiles WHERE user_id = %s",
        (user_id,),
    )
    row = cursor.fetchone()
    if row is None:
        score, breakdown = calculate_match_score(cursor, job_id, None)
        breakdown["applicant_profile_found"] = False
        breakdown["reason"] = "applicant_profile_not_found"
        return {
            "match_score": score,
            "match_score_breakdown": breakdown,
        }

    profile_id = str(row["id"])
    score, breakdown = calculate_match_score(cursor, job_id, profile_id)
    breakdown["applicant_profile_found"] = True

    # If the job has zero required skills we still return a score of 0,
    # but the caller (enrich_job) can choose to hide the badge when
    # required_skills is empty.  We include the breakdown either way.
    return {
        "match_score": score,
        "match_score_breakdown": breakdown,
    }
