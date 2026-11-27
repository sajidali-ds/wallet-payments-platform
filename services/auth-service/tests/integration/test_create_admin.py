from app.config import get_settings
from app.create_admin import create_admin
from app.security import decode_access_token

PASSWORD = "correct-horse-battery"


async def test_create_admin_makes_a_user_with_admin_role(pool):
    user_id = await create_admin(get_settings(), email="root@example.com", password=PASSWORD)
    assert await pool.fetchval("SELECT role FROM users WHERE id = $1", user_id) == "admin"


async def test_create_admin_promotes_an_existing_user_and_keeps_their_password(client, pool):
    await client.post("/auth/register", json={"email": "bob@example.com", "password": PASSWORD})
    user_id = await create_admin(
        get_settings(), email="bob@example.com", password="another-password-1"
    )

    assert await pool.fetchval("SELECT role FROM users WHERE id = $1", user_id) == "admin"
    login = await client.post(
        "/auth/login", json={"email": "bob@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200  # the original password still works


async def test_admin_token_carries_the_admin_role(client):
    await create_admin(get_settings(), email="root@example.com", password=PASSWORD)
    login = await client.post(
        "/auth/login", json={"email": "root@example.com", "password": PASSWORD}
    )
    claims = decode_access_token(login.json()["access_token"], get_settings())
    assert claims["role"] == "admin"
