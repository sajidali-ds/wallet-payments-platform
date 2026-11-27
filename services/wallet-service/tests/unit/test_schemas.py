import pytest
from pydantic import ValidationError

from app.schemas.wallet import MAX_AMOUNT_PAISE, DepositRequest


@pytest.mark.parametrize("amount", [1, 5000, MAX_AMOUNT_PAISE])
def test_deposit_accepts_positive_integers(amount):
    assert DepositRequest(amount=amount).amount == amount


@pytest.mark.parametrize(
    "amount",
    [0, -1, 10.5, 100.0, "100", True, None, MAX_AMOUNT_PAISE + 1],
)
def test_deposit_rejects_everything_else(amount):
    with pytest.raises(ValidationError):
        DepositRequest(amount=amount)


def test_deposit_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        DepositRequest(amount=100, currency="USD")
