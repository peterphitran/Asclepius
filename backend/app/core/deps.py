import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db import get_session
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_credentials_error = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: SessionDep,
) -> User:
    try:
        payload = decode_access_token(token)
        subject = payload.get("sub")
    except InvalidTokenError:
        raise _credentials_error from None

    if subject is None:
        raise _credentials_error

    user = await session.get(User, uuid.UUID(subject))
    if user is None:
        raise _credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
