"""The contract of the events this service consumes (published by wallet-service)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class TransferCompletedData(BaseModel):
    # ignore: fields added by a newer wallet-service must not break this (older) consumer.
    model_config = ConfigDict(extra="ignore")

    transfer_id: UUID
    type: Literal["transfer", "deposit"]
    from_wallet_id: UUID
    from_user_id: UUID | None  # None for deposits: the money comes from the system wallet
    to_wallet_id: UUID
    to_user_id: UUID
    amount: Annotated[StrictInt, Field(gt=0)]  # integer paise
    currency: str


class EventEnvelope(BaseModel):
    event_id: UUID  # the dedupe key
    event_type: Literal["transfer.completed"]
    request_id: str | None = None  # correlation id of the HTTP request that caused the event
    occurred_at: datetime
    data: TransferCompletedData
