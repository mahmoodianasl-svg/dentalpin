"""Authentication router with rate limiting."""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import quote
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.plugins import module_registry
from app.core.schemas import ApiResponse, PaginatedApiResponse
from app.database import get_db

from .dependencies import ClinicContext, get_clinic_context, get_current_user, require_permission
from .mfa import (
    MFA_ACCOUNT_CHALLENGE_WINDOW,
    MFA_ACCOUNT_MAX_FAILURES,
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_recovery_codes,
    generate_totp_secret,
    hash_pending_challenge,
    hash_recovery_code,
    issue_pending_challenge,
    load_staff_mfa_key_material,
    pending_challenge_is_usable,
    verify_totp,
)
from .models import (
    Clinic,
    ClinicMembership,
    RefreshSession,
    StaffMfaChallenge,
    StaffMfaFactor,
    StaffMfaRecoveryCode,
    User,
)
from .permissions import (
    CORE_PERMISSIONS,
    PROFESSIONAL_ROLES,
    ROLES,
    expand_permissions,
    get_role_permissions,
)
from .schemas import (
    AuthResponse,
    BeginMfaEnrollmentRequest,
    BeginMfaEnrollmentResponse,
    ClinicMetadataResponse,
    ClinicMetadataUpdate,
    ClinicResponse,
    CompleteMfaRequest,
    ConfirmMfaEnrollmentRequest,
    ConfirmMfaEnrollmentResponse,
    MeResponse,
    PendingMfaResponse,
    ProfessionalResponse,
    RotateMfaRecoveryCodesRequest,
    RotateMfaRecoveryCodesResponse,
    SetupStatusResponse,
    StaffMfaStatusResponse,
    SystemSetup,
    TokenResponse,
    UserCreate,
    UserResponse,
    UserUpdate,
    UserWithRoleResponse,
)
from .service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    refresh_credential_hash,
    validate_staff_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
# Rate limiting guards production. Dev + test disable it so local flows
# (manual clicking, Playwright E2E, pytest) don't run into 5/minute
# caps after a handful of reloads.
_limiter_enabled = settings.ENVIRONMENT == "production" and not settings.TESTING
limiter = Limiter(key_func=get_remote_address, enabled=_limiter_enabled)

# Serialize the one-time installation claim across backend replicas.  The
# transaction-scoped PostgreSQL lock is released by the setup commit (or by a
# rollback), so a competing request re-checks initialized state after waiting.
_SETUP_ADVISORY_LOCK_ID = int.from_bytes(b"DPNSETUP", "big")
_REFRESH_COOKIE_NAME = "dentalpin_refresh"
_CSRF_COOKIE_NAME = "dentalpin_csrf"
_CSRF_HEADER_NAME = "X-DentalPin-CSRF-Token"


def _cookie_secure() -> bool:
    return settings.ENVIRONMENT.lower() == "production"


def _set_session_cookies(
    response: Response,
    refresh_token: str,
    *,
    csrf_token: str | None = None,
) -> str:
    """Write the protected refresh credential and readable CSRF nonce."""
    max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    csrf_token = csrf_token or secrets.token_urlsafe(32)
    common = {
        "max_age": max_age,
        "secure": _cookie_secure(),
        "samesite": "strict",
        "path": "/",
    }
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        **common,
    )
    response.set_cookie(
        key=_CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        **common,
    )
    response.headers["Cache-Control"] = "no-store"
    return csrf_token


async def _create_browser_session(
    db: AsyncSession, user: User, *, mfa_verified_at: datetime | None = None
) -> str:
    """Persist the credential before exposing it to the browser."""
    now = datetime.now(UTC)
    session = RefreshSession(
        user_id=user.id,
        created_at=now,
        mfa_verified_at=mfa_verified_at,
        absolute_expires_at=now + timedelta(days=settings.REFRESH_SESSION_ABSOLUTE_DAYS),
    )
    session.id = uuid4()
    token = create_refresh_token(
        user.id,
        token_version=user.token_version,
        session_id=session.id,
        absolute_expires_at=session.absolute_expires_at,
    )
    session.credential_hash = refresh_credential_hash(token)
    db.add(session)
    await db.commit()
    return token


def _clear_session_cookies(response: Response) -> None:
    """Expire both browser session cookies."""
    response.delete_cookie(_REFRESH_COOKIE_NAME, path="/")
    response.delete_cookie(_CSRF_COOKIE_NAME, path="/")
    response.headers["Cache-Control"] = "no-store"


def _verify_csrf(request: Request, presented_token: str | None) -> str:
    """Validate the double-submit nonce for cookie-authenticated requests."""
    cookie_token = request.cookies.get(_CSRF_COOKIE_NAME)
    if (
        cookie_token is None
        or presented_token is None
        or not secrets.compare_digest(
            cookie_token.encode("utf-8"),
            presented_token.encode("utf-8"),
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )
    return cookie_token


def _verify_setup_token(presented_token: str | None) -> None:
    """Fail closed unless the operator supplied the configured setup secret."""
    configured_token = settings.SETUP_TOKEN
    if len(configured_token) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="First-run setup is disabled until SETUP_TOKEN is configured",
        )
    if presented_token is None or not secrets.compare_digest(
        presented_token.encode("utf-8"),
        configured_token.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid setup token",
        )


