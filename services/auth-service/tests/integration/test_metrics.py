from prometheus_client import REGISTRY

PASSWORD = "correct-horse-battery"


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def _register(client, email="alice@example.com"):
    return await client.post("/auth/register", json={"email": email, "password": PASSWORD})


async def _login(client, password=PASSWORD):
    return await client.post(
        "/auth/login", json={"email": "alice@example.com", "password": password}
    )


async def test_registrations_and_logins_are_counted_by_result(client, pool):
    registrations = sample("auth_registrations_total")
    success = sample("auth_logins_total", result="success")
    failed = sample("auth_logins_total", result="failed")
    disabled = sample("auth_logins_total", result="disabled")

    await _register(client)
    await _login(client)
    await _login(client, password="wrong-password-1")
    await _login(client, password="wrong-password-2")
    await pool.execute("UPDATE users SET is_active = FALSE")
    await _login(client)

    assert sample("auth_registrations_total") - registrations == 1
    assert sample("auth_logins_total", result="success") - success == 1
    assert sample("auth_logins_total", result="failed") - failed == 2
    assert sample("auth_logins_total", result="disabled") - disabled == 1


async def test_duplicate_registration_shows_up_as_a_business_error(client):
    labels = {"code": "email_already_registered", "status": "409"}
    before = sample("app_errors_total", **labels)

    await _register(client)
    await _register(client)

    assert sample("app_errors_total", **labels) - before == 1
