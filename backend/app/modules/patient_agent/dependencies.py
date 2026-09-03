from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .identity import PatientPrincipal, decode_patient_session_token

_patient_bearer = HTTPBearer(auto_error=False)


async def get_patient_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_patient_bearer)],
) -> PatientPrincipal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Patient authentication required")
    try:
        return decode_patient_session_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid patient session") from exc
