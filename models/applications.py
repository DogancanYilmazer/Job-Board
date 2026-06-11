from typing import Optional

from pydantic import BaseModel


class ApplicationCreate(BaseModel):
    applicant_user_id: Optional[str] = None
    cover_letter: Optional[str] = None
    proposed_amount_minor: Optional[int] = None
    proposed_currency: str = "EGP"


class ApplicationStatusUpdate(BaseModel):
    status: str
    changed_by_user_id: Optional[str] = None
    note: Optional[str] = None


class WithdrawApplication(BaseModel):
    applicant_user_id: Optional[str] = None
    reason: Optional[str] = None
