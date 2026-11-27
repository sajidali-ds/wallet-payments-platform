from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt

# 10_000_000_000 paise = INR 100,000,000. A cap stops fat-finger amounts and keeps sums far
# away from the BIGINT limit.
MAX_AMOUNT_PAISE = 10_000_000_000

# StrictInt: JSON 100 is accepted; 100.0, "100" and true are rejected (no silent coercion).
Amount = Annotated[StrictInt, Field(gt=0, le=MAX_AMOUNT_PAISE)]


class DepositRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Amount  # integer paise


class WalletResponse(BaseModel):
    id: UUID
    user_id: UUID
    currency: str
    balance: int  # paise
    created_at: datetime


class BalanceResponse(BaseModel):
    wallet_id: UUID
    currency: str
    balance: int  # paise


class DepositResponse(BaseModel):
    transfer_id: UUID
    wallet_id: UUID
    amount: int
    balance_after: int
    created_at: datetime


class TransactionItem(BaseModel):
    entry_id: int
    transfer_id: UUID
    type: Literal["transfer", "deposit"]
    amount: int  # signed paise: positive = money in, negative = money out
    balance_after: int
    counterparty_wallet_id: UUID
    created_at: datetime


class TransactionPage(BaseModel):
    items: list[TransactionItem]
    next_cursor: int | None  # pass as ?cursor= to get the next (older) page; null = no more
