from typing import Optional

from pydantic import BaseModel


class PriceProposalCreate(BaseModel):
    application_id: Optional[str] = None
    proposer_user_id: Optional[str] = None
    receiver_user_id: Optional[str] = None
    amount_minor: int
    currency: str = "EGP"
    message: Optional[str] = None
    expires_at: Optional[str] = None


class OfferCreate(BaseModel):
    owner_user_id: Optional[str] = None
    amount_minor: int
    currency: str = "EGP"
    terms: Optional[str] = None
    expires_at: Optional[str] = None


class OfferReject(BaseModel):
    reason: Optional[str] = None


class FundContract(BaseModel):
    payment_method_id: Optional[str] = None
    actor_user_id: Optional[str] = None


class CancelContract(BaseModel):
    requested_by_user_id: Optional[str] = None
    requested_by_role: str
    reason: Optional[str] = None


class RatingCreate(BaseModel):
    rater_user_id: Optional[str] = None
    ratee_user_id: str
    rating: int
    comment: Optional[str] = None
    role_context: Optional[str] = None
