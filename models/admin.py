from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


class UserRoleUpdate(BaseModel):
    role: str
    action: str = "add"  # 'add' or 'remove'

    @validator("role")
    def validate_role(cls, value: str):
        value = value.strip().upper()
        if value not in {"APPLICANT", "EMPLOYER", "ADMIN"}:
            raise ValueError("Invalid role")
        return value

    @validator("action")
    def validate_action(cls, value: str):
        value = value.strip().lower()
        if value not in {"add", "remove"}:
            raise ValueError("Invalid action")
        return value


class UserBlockUpdate(BaseModel):
    is_blocked: bool


class UserStatusAdminUpdate(BaseModel):
    status: str


class JobStatusAdminUpdate(BaseModel):
    status: str
    note: Optional[str] = None


class ApplicationStatusAdminUpdate(BaseModel):
    status: str
    note: Optional[str] = None


class SiteSettingsUpdate(BaseModel):
    site_name: Optional[str] = None
    logo_url: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    default_country: Optional[str] = None
    default_phone_code: Optional[str] = None
    terms_url: Optional[str] = None
    privacy_url: Optional[str] = None
    email_notifications_enabled: Optional[bool] = None


class AdminLogCreate(BaseModel):
    action_type: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
