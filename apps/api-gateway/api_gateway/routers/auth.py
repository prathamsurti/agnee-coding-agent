import secrets
import uuid
import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from packages.shared_protocol.shared_protocol.schemas import (
    UserSignupRequest,
    VerifyEmailRequest,
    UserLoginRequest,
    TokenResponse,
    RefreshTokenRequest
)
from ..database import get_db
from ..models import User, Workspace, DeviceSession
from ..security import (
    hash_password,
    verify_password,
    create_access_token,
    hash_token,
    get_jwks
)
from ..redis_client import redis_mgr
from ..config import settings

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])

@router.get("/.well-known/jwks.json")
async def jwks():
    return get_jwks()

@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(req: UserSignupRequest, request: Request, db: AsyncSession = Depends(get_db)):
    client_ip = request.client.host if request.client else "127.0.0.1"
    if not await redis_mgr.check_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, 
            detail="Too many signup attempts. Try again later."
        )

    norm_email = req.email.strip().lower()

    # Check if user exists
    stmt = select(User).where(User.email == norm_email)
    res = await db.execute(stmt)
    if res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email address already exists."
        )

    # Hash password using Argon2id
    pwd_hash = hash_password(req.password)

    # Create user & default workspace atomically
    user_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    new_user = User(
        id=user_id,
        email=norm_email,
        name=req.name.strip(),
        password_hash=pwd_hash,
        email_verified=False
    )
    new_workspace = Workspace(
        id=workspace_id,
        owner_id=user_id,
        name=f"{req.name.strip()}'s Workspace",
        slug=f"{req.name.strip().lower().replace(' ', '-')}-{secrets.token_hex(3)}",
        plan_tier="FREE",
        monthly_token_limit=500_000,
        tokens_consumed=0
    )

    db.add(new_user)
    db.add(new_workspace)
    await db.commit()

    # Generate 6-digit OTP
    otp_code = str(secrets.randbelow(900000) + 100000)
    otp_hash = hash_token(otp_code)
    await redis_mgr.set_json(f"otp:verify:{norm_email}", {"hash": otp_hash, "attempts": 0}, ttl=600)

    return {
        "message": "User registered successfully. Please verify your email.",
        "email": norm_email,
        "dev_otp": otp_code  # Printed in response for effortless local/docker testing!
    }

@router.post("/verify-email")
async def verify_email(req: VerifyEmailRequest, response: Response, db: AsyncSession = Depends(get_db)):
    norm_email = req.email.strip().lower()
    cached = await redis_mgr.get_json(f"otp:verify:{norm_email}")
    if not cached:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP expired or invalid.")

    if cached["attempts"] >= 5:
        await redis_mgr.delete(f"otp:verify:{norm_email}")
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Max attempts exceeded.")

    submitted_hash = hash_token(req.code.strip())
    if submitted_hash != cached["hash"]:
        cached["attempts"] += 1
        await redis_mgr.set_json(f"otp:verify:{norm_email}", cached, ttl=600)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OTP verification code.")

    # Mark user verified
    stmt = select(User).where(User.email == norm_email)
    user = (await db.execute(stmt)).scalars().first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    user.email_verified = True
    await db.commit()
    await redis_mgr.delete(f"otp:verify:{norm_email}")

    # Fetch default workspace
    ws_stmt = select(Workspace).where(Workspace.owner_id == user.id)
    workspace = (await db.execute(ws_stmt)).scalars().first()
    ws_id = str(workspace.id) if workspace else str(uuid.uuid4())

    # Issue Session Tokens
    access_token = create_access_token(str(user.id), ws_id, workspace.plan_tier if workspace else "FREE")
    raw_refresh = f"agni_rt_{secrets.token_urlsafe(32)}"
    refresh_hash = hash_token(raw_refresh)
    family_id = uuid.uuid4()

    expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    session_row = DeviceSession(
        user_id=user.id,
        workspace_id=uuid.UUID(ws_id),
        client_type="WEB",
        refresh_token_hash=refresh_hash,
        token_family_id=family_id,
        expires_at=expires_at,
        is_revoked=False
    )
    db.add(session_row)
    await db.commit()

    # Deliver cookies
    response.set_cookie("agni_access_token", access_token, httponly=True, samesite="lax", max_age=900)
    response.set_cookie("agni_refresh_token", raw_refresh, httponly=True, samesite="lax", max_age=86400*30)

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=900,
        user_id=str(user.id),
        workspace_id=ws_id,
        plan_tier=workspace.plan_tier if workspace else "FREE"
    )

