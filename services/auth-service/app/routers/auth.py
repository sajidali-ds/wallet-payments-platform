from fastapi import APIRouter, status

from app.dependencies import CurrentUserDep, PoolDep, SettingsDep
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, pool: PoolDep, settings: SettingsDep) -> UserResponse:
    user = await auth_service.register_user(
        pool, settings, email=body.email, password=body.password
    )
    return UserResponse.model_validate(dict(user))


@router.post("/login")
async def login(body: LoginRequest, pool: PoolDep, settings: SettingsDep) -> TokenResponse:
    token = await auth_service.authenticate(
        pool, settings, email=body.email, password=body.password
    )
    return TokenResponse(access_token=token, expires_in=settings.jwt_expire_minutes * 60)


@router.get("/me")
async def me(user: CurrentUserDep) -> UserResponse:
    return UserResponse.model_validate(dict(user))
