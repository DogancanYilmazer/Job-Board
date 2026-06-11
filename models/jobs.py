from typing import List, Optional

from pydantic import BaseModel, Field


class RequiredSkillInput(BaseModel):
    skill_id: str
    importance_weight: int = Field(1, ge=1)
    required_level: int = Field(1, ge=1, le=5)
    must_have: bool = False


class JobCreate(BaseModel):
    owner_user_id: str
    employer_profile_id: str
    title: str
    description: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    remote_allowed: bool = False
    workplace_type: Optional[str] = None
    job_type: Optional[str] = None
    career_level: Optional[str] = None
    salary_min_minor: Optional[int] = None
    salary_max_minor: Optional[int] = None
    currency: str = "EGP"
    salary_period: str = "PROJECT"
    price_negotiable: bool = True
    visibility: str = "PUBLIC"
    taken_visibility: str = "SHOW_TAKEN_ONLY"
    status: str = "OPEN"
    required_skills: List[RequiredSkillInput] = []


class JobUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    remote_allowed: Optional[bool] = None
    workplace_type: Optional[str] = None
    job_type: Optional[str] = None
    career_level: Optional[str] = None
    salary_min_minor: Optional[int] = None
    salary_max_minor: Optional[int] = None
    currency: Optional[str] = None
    salary_period: Optional[str] = None
    price_negotiable: Optional[bool] = None
    visibility: Optional[str] = None


class JobStatusUpdate(BaseModel):
    status: str
    changed_by_user_id: Optional[str] = None
    note: Optional[str] = None


class TakenVisibilityUpdate(BaseModel):
    taken_visibility: str
