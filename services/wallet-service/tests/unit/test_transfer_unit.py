from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.transfer import TransferRequest
from app.services.transfer_service import request_hash


def test_same_request_gives_the_same_hash():
    wallet = uuid4()
    assert request_hash(wallet, 500) == request_hash(wallet, 500)


def test_hash_changes_with_amount_or_recipient():
    wallet = uuid4()
    assert request_hash(wallet, 500) != request_hash(wallet, 501)
    assert request_hash(wallet, 500) != request_hash(uuid4(), 500)


def test_hash_is_a_sha256_hex_digest():
    assert len(request_hash(uuid4(), 1)) == 64


def test_transfer_request_accepts_valid_input():
    wallet = uuid4()
    body = TransferRequest(to_wallet_id=wallet, amount=100)
    assert (body.to_wallet_id, body.amount) == (wallet, 100)


def test_transfer_request_cannot_name_a_sender():
    with pytest.raises(ValidationError):
        TransferRequest(to_wallet_id=uuid4(), amount=100, from_wallet_id=uuid4())


@pytest.mark.parametrize("amount", [0, -1, 1.5, "10", True, None])
def test_transfer_request_rejects_bad_amounts(amount):
    with pytest.raises(ValidationError):
        TransferRequest(to_wallet_id=uuid4(), amount=amount)


def test_transfer_request_rejects_bad_wallet_id():
    with pytest.raises(ValidationError):
        TransferRequest(to_wallet_id="nope", amount=100)
