from typing import List, Optional

from pydantic import BaseModel, Field


class ApplicantSkillInput(BaseModel):
    skill_id: str
    proficiency_level: int = Field(1, ge=1, le=5)
    years_experience: float = Field(0, ge=0)


class ApplicantProfileUpsert(BaseModel):
    headline: Optional[str] = None
    bio: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    expected_salary_min_minor: Optional[int] = None
    expected_salary_max_minor: Optional[int] = None
    currency: str = "EGP"
    availability: str = "OPEN_TO_WORK"
    visibility: str = "PUBLIC"
    cv_url: Optional[str] = None
    skills: List[ApplicantSkillInput] = []


class EmployerProfileUpsert(BaseModel):
    display_name: Optional[str] = None
    company_name: Optional[str] = None
    website_url: Optional[str] = None
    bio: Optional[str] = None
