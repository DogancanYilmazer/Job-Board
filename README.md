# FastAPI Job Board API

pip install -r requirements.txt
uvicorn main:app --reload



POSTGRES_DSN=postgresql://postgres:[database_password]@localhost:5432/job_board_db
MONGO_URI=mongodb://localhost:27017


## Skills Match Score

The backend calculates `match_score` without machine learning. It compares the
skill IDs on an applicant profile with the required skill IDs on a job posting.

Formula:

```text
match_score = round((earned_weight / total_weight) * 100)
```

- `total_weight` is the sum of each required skill's `importance_weight`.
- `earned_weight` is the sum of weights for required skills the applicant has
  at or above the job's `required_level`.
- The result is clamped to a percentage between 0 and 100.

Edge cases:

- If the job has no required skills, the score is `0`.
- If the applicant has no profile or no skills, the score is `0`; required
  skills are treated as missing.
- Invalid or old weight values below `1` are normalized to `1`.

Limitations:

- This is exact skill-ID matching, not semantic matching.
- Skill aliases help users find/create skills, but the score only compares the
  stored canonical skill IDs.
- It does not consider resumes, job description text, years of experience, or
  soft skills unless they are represented as structured skills.
