from typing import List, Optional

from pydantic import BaseModel


class SkillCreate(BaseModel):
    canonical_name: str
    category: Optional[str] = None
    aliases: List[str] = []
