import pytest

from app.exceptions import RateLimited


@pytest.mark.parametrize(
    ("retry_after_ms", "header"), [(1, "1"), (999, "1"), (1000, "1"), (1001, "2"), (59_500, "60")]
)
def test_retry_after_is_rounded_up_to_whole_seconds(retry_after_ms, header):
    error = RateLimited(retry_after_ms)
    assert error.status_code == 429
    assert error.headers == {"Retry-After": header}