async def _refresh_rate_key(request: Request) -> str:
    """Key the refresh limiter by user, not IP.

    A shared edge proxy (Cloudflare → Nuxt SSR → backend) collapses every
    real client to the same socket peer, so an IP-keyed limiter caps the
    whole tenant after a handful of refreshes. Decoding the refresh token
    here gives a per-user bucket; we fall back to the proxy-aware client
    IP if the body is missing or unreadable.
    """
    try:
        token = request.cookies.get(_REFRESH_COOKIE_NAME)
        if token:
            payload = decode_token(token)
            sub = payload.get("sub")
            if sub:
                return f"refresh:{sub}"
    except Exception:
        pass
    return get_remote_address(request)


def _mfa_enrollment_rate_key(request: Request) -> str:
    """Give authenticated staff separate rate buckets behind a shared proxy."""
    try:
        scheme, token = request.headers.get("Authorization", "").split(" ", 1)
        if scheme.lower() == "bearer":
            payload = decode_token(token)
            if payload.get("type") == "access" and payload.get("sub"):
                return f"mfa-enrollment:{payload['sub']}"
    except (JWTError, ValueError):
        pass
    return get_remote_address(request)


@router.get("/setup/status", response_model=ApiResponse[SetupStatusResponse])
async def setup_status(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SetupStatusResponse]:
    """Whether the system already has an account (drives the first-run wizard)."""
    count = await db.scalar(select(func.count()).select_from(User))
    return ApiResponse(data=SetupStatusResponse(initialized=bool(count)))


@router.post("/setup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/hour")
async def setup(
    request: Request,
    response: Response,
    data: SystemSetup,
    db: Annotated[AsyncSession, Depends(get_db)],
    setup_token: Annotated[str | None, Header(alias="X-DentalPin-Setup-Token")] = None,
) -> TokenResponse:
    """First-run: create the first admin account and its clinic, then log them in.

    The claim requires an operator-provisioned secret and is serialized across
    replicas. Once any user exists the endpoint self-closes with 409.
    """
    _verify_setup_token(setup_token)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": _SETUP_ADVISORY_LOCK_ID},
    )
    existing = await db.scalar(select(func.count()).select_from(User))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="System already initialized",
        )

    is_valid, error_msg = validate_staff_password(data.admin_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_msg,
        )

    clinic = Clinic(
        name=data.clinic_name,
        tax_id=data.clinic_tax_id,
        timezone=data.timezone or "Europe/Madrid",
        currency=data.currency or "EUR",
    )
    db.add(clinic)
    await db.flush()

    user = User(
        email=data.admin_email,
        password_hash=hash_password(data.admin_password),
        first_name=data.admin_first_name,
        last_name=data.admin_last_name,
    )
    db.add(user)
    await db.flush()

    db.add(ClinicMembership(user_id=user.id, clinic_id=clinic.id, role="admin"))
    await db.commit()

    access_token = create_access_token(
        user.id, clinic_id=clinic.id, token_version=user.token_version
    )
    refresh_token = await _create_browser_session(db, user)

    _set_session_cookies(response, refresh_token)
    return TokenResponse(access_token=access_token)


