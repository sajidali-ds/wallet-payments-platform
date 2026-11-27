from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.wallet import Amount


class TransferRequest(BaseModel):
    # forbid: a body containing "from_wallet_id" is rejected. The sender is ALWAYS the caller's
    # own wallet (taken from the JWT), so nobody can spend from someone else's wallet.
    model_config = ConfigDict(extra="forbid")

    to_wallet_id: UUID
    amount: Amount  # integer paise


class TransferResponse(BaseModel):
    transfer_id: UUID
    from_wallet_id: UUID
    to_wallet_id: UUID
    amount: int
    balance_after: int  # the sender's balance after this transfer
    created_at: datetime