@router.post("/login")
async def login(req: UserLoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    client_ip = request.client.host if request.client else "127.0.0.1"
    if not await redis_mgr.check_rate_limit(client_ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded.")

    norm_email = req.email.strip().lower()
    stmt = select(User).where(User.email == norm_email)
    user = (await db.execute(stmt)).scalars().first()

    valid = verify_password(req.password, user.password_hash if user else None)
    if not user or not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    # Fetch default workspace
    ws_stmt = select(Workspace).where(Workspace.owner_id == user.id)
    workspace = (await db.execute(ws_stmt)).scalars().first()
    ws_id = str(workspace.id) if workspace else str(uuid.uuid4())
    plan_tier = workspace.plan_tier if workspace else "FREE"

    access_token = create_access_token(str(user.id), ws_id, plan_tier)
    raw_refresh = f"agni_rt_{secrets.token_urlsafe(32)}"
    refresh_hash = hash_token(raw_refresh)
    family_id = uuid.uuid4()

    expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    session_row = DeviceSession(
        user_id=user.id,
        workspace_id=uuid.UUID(ws_id),
        client_type="WEB",
        hostname="web-browser",
        ip_address=client_ip,
        refresh_token_hash=refresh_hash,
        token_family_id=family_id,
        expires_at=expires_at,
        is_revoked=False
    )
    db.add(session_row)
    await db.commit()

    # Set HttpOnly Cookies
    response.set_cookie("agni_access_token", access_token, httponly=True, samesite="lax", max_age=900)
    response.set_cookie("agni_refresh_token", raw_refresh, httponly=True, samesite="lax", max_age=86400*30)

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=900,
        user_id=str(user.id),
        workspace_id=ws_id,
        plan_tier=plan_tier
    )

@router.post("/refresh")
async def refresh_tokens(req: RefreshTokenRequest, response: Response, db: AsyncSession = Depends(get_db)):
    old_hash = hash_token(req.refresh_token)

    # Check 30s grace period cache in Redis
    cached_grace = await redis_mgr.get_json(f"session:grace:{old_hash}")
    if cached_grace:
        return TokenResponse(**cached_grace)

    # Lookup session in DB
    stmt = select(DeviceSession).where(DeviceSession.refresh_token_hash == old_hash)
    session_row = (await db.execute(stmt)).scalars().first()

    if not session_row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.")

    # Replay/theft detection
    if session_row.is_revoked or session_row.expires_at < datetime.datetime.utcnow():
        # Revoke entire token family
        rev_stmt = update(DeviceSession).where(DeviceSession.token_family_id == session_row.token_family_id).values(is_revoked=True)
        await db.execute(rev_stmt)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or token reused. Revoking family.")

    # Fetch workspace
    ws = (await db.execute(select(Workspace).where(Workspace.id == session_row.workspace_id))).scalars().first()
    plan_tier = ws.plan_tier if ws else "FREE"

    # Rotate Refresh Token
    new_raw_refresh = f"agni_rt_{secrets.token_urlsafe(32)}"
    new_hash = hash_token(new_raw_refresh)
    new_access_token = create_access_token(str(session_row.user_id), str(session_row.workspace_id), plan_tier)

    session_row.refresh_token_hash = new_hash
    session_row.expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    await db.commit()

    token_data = {
        "access_token": new_access_token,
        "refresh_token": new_raw_refresh,
        "token_type": "bearer",
        "expires_in": 900,
        "user_id": str(session_row.user_id),
        "workspace_id": str(session_row.workspace_id),
        "plan_tier": plan_tier
    }

    # Cache old token in grace period store for 30s
    await redis_mgr.set_json(f"session:grace:{old_hash}", token_data, ttl=settings.TOKEN_FAMILY_GRACE_PERIOD_SECONDS)

    response.set_cookie("agni_access_token", new_access_token, httponly=True, samesite="lax", max_age=900)
    response.set_cookie("agni_refresh_token", new_raw_refresh, httponly=True, samesite="lax", max_age=86400*30)

    return TokenResponse(**token_data)

@router.post("/logout")
async def logout(req: RefreshTokenRequest, response: Response, db: AsyncSession = Depends(get_db)):
    old_hash = hash_token(req.refresh_token)
    stmt = update(DeviceSession).where(DeviceSession.refresh_token_hash == old_hash).values(is_revoked=True)
    await db.execute(stmt)
    await db.commit()

    response.delete_cookie("agni_access_token")
    response.delete_cookie("agni_refresh_token")
    return {"message": "Logged out successfully."}