@router.post("/login", response_model=TokenResponse | PendingMfaResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse | PendingMfaResponse:
    """Login and get access tokens."""
    # Find user by email
    result = await db.execute(
        select(User).options(selectinload(User.memberships)).where(User.email == form_data.username)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    enrolled = await db.scalar(
        select(StaffMfaFactor.id).where(
            StaffMfaFactor.user_id == user.id,
            StaffMfaFactor.enrolled_at.is_not(None),
        )
    )
    if enrolled is not None:
        challenge, record = issue_pending_challenge(
            user_id=user.id, purpose="login", now=datetime.now(UTC)
        )
        db.add(record)
        await db.commit()
        response.headers["Cache-Control"] = "no-store"
        return PendingMfaResponse(challenge=challenge)

    # Get first clinic ID if user has any membership
    clinic_id = None
    if user.memberships:
        clinic_id = user.memberships[0].clinic_id

    # Generate tokens
    access_token = create_access_token(
        user.id,
        clinic_id=clinic_id,
        token_version=user.token_version,
    )
    refresh_token = await _create_browser_session(db, user)

    _set_session_cookies(response, refresh_token)
    return TokenResponse(access_token=access_token)


@router.post("/mfa/complete", response_model=TokenResponse)
@limiter.limit("5/minute")
async def complete_mfa_login(
    request: Request,
    response: Response,
    data: CompleteMfaRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Consume a password-verified login challenge and a TOTP or recovery code."""
    invalid = HTTPException(status_code=401, detail="Invalid or expired MFA challenge or code")
    record = await db.scalar(
        select(StaffMfaChallenge)
        .where(StaffMfaChallenge.challenge_hash == hash_pending_challenge(data.challenge))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if (
        record is None
        or record.purpose != "login"
        or not pending_challenge_is_usable(record, data.challenge, now=now)
    ):
        raise invalid

    factor = await db.scalar(
        select(StaffMfaFactor).where(StaffMfaFactor.user_id == record.user_id).with_for_update()
    )
    user = await db.scalar(
        select(User).options(selectinload(User.memberships)).where(User.id == record.user_id)
    )
    if factor is None or factor.enrolled_at is None or user is None or not user.is_active:
        raise invalid

    # The factor row lock serializes completions for different challenges on
    # the same account. Count attempts across recent password-verified login
    # challenges so issuing a fresh challenge cannot reset the guess budget.
    failures = await db.scalar(
        select(func.coalesce(func.sum(StaffMfaChallenge.attempts), 0)).where(
            StaffMfaChallenge.user_id == user.id,
            StaffMfaChallenge.purpose == "login",
            StaffMfaChallenge.created_at > now - MFA_ACCOUNT_CHALLENGE_WINDOW,
        )
    )
    if failures >= MFA_ACCOUNT_MAX_FAILURES:
        raise HTTPException(status_code=429, detail="Too many MFA attempts")

    try:
        keys = load_staff_mfa_key_material(
            key_id=settings.MFA_ENCRYPTION_KEY_ID,
            encoded_encryption_key=settings.MFA_ENCRYPTION_KEY,
            encoded_recovery_pepper=settings.MFA_RECOVERY_PEPPER,
        )
        if keys.key_id != factor.key_id:
            raise ValueError("MFA encryption key id mismatch")
        secret = decrypt_totp_secret(
            factor.encrypted_secret,
            user_id=user.id,
            key_id=factor.key_id,
            encoded_key=keys.encoded_encryption_key,
        )
    except (InvalidTag, UnicodeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Staff MFA is unavailable") from exc

    step = verify_totp(secret, data.code, at=now, last_accepted_step=factor.last_accepted_step)
    used_recovery = None
    if step is None:
        try:
            digest = hash_recovery_code(data.code, pepper=keys.recovery_pepper)
        except ValueError:
            digest = None
        if digest is not None:
            used_recovery = await db.scalar(
                select(StaffMfaRecoveryCode)
                .where(
                    StaffMfaRecoveryCode.user_id == user.id,
                    StaffMfaRecoveryCode.code_hash == digest,
                    StaffMfaRecoveryCode.used_at.is_(None),
                )
                .with_for_update()
            )
    if step is None and used_recovery is None:
        record.attempts += 1
        await db.commit()
        raise invalid

    if step is not None:
        factor.last_accepted_step = step
    else:
        used_recovery.used_at = now
    record.consumed_at = now
    # Persist one-use state before any credential leaves the process.
    await db.commit()

    clinic_id = user.memberships[0].clinic_id if user.memberships else None
    access_token = create_access_token(
        user.id, clinic_id=clinic_id, token_version=user.token_version, mfa_verified_at=now
    )
    refresh_token = await _create_browser_session(db, user, mfa_verified_at=now)
    _set_session_cookies(response, refresh_token)
    return TokenResponse(access_token=access_token)


@router.post("/mfa/enroll/start", response_model=BeginMfaEnrollmentResponse)
@limiter.limit("5/minute", key_func=_mfa_enrollment_rate_key)
async def begin_mfa_enrollment(
    request: Request,
    response: Response,
    data: BeginMfaEnrollmentRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BeginMfaEnrollmentResponse:
    """Require the current password before exposing a new authenticator seed."""
    try:
        keys = load_staff_mfa_key_material(
            key_id=settings.MFA_ENCRYPTION_KEY_ID,
            encoded_encryption_key=settings.MFA_ENCRYPTION_KEY,
            encoded_recovery_pepper=settings.MFA_RECOVERY_PEPPER,
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Staff MFA is unavailable") from exc

    # The user lock serializes simultaneous starts even before a factor row exists.
    user = await db.scalar(select(User).where(User.id == current_user.id).with_for_update())
    if user is None or not user.is_active or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    factor = await db.scalar(
        select(StaffMfaFactor).where(StaffMfaFactor.user_id == user.id).with_for_update()
    )
    if factor is not None and factor.enrolled_at is not None:
        raise HTTPException(status_code=409, detail="MFA is already enrolled")

    now = datetime.now(UTC)
    secret = generate_totp_secret()
    envelope = encrypt_totp_secret(
        secret, user_id=user.id, key_id=keys.key_id, encoded_key=keys.encoded_encryption_key
    )
    if factor is None:
        factor = StaffMfaFactor(
            user_id=user.id, created_at=now, encrypted_secret=envelope, key_id=keys.key_id
        )
        db.add(factor)
    else:
        factor.encrypted_secret = envelope
        factor.key_id = keys.key_id
        factor.last_accepted_step = None
    factor.pending_expires_at = now + timedelta(minutes=10)

    # A restarted setup invalidates all earlier pending enrollment challenges.
    await db.execute(
        update(StaffMfaChallenge)
        .where(
            StaffMfaChallenge.user_id == user.id,
            StaffMfaChallenge.purpose == "enrollment",
            StaffMfaChallenge.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    challenge, record = issue_pending_challenge(user_id=user.id, purpose="enrollment", now=now)
    db.add(record)
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    issuer = "DentalPin"
    uri = (
        f"otpauth://totp/{quote(issuer)}:{quote(user.email, safe='')}"
        f"?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
    )
    return BeginMfaEnrollmentResponse(challenge=challenge, secret=secret, provisioning_uri=uri)


@router.post("/mfa/enroll/confirm", response_model=ConfirmMfaEnrollmentResponse)
@limiter.limit("5/minute", key_func=_mfa_enrollment_rate_key)
async def confirm_mfa_enrollment(
    request: Request,
    response: Response,
    data: ConfirmMfaEnrollmentRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConfirmMfaEnrollmentResponse:
    """Confirm the pending seed, revoke old sessions, and reveal recovery codes once."""
    invalid = HTTPException(status_code=401, detail="Invalid or expired MFA enrollment")
    record = await db.scalar(
        select(StaffMfaChallenge)
        .where(StaffMfaChallenge.challenge_hash == hash_pending_challenge(data.challenge))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if (
        record is None
        or record.user_id != current_user.id
        or record.purpose != "enrollment"
        or not pending_challenge_is_usable(record, data.challenge, now=now)
    ):
        raise invalid

    user = await db.scalar(
        select(User)
        .options(selectinload(User.memberships))
        .where(User.id == current_user.id)
        .with_for_update()
    )
    factor = await db.scalar(
        select(StaffMfaFactor).where(StaffMfaFactor.user_id == current_user.id).with_for_update()
    )
    if (
        user is None
        or not user.is_active
        or factor is None
        or factor.enrolled_at is not None
        or factor.pending_expires_at is None
        or factor.pending_expires_at <= now
    ):
        raise invalid
    try:
        keys = load_staff_mfa_key_material(
            key_id=settings.MFA_ENCRYPTION_KEY_ID,
            encoded_encryption_key=settings.MFA_ENCRYPTION_KEY,
            encoded_recovery_pepper=settings.MFA_RECOVERY_PEPPER,
        )
        if keys.key_id != factor.key_id:
            raise ValueError("MFA encryption key id mismatch")
        secret = decrypt_totp_secret(
            factor.encrypted_secret,
            user_id=user.id,
            key_id=factor.key_id,
            encoded_key=keys.encoded_encryption_key,
        )
    except (InvalidTag, UnicodeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Staff MFA is unavailable") from exc
    step = verify_totp(secret, data.code, at=now)
    if step is None:
        record.attempts += 1
        await db.commit()
        raise invalid

    factor.last_accepted_step = step
    factor.enrolled_at = now
    factor.pending_expires_at = None
    record.consumed_at = now
    recovery_codes = generate_recovery_codes()
    db.add_all(
        StaffMfaRecoveryCode(
            user_id=user.id,
            code_hash=hash_recovery_code(code, pepper=keys.recovery_pepper),
            created_at=now,
        )
        for code in recovery_codes
    )
    user.token_version += 1
    await db.execute(
        update(RefreshSession)
        .where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    # The session helper commits enrollment, recovery digests, and the new session
    # as one transaction before either credentials or recovery codes are returned.
    refresh_token = await _create_browser_session(db, user, mfa_verified_at=now)
    clinic_id = user.memberships[0].clinic_id if user.memberships else None
    access_token = create_access_token(
        user.id, clinic_id=clinic_id, token_version=user.token_version, mfa_verified_at=now
    )
    _set_session_cookies(response, refresh_token)
    return ConfirmMfaEnrollmentResponse(access_token=access_token, recovery_codes=recovery_codes)


@router.get("/mfa/status", response_model=StaffMfaStatusResponse)
async def staff_mfa_status(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StaffMfaStatusResponse:
    """Expose enrollment state without disclosing seeds or recovery secrets."""
    enrolled = await db.scalar(
        select(StaffMfaFactor.id).where(
            StaffMfaFactor.user_id == current_user.id,
            StaffMfaFactor.enrolled_at.is_not(None),
        )
    )
    remaining = 0
    if enrolled is not None:
        remaining = (
            await db.scalar(
                select(func.count())
                .select_from(StaffMfaRecoveryCode)
                .where(
                    StaffMfaRecoveryCode.user_id == current_user.id,
                    StaffMfaRecoveryCode.used_at.is_(None),
                )
            )
            or 0
        )
    return StaffMfaStatusResponse(enrolled=enrolled is not None, recovery_codes_remaining=remaining)


@router.post("/mfa/recovery/rotate", response_model=RotateMfaRecoveryCodesResponse)
@limiter.limit("5/minute", key_func=_mfa_enrollment_rate_key)
async def rotate_mfa_recovery_codes(
    request: Request,
    response: Response,
    data: RotateMfaRecoveryCodesRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RotateMfaRecoveryCodesResponse:
    """Replace every recovery code after password and fresh TOTP step-up."""
    invalid = HTTPException(status_code=401, detail="Invalid credentials or authenticator code")
    factor = await db.scalar(
        select(StaffMfaFactor).where(StaffMfaFactor.user_id == current_user.id).with_for_update()
    )
    if factor is None or factor.enrolled_at is None:
        raise HTTPException(status_code=409, detail="MFA is not enrolled")
    user = await db.scalar(select(User).where(User.id == current_user.id))
    if user is None or not user.is_active or not verify_password(data.password, user.password_hash):
        raise invalid
    try:
        keys = load_staff_mfa_key_material(
            key_id=settings.MFA_ENCRYPTION_KEY_ID,
            encoded_encryption_key=settings.MFA_ENCRYPTION_KEY,
            encoded_recovery_pepper=settings.MFA_RECOVERY_PEPPER,
        )
        if keys.key_id != factor.key_id:
            raise ValueError("MFA encryption key id mismatch")
        secret = decrypt_totp_secret(
            factor.encrypted_secret,
            user_id=user.id,
            key_id=factor.key_id,
            encoded_key=keys.encoded_encryption_key,
        )
    except (InvalidTag, UnicodeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Staff MFA is unavailable") from exc

    now = datetime.now(UTC)
    step = verify_totp(secret, data.code, at=now, last_accepted_step=factor.last_accepted_step)
    if step is None:
        raise invalid
    codes = generate_recovery_codes()
    await db.execute(delete(StaffMfaRecoveryCode).where(StaffMfaRecoveryCode.user_id == user.id))
    db.add_all(
        StaffMfaRecoveryCode(
            user_id=user.id,
            code_hash=hash_recovery_code(code, pepper=keys.recovery_pepper),
            created_at=now,
        )
        for code in codes
    )
    factor.last_accepted_step = step
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return RotateMfaRecoveryCodesResponse(recovery_codes=codes)


@router.post("/refresh", response_model=AuthResponse)
@limiter.limit("10/minute", key_func=_refresh_rate_key)
async def refresh_token(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    csrf_token: Annotated[str | None, Header(alias=_CSRF_HEADER_NAME)] = None,
) -> AuthResponse:
    """Refresh browser auth state from the protected session cookie."""
    refresh_cookie = request.cookies.get(_REFRESH_COOKIE_NAME)
    if refresh_cookie is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh session",
        )
    verified_csrf = _verify_csrf(request, csrf_token)
    try:
        payload = decode_token(refresh_cookie)
        user_id = payload.get("sub")
        token_type = payload.get("type")
        token_version = payload.get("token_version", 0)
        session_id = UUID(payload["sid"])
        parsed_user_id = UUID(user_id)

        if user_id is None or token_type != "refresh" or not payload.get("jti"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )

    except (JWTError, KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # A row lock serializes competing rotations, including across replicas.
    session = await db.scalar(
        select(RefreshSession).where(RefreshSession.id == session_id).with_for_update()
    )
    now = datetime.now(UTC)
    if session is None or session.user_id != parsed_user_id or session.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Refresh session revoked or unknown")
    if session.absolute_expires_at <= now:
        session.revoked_at = now
        await db.commit()
        raise HTTPException(status_code=401, detail="Refresh session expired")
    if not secrets.compare_digest(session.credential_hash, refresh_credential_hash(refresh_cookie)):
        # Commit the revocation before raising: failed requests otherwise roll back.
        session.revoked_at = now
        await db.commit()
        raise HTTPException(status_code=401, detail="Refresh credential reuse detected")

    # Fetch user with memberships and clinics
    result = await db.execute(
        select(User).options(selectinload(User.memberships)).where(User.id == parsed_user_id)
    )
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Check token version for revocation
    if user.token_version != token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )

    enrolled_at = await db.scalar(
        select(StaffMfaFactor.enrolled_at).where(StaffMfaFactor.user_id == user.id)
    )
    if enrolled_at is not None and (
        session.mfa_verified_at is None or session.mfa_verified_at < enrolled_at
    ):
        session.revoked_at = now
        await db.commit()
        raise HTTPException(status_code=401, detail="MFA verification required")

    # Fetch memberships with clinics for response
    memberships_result = await db.execute(
        select(ClinicMembership)
        .options(selectinload(ClinicMembership.clinic))
        .where(ClinicMembership.user_id == user.id)
    )
    memberships = memberships_result.scalars().all()

    clinics = [
        ClinicResponse(
            id=m.clinic.id,
            name=m.clinic.name,
            role=m.role,
        )
        for m in memberships
    ]

    # Get first clinic ID for token
    clinic_id = None
    if memberships:
        clinic_id = memberships[0].clinic_id

    # Generate new tokens
    access_token = create_access_token(
        user.id,
        clinic_id=clinic_id,
        token_version=user.token_version,
        mfa_verified_at=session.mfa_verified_at if enrolled_at is not None else None,
    )
    new_refresh_token = create_refresh_token(
        user.id,
        token_version=user.token_version,
        session_id=session.id,
        absolute_expires_at=session.absolute_expires_at,
    )
    session.credential_hash = refresh_credential_hash(new_refresh_token)
    await db.commit()
    _set_session_cookies(response, new_refresh_token, csrf_token=verified_csrf)

    return AuthResponse(
        access_token=access_token,
        user=UserResponse.model_validate(user),
        clinics=clinics,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    csrf_token: Annotated[str | None, Header(alias=_CSRF_HEADER_NAME)] = None,
) -> Response:
    """Revoke the current session server-side, then clear browser cookies."""
    refresh_cookie = request.cookies.get(_REFRESH_COOKIE_NAME)
    if refresh_cookie is not None:
        _verify_csrf(request, csrf_token)
        try:
            payload = decode_token(refresh_cookie)
            if payload.get("type") == "refresh":
                session_id = UUID(payload["sid"])
                session = await db.scalar(
                    select(RefreshSession).where(RefreshSession.id == session_id).with_for_update()
                )
                if session and secrets.compare_digest(
                    session.credential_hash, refresh_credential_hash(refresh_cookie)
                ):
                    session.revoked_at = datetime.now(UTC)
                    await db.commit()
        except (JWTError, KeyError, TypeError, ValueError):
            pass
    _clear_session_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=ApiResponse[MeResponse])
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[MeResponse]:
    """Get current user info, clinics, and permissions."""
    # Fetch memberships with clinics
    result = await db.execute(
        select(ClinicMembership)
        .options(selectinload(ClinicMembership.clinic))
        .where(ClinicMembership.user_id == current_user.id)
    )
    memberships = result.scalars().all()

    clinics = [
        ClinicResponse(
            id=m.clinic.id,
            name=m.clinic.name,
            role=m.role,
        )
        for m in memberships
    ]

    # Compute effective permissions (use first clinic's role for MVP)
    permissions: list[str] = []
    if memberships:
        role = memberships[0].role
        role_perms = get_role_permissions(role)
        # Combine module permissions with core permissions
        all_perms = module_registry.get_all_permissions() + CORE_PERMISSIONS
        permissions = expand_permissions(role_perms, all_perms)

    return ApiResponse(
        data=MeResponse(
            user=UserResponse.model_validate(current_user),
            clinics=clinics,
            permissions=permissions,
        )
    )


@router.get("/users", response_model=PaginatedApiResponse[UserWithRoleResponse])
async def list_users(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.users.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PaginatedApiResponse[UserWithRoleResponse]:
    """List all users in the current clinic (admin only)."""
    # Fetch all memberships for this clinic with user data
    result = await db.execute(
        select(ClinicMembership)
        .options(selectinload(ClinicMembership.user))
        .where(ClinicMembership.clinic_id == ctx.clinic_id)
    )
    memberships = result.scalars().all()

    users = [
        UserWithRoleResponse(
            id=m.user.id,
            email=m.user.email,
            first_name=m.user.first_name,
            last_name=m.user.last_name,
            is_active=m.user.is_active,
            role=m.role,
            is_professional=m.is_professional,
            created_at=m.user.created_at.isoformat(),
        )
        for m in memberships
    ]

    return PaginatedApiResponse(
        data=users,
        total=len(users),
        page=1,
        page_size=len(users),
    )


@router.post(
    "/users", response_model=ApiResponse[UserResponse], status_code=status.HTTP_201_CREATED
)
async def create_user(
    data: UserCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.users.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[UserResponse]:
    """Create a new user (admin only)."""
    # Validate role
    if data.role not in ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid role. Must be one of: {', '.join(ROLES)}",
        )

    # Validate password strength
    is_valid, error_msg = validate_staff_password(data.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_msg,
        )

    # Resolve the target clinic. A caller may only create a membership in
    # a clinic they administer themselves — otherwise an admin of clinic A
    # could mint an admin membership in clinic B by passing its id.
    clinic_id = data.clinic_id if data.clinic_id else ctx.clinic_id
    if clinic_id != ctx.clinic_id:
        caller_is_admin = await db.execute(
            select(ClinicMembership.id).where(
                ClinicMembership.user_id == ctx.user_id,
                ClinicMembership.clinic_id == clinic_id,
                ClinicMembership.role == "admin",
            )
        )
        if caller_is_admin.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not administer the target clinic",
            )

    # Check if email already exists
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Create user
    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        first_name=data.first_name,
        last_name=data.last_name,
    )
    db.add(user)
    await db.flush()

    # Create clinic membership. Professional-ness defaults from the
    # role but is an independent axis — an admin can also practise.
    membership = ClinicMembership(
        user_id=user.id,
        clinic_id=clinic_id,
        role=data.role,
        is_professional=(
            data.is_professional
            if data.is_professional is not None
            else data.role in PROFESSIONAL_ROLES
        ),
    )
    db.add(membership)
    await db.commit()

    return ApiResponse(data=UserResponse.model_validate(user))


@router.put("/users/{user_id}", response_model=ApiResponse[UserWithRoleResponse])
async def update_user(
    user_id: UUID,
    data: UserUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.users.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[UserWithRoleResponse]:
    """Update a user in the current clinic (admin only)."""
    # Verify user belongs to this clinic
    result = await db.execute(
        select(ClinicMembership)
        .options(selectinload(ClinicMembership.user))
        .where(ClinicMembership.user_id == user_id)
        .where(ClinicMembership.clinic_id == ctx.clinic_id)
    )
    membership = result.scalar_one_or_none()

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in this clinic",
        )

    user = membership.user

    # Prevent admin from deactivating themselves
    if data.is_active is False and user.id == ctx.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )

    # Validate role if provided
    if data.role is not None and data.role not in ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid role. Must be one of: {', '.join(ROLES)}",
        )

    # Check email uniqueness if changing email
    if data.email is not None and data.email != user.email:
        email_check = await db.execute(select(User).where(User.email == data.email))
        if email_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )
        user.email = data.email

    # Update user fields
    if data.first_name is not None:
        user.first_name = data.first_name
    if data.last_name is not None:
        user.last_name = data.last_name
    if data.is_active is not None:
        user.is_active = data.is_active
        # Increment token version to invalidate existing tokens when deactivating
        if not data.is_active:
            user.token_version += 1

    # Update role in membership
    if data.role is not None:
        membership.role = data.role

    # Explicit flag wins; a role-only change re-derives it so switching
    # someone to dentist keeps them schedulable without a second click.
    if data.is_professional is not None:
        membership.is_professional = data.is_professional
    elif data.role is not None:
        membership.is_professional = data.role in PROFESSIONAL_ROLES

    await db.commit()
    await db.refresh(user)
    await db.refresh(membership)

    return ApiResponse(
        data=UserWithRoleResponse(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            is_active=user.is_active,
            role=membership.role,
            is_professional=membership.is_professional,
            created_at=user.created_at.isoformat(),
        )
    )


@router.get("/professionals", response_model=PaginatedApiResponse[ProfessionalResponse])
async def list_professionals(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("agenda.appointments.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PaginatedApiResponse[ProfessionalResponse]:
    """List professionals (members with ``is_professional``) in the current clinic."""
    # Professional-ness is a membership flag, not a role — an admin who
    # also practises shows up here too (defaults to true for
    # dentist/hygienist).
    result = await db.execute(
        select(ClinicMembership)
        .options(selectinload(ClinicMembership.user))
        .where(
            ClinicMembership.clinic_id == ctx.clinic_id,
            ClinicMembership.is_professional.is_(True),
        )
    )
    memberships = result.scalars().all()

    professionals = [
        ProfessionalResponse(
            id=m.user.id,
            email=m.user.email,
            first_name=m.user.first_name,
            last_name=m.user.last_name,
            role=m.role,
        )
        for m in memberships
        if m.user.is_active
    ]

    return PaginatedApiResponse(
        data=professionals,
        total=len(professionals),
        page=1,
        page_size=len(professionals),
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.users.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Remove a user from the current clinic (admin only).

    This removes the clinic membership but does not delete the user account.
    """
    # Prevent admin from removing themselves
    if user_id == ctx.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove yourself from the clinic",
        )

    # Verify user belongs to this clinic
    result = await db.execute(
        select(ClinicMembership)
        .where(ClinicMembership.user_id == user_id)
        .where(ClinicMembership.clinic_id == ctx.clinic_id)
    )
    membership = result.scalar_one_or_none()

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in this clinic",
        )

    await db.delete(membership)
    await db.commit()


# --- Clinic metadata (B.5: moved from clinical module) ------------------


@router.get("/clinics", response_model=PaginatedApiResponse[ClinicMetadataResponse])
async def list_user_clinics(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
) -> PaginatedApiResponse[ClinicMetadataResponse]:
    """List the caller's active clinic with full metadata + cabinets."""
    clinics = [ClinicMetadataResponse.model_validate(ctx.clinic)]
    return PaginatedApiResponse(
        data=clinics,
        total=len(clinics),
        page=1,
        page_size=len(clinics),
    )


@router.get("/clinics/{clinic_id}", response_model=ApiResponse[ClinicMetadataResponse])
async def get_clinic_metadata(
    clinic_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
) -> ApiResponse[ClinicMetadataResponse]:
    """Get clinic details."""
    if ctx.clinic_id != clinic_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this clinic",
        )
    return ApiResponse(data=ClinicMetadataResponse.model_validate(ctx.clinic))


