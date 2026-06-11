from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SavedJobCreate(BaseModel):
    user_id: Optional[str] = None
    job_id: str
    note: Optional[str] = None
    tags: List[str] = []


class SearchHistoryCreate(BaseModel):
    user_id: Optional[str] = None
    query: str
    filters: Dict[str, Any] = {}
    result_count: int = 0
    clicked_job_ids: List[str] = []


class ConversationCreate(BaseModel):
    job_id: str
    application_id: Optional[str] = None
    owner_user_id: Optional[str] = None
    applicant_user_id: Optional[str] = None


class ConversationUpdate(BaseModel):
    status: Optional[str] = None
    last_message_at: Optional[str] = None


class MessageAttachment(BaseModel):
    type: str = "FILE"
    url: str


class MessageCreate(BaseModel):
    sender_user_id: Optional[str] = None
    body: str
    attachments: List[MessageAttachment] = []
