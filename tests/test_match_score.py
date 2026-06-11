from utils.match_score import calculate_match_score, get_match_score_for_user


class FakeCursor:
    def __init__(self, required_skills=None, applicant_skills=None, profile_row=None):
        self.required_skills = required_skills or []
        self.applicant_skills = applicant_skills or []
        self.profile_row = profile_row
        self._rows = []
        self._row = None

    def execute(self, query, params=()):
        if "FROM job_required_skills" in query:
            self._rows = self.required_skills
            self._row = None
        elif "FROM applicant_skills" in query:
            self._rows = self.applicant_skills
            self._row = None
        elif "FROM applicant_profiles" in query:
            self._rows = []
            self._row = self.profile_row
        else:
            self._rows = []
            self._row = None

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._row


def test_calculate_match_score_uses_weighted_skill_overlap_and_required_level():
    cursor = FakeCursor(
        required_skills=[
            {
                "skill_id": "python",
                "importance_weight": 3,
                "required_level": 3,
                "must_have": True,
                "canonical_name": "Python",
            },
            {
                "skill_id": "sql",
                "importance_weight": 1,
                "required_level": 2,
                "must_have": False,
                "canonical_name": "SQL",
            },
            {
                "skill_id": "react",
                "importance_weight": 2,
                "required_level": 2,
                "must_have": False,
                "canonical_name": "React",
            },
        ],
        applicant_skills=[
            {"skill_id": "python", "proficiency_level": 4},
            {"skill_id": "sql", "proficiency_level": 1},
        ],
    )

    score, breakdown = calculate_match_score(cursor, "job-1", "profile-1")

    assert score == 50
    assert breakdown["earned_weight"] == 3
    assert breakdown["total_weight"] == 6
    assert breakdown["matched_skills"] == ["Python"]
    assert breakdown["missing_skills"] == ["SQL", "React"]
    assert breakdown["must_have_missing"] == []


def test_calculate_match_score_handles_empty_required_skills_as_zero_percent():
    cursor = FakeCursor(required_skills=[], applicant_skills=[])

    score, breakdown = calculate_match_score(cursor, "job-1", "profile-1")

    assert score == 0
    assert breakdown["reason"] == "job_has_no_required_skills"
    assert breakdown["total_weight"] == 0


def test_get_match_score_for_user_without_profile_returns_zero_percent_payload():
    cursor = FakeCursor(
        required_skills=[
            {
                "skill_id": "python",
                "importance_weight": 2,
                "required_level": 3,
                "must_have": True,
                "canonical_name": "Python",
            },
        ],
        profile_row=None,
    )

    payload = get_match_score_for_user(cursor, "job-1", "user-1")

    assert payload["match_score"] == 0
    assert payload["match_score_breakdown"]["reason"] == "applicant_profile_not_found"
    assert payload["match_score_breakdown"]["applicant_profile_found"] is False
    assert payload["match_score_breakdown"]["missing_skills"] == ["Python"]
    assert payload["match_score_breakdown"]["total_required_skills"] == 1