@router.put("/clinics", response_model=ApiResponse[ClinicMetadataResponse])
async def update_clinic_metadata(
    data: ClinicMetadataUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ClinicMetadataResponse]:
    """Update clinic info (admin only)."""
    clinic = ctx.clinic

    if data.name is not None:
        clinic.name = data.name
    if data.tax_id is not None:
        clinic.tax_id = data.tax_id
    if data.legal_name is not None:
        clinic.legal_name = data.legal_name or None
    if data.phone is not None:
        clinic.phone = data.phone
    if data.email is not None:
        clinic.email = data.email
    if data.address is not None:
        existing_address = clinic.address or {}
        new_address = data.address.model_dump(exclude_unset=True)
        clinic.address = {**existing_address, **new_address}
    if data.timezone is not None:
        clinic.timezone = data.timezone
    if data.currency is not None:
        clinic.currency = data.currency

    await db.commit()
    # Re-query with cabinets eagerly loaded so ClinicMetadataResponse
    # serialization doesn't trigger an async lazy load. The response
    # always returns the full metadata shape including cabinets.
    result = await db.execute(
        select(Clinic).where(Clinic.id == clinic.id).options(selectinload(Clinic.cabinets))
    )
    clinic = result.scalar_one()

    return ApiResponse(data=ClinicMetadataResponse.model_validate(clinic))


