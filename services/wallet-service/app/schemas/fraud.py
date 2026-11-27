from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class FraudFlagResponse(BaseModel):
    id: UUID
    user_id: UUID
    rule: str
    transfer_count: int
    window_seconds: int
    triggering_transfer_id: UUID
    created_at: datetime
