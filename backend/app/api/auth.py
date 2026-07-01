from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.auth import create_access_token, get_current_user, hash_password, verify_password
from app.dependencies.database import DbSession
from app.models.core import User
from app.schemas.auth import AuthCredentials, AuthResponse, UserRead


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: AuthCredentials, db: DbSession) -> AuthResponse:
    user = User(email=_normalize_email(payload.email), password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists") from exc
    db.refresh(user)
    return AuthResponse(access_token=create_access_token(user), user=_user_read(user))


@router.post("/login", response_model=AuthResponse)
def login(payload: AuthCredentials, db: DbSession) -> AuthResponse:
    user = db.scalar(select(User).where(User.email == _normalize_email(payload.email)))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    return AuthResponse(access_token=create_access_token(user), user=_user_read(user))


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> UserRead:
    return _user_read(user)


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if "@" not in normalized or "." not in normalized.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email")
    return normalized


def _user_read(user: User) -> UserRead:
    return UserRead(id=user.id, email=user.email, created_at=user.created_at)