# ---------------------------------------------------------------------------
# Per-clinic settings (JSONB ``clinic.settings``).
#
# Module-specific settings live under namespaced keys so each module
# can read its own subset without colliding. The settings PATCH
# endpoint lives in core because ``Clinic`` is a core entity, but the
# accepted keys are validated against per-module schemas.
# ---------------------------------------------------------------------------


from pydantic import BaseModel, Field  # noqa: E402


class _BudgetSettingsPatch(BaseModel):
    """Subset of clinic.settings keys owned by the budget module."""

    budget_expiry_days: int | None = Field(default=None, ge=7, le=180)
    plan_auto_close_days_after_expiry: int | None = Field(default=None, ge=7, le=180)
    budget_reminders_enabled: bool | None = None
    budget_public_auth_disabled: bool | None = None


class _BudgetSettingsResponse(BaseModel):
    budget_expiry_days: int = 30
    plan_auto_close_days_after_expiry: int = 30
    budget_reminders_enabled: bool = False
    budget_public_auth_disabled: bool = False


def _read_budget_settings(raw: dict | None) -> _BudgetSettingsResponse:
    raw = raw or {}
    return _BudgetSettingsResponse(
        budget_expiry_days=int(raw.get("budget_expiry_days", 30)),
        plan_auto_close_days_after_expiry=int(raw.get("plan_auto_close_days_after_expiry", 30)),
        budget_reminders_enabled=bool(raw.get("budget_reminders_enabled", False)),
        budget_public_auth_disabled=bool(raw.get("budget_public_auth_disabled", False)),
    )


