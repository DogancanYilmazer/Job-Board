from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator, validator


VALID_USER_ROLES = {"APPLICANT", "EMPLOYER", "ADMIN"}


class User(BaseModel):
    id: str
    email: str
    username: Optional[str] = None
    password: str
    full_name: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    status: str = "ONBOARDING"
    onboarding_status: str = "IN_PROGRESS"
    preferred_locale: str = "tr"
    otp_secret: Optional[str] = None
    otp_enabled: bool = False
    otp_verified: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


class UserCreate(BaseModel):
    email: str = Field(..., min_length=3)
    username: Optional[str] = Field(None, min_length=3, max_length=30)
    password: str = Field(..., min_length=8)
    full_name: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    roles: List[str] = Field(default_factory=lambda: ["APPLICANT"])

    @validator("username")
    def validate_username(cls, value: Optional[str]):
        if value is None:
            return value
        value = value.strip().lower()
        if not value:
            return None
        if not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Username can only contain letters, numbers, underscores, and hyphens")
        if len(value) < 3:
            raise ValueError("Username must be at least 3 characters")
        return value

    @validator("email")
    def validate_email(cls, value: str):
        value = value.strip()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("Please enter a valid email address")
        return value

    @validator("roles", pre=True, always=True)
    def validate_roles(cls, value):
        roles = value or ["APPLICANT"]
        if isinstance(roles, str):
            roles = [roles]

        normalized_roles = []
        for role in roles:
            if role not in VALID_USER_ROLES:
                raise ValueError(f"Invalid role: {role}")
            if role not in normalized_roles:
                normalized_roles.append(role)

        if not normalized_roles:
            raise ValueError("Please select at least one role")
        if len(normalized_roles) > 1:
            raise ValueError("You can only select one role (Job Seeker or Employer)")
        return normalized_roles

    class Config:
        extra = "forbid"


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    preferred_locale: Optional[str] = None


class UserStatusUpdate(BaseModel):
    status: str
    reason: Optional[str] = None


class UserLogin(BaseModel):
    email: Optional[str] = None
    username: Optional[str] = None
    password: str = Field(..., min_length=1)
    remember_me: Optional[bool] = False

    @model_validator(mode="before")
    def validate_login_identifier(cls, values):
        if not isinstance(values, dict):
            return values
        email = values.get("email")
        username = values.get("username")
        if not email and not username:
            raise ValueError("Please enter an email or username")
        if email:
            email = email.strip()
            if "@" not in email or email.startswith("@") or email.endswith("@"):
                raise ValueError("Please enter a valid email address")
            values["email"] = email
        if username:
            username = username.strip().lower()
            if len(username) < 3:
                raise ValueError("Username must be at least 3 characters")
            values["username"] = username
        return values


class TwoFactorCode(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)

    @validator("code")
    def validate_code(cls, value: str):
        value = value.strip()
        if not value.isdigit() or len(value) != 6:
            raise ValueError("Please enter the 6-digit verification code")
        return value


class TwoFactorLogin(TwoFactorCode):
    temp_token: str = Field(..., min_length=10)
    remember_me: Optional[bool] = False


class UserPreferenceUpdate(BaseModel):
    hide_taken_jobs: Optional[bool] = None
    profile_visibility: Optional[str] = None
    notification_settings: Optional[Dict[str, Any]] = None


class OnboardingStepUpdate(BaseModel):
    status: str
    data: Dict[str, Any] = {}
