from datetime import datetime
from typing import Annotated, Optional
from uuid import UUID

from pydantic import AfterValidator, BaseModel, EmailStr, Field, field_validator

from backend.core.validators import require_nonblank_name

# passlib refuses anything over 4096 characters by raising, which would be a
# 500 from any endpoint that hashes or verifies a password. New passwords are
# capped far lower (bcrypt only uses the first 72 bytes anyway); the login cap
# is passlib's own limit so an existing long password can still sign in.
# Addresses are stored and compared in lower case: `Bob@x.com` and `bob@x.com`
# reach the same inbox, so they must be the same account. Applied to every
# email a client sends (the database also refuses a non-lower-case row).
NormalizedEmail = Annotated[EmailStr, AfterValidator(lambda value: value.lower())]

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
LOGIN_PASSWORD_MAX_LENGTH = 4096


class SignupRequest(BaseModel):
    email: NormalizedEmail
    password: str = Field(
        ..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH
    )
    name: str = Field(..., min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return require_nonblank_name(value)


class LoginRequest(BaseModel):
    email: NormalizedEmail
    password: str = Field(..., max_length=LOGIN_PASSWORD_MAX_LENGTH)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    avatar_url: Optional[str] = None
    provider: str
    email_verified_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UpdateUserRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: Optional[str]) -> Optional[str]:
        return require_nonblank_name(value) if value is not None else value


class MessageResponse(BaseModel):
    detail: str


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=2048)


class ForgotPasswordRequest(BaseModel):
    email: NormalizedEmail


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=2048)
    new_password: str = Field(
        ..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH
    )