@router.get(
    "/clinic/settings/budget",
    response_model=ApiResponse[_BudgetSettingsResponse],
)
async def get_budget_settings(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.read"))],
) -> ApiResponse[_BudgetSettingsResponse]:
    """Read the budget-related toggles from the clinic settings."""
    return ApiResponse(data=_read_budget_settings(ctx.clinic.settings))


@router.patch(
    "/clinic/settings/budget",
    response_model=ApiResponse[_BudgetSettingsResponse],
)
async def update_budget_settings(
    data: _BudgetSettingsPatch,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[_BudgetSettingsResponse]:
    """Update budget-related clinic settings (admin only)."""
    clinic = ctx.clinic
    current = dict(clinic.settings or {})
    payload = data.model_dump(exclude_unset=True)
    current.update(payload)
    clinic.settings = current
    await db.commit()
    await db.refresh(clinic)
    return ApiResponse(data=_read_budget_settings(clinic.settings))


# ---------------------------------------------------------------------------
# Communications settings (clinic-wide). Drives the language used for
# patient-facing pages (public budget link), email templates, and
# future SMS / WhatsApp messages.
# ---------------------------------------------------------------------------


class _CommunicationsSettingsPatch(BaseModel):
    language: str | None = Field(default=None, pattern="^(es|en|fr|pt|ta)$")


class _CommunicationsSettingsResponse(BaseModel):
    language: str = "es"


def _read_communications_settings(raw: dict | None) -> _CommunicationsSettingsResponse:
    raw = raw or {}
    return _CommunicationsSettingsResponse(
        language=str(raw.get("communication_language", "es")),
    )


@router.get(
    "/clinic/settings/communications",
    response_model=ApiResponse[_CommunicationsSettingsResponse],
)
async def get_communications_settings(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.read"))],
) -> ApiResponse[_CommunicationsSettingsResponse]:
    """Read the clinic-wide communications language."""
    return ApiResponse(data=_read_communications_settings(ctx.clinic.settings))


@router.patch(
    "/clinic/settings/communications",
    response_model=ApiResponse[_CommunicationsSettingsResponse],
)
async def update_communications_settings(
    data: _CommunicationsSettingsPatch,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[_CommunicationsSettingsResponse]:
    """Update the clinic-wide communications language.

    Persists under ``clinic.settings.communication_language``.
    """
    clinic = ctx.clinic
    current = dict(clinic.settings or {})
    if data.language is not None:
        current["communication_language"] = data.language
    clinic.settings = current
    await db.commit()
    await db.refresh(clinic)
    return ApiResponse(data=_read_communications_settings(clinic.settings))
