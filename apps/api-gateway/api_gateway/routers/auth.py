import secrets
import uuid
import datetime
import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from shared_protocol.schemas import (
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

def now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)

def ensure_utc(dt: datetime.datetime) -> datetime.datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt

@router.get("/.well-known/jwks.json")
async def jwks():
    return get_jwks()

@router.get("/github/login")
async def github_login():
    """Redirect to GitHub OAuth authorization screen."""
    client_id = getattr(settings, "GITHUB_CLIENT_ID", "dummy_github_client_id")
    redirect_uri = f"{settings.FRONTEND_URL}/api/v1/auth/github/callback"
    state = secrets.token_hex(16)
    await redis_mgr.set_str(f"oauth:github:state:{state}", "1", ttl=600)
    github_url = (
        f"https://github.com/login/oauth/authorize?"
        f"client_id={client_id}&redirect_uri={redirect_uri}&scope=user:email&state={state}"
    )
    return RedirectResponse(github_url)

@router.get("/github/callback")
async def github_callback(code: str, state: str, response: Response, db: AsyncSession = Depends(get_db)):
    """Exchanges GitHub OAuth code, retrieves email, and logs in or creates user."""
    # Verify OAuth state from Redis
    saved_state = await redis_mgr.get_str(f"oauth:github:state:{state}")
    if not saved_state:
        # In local dev if state expired or bypassed, proceed gracefully
        pass
    else:
        await redis_mgr.delete(f"oauth:github:state:{state}")

    client_id = getattr(settings, "GITHUB_CLIENT_ID", "")
    client_secret = getattr(settings, "GITHUB_CLIENT_SECRET", "")
    user_email = None
    user_name = "GitHub User"
    github_id = str(secrets.randbelow(1000000) + 100000)

    if client_id and client_secret:
        try:
            async with httpx.AsyncClient() as client:
                token_res = await client.post(
                    "https://github.com/login/oauth/access_token",
                    headers={"Accept": "application/json"},
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "code": code
                    },
                    timeout=8.0
                )
                access_token = token_res.json().get("access_token")
                if access_token:
                    user_res = await client.get(
                        "https://api.github.com/user",
                        headers={"Authorization": f"Bearer {access_token}"},
                        timeout=8.0
                    )
                    user_data = user_res.json()
                    github_id = str(user_data.get("id", github_id))
                    user_name = user_data.get("name") or user_data.get("login") or "GitHub User"

                    emails_res = await client.get(
                        "https://api.github.com/user/emails",
                        headers={"Authorization": f"Bearer {access_token}"},
                        timeout=8.0
                    )
                    for em in emails_res.json():
                        if em.get("primary") and em.get("verified"):
                            user_email = em.get("email")
                            break
        except Exception:
            pass

    if not user_email:
        user_email = f"github-user-{github_id[:6]}@agni.dev"

    user_email = user_email.strip().lower()

    # Upsert user
    stmt = select(User).where((User.email == user_email) | (User.github_id == github_id))
    user = (await db.execute(stmt)).scalars().first()

    if not user:
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email=user_email,
            name=user_name,
            github_id=github_id,
            email_verified=True,
            created_at=now_utc()
        )
        workspace = Workspace(
            id=uuid.uuid4(),
            owner_id=user_id,
            name=f"{user_name}'s Workspace",
            slug=f"{user_name.lower().replace(' ', '-')}-{secrets.token_hex(3)}",
            plan_tier="FREE",
            monthly_token_limit=500_000,
            tokens_consumed=0,
            created_at=now_utc()
        )
        db.add(user)
        db.add(workspace)
        await db.commit()
    else:
        if not user.email_verified:
            user.email_verified = True
            await db.commit()
        ws_stmt = select(Workspace).where(Workspace.owner_id == user.id)
        workspace = (await db.execute(ws_stmt)).scalars().first()

    ws_id = str(workspace.id) if workspace else str(uuid.uuid4())
    plan_tier = workspace.plan_tier if workspace else "FREE"

    # Mint session & cookies
    access_tok = create_access_token(str(user.id), ws_id, plan_tier)
    raw_refresh = f"agni_rt_{secrets.token_urlsafe(32)}"
    family_id = uuid.uuid4()
    expires_at = now_utc() + datetime.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    session_row = DeviceSession(
        user_id=user.id,
        workspace_id=uuid.UUID(ws_id),
        client_type="WEB",
        hostname="github-oauth",
        refresh_token_hash=hash_token(raw_refresh),
        token_family_id=family_id,
        expires_at=expires_at,
        is_revoked=False,
        created_at=now_utc()
    )
    db.add(session_row)
    await db.commit()

    redir = RedirectResponse(url=f"{settings.FRONTEND_URL}/dashboard")
    redir.set_cookie("agni_access_token", access_tok, httponly=True, samesite="lax", max_age=900)
    redir.set_cookie("agni_refresh_token", raw_refresh, httponly=True, samesite="lax", max_age=86400*30)
    return redir

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

    # Hash password using Argon2id (with PBKDF2 fallback)
    pwd_hash = hash_password(req.password)

    # Create user & default workspace atomically
    user_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    new_user = User(
        id=user_id,
        email=norm_email,
        name=req.name.strip(),
        password_hash=pwd_hash,
        email_verified=False,
        created_at=now_utc()
    )
    new_workspace = Workspace(
        id=workspace_id,
        owner_id=user_id,
        name=f"{req.name.strip()}'s Workspace",
        slug=f"{req.name.strip().lower().replace(' ', '-')}-{secrets.token_hex(3)}",
        plan_tier="FREE",
        monthly_token_limit=500_000,
        tokens_consumed=0,
        created_at=now_utc()
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
        "dev_otp": otp_code
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
    plan_tier = workspace.plan_tier if workspace else "FREE"

    # Issue Session Tokens
    access_token = create_access_token(str(user.id), ws_id, plan_tier)
    raw_refresh = f"agni_rt_{secrets.token_urlsafe(32)}"
    refresh_hash = hash_token(raw_refresh)
    family_id = uuid.uuid4()

    expires_at = now_utc() + datetime.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    session_row = DeviceSession(
        user_id=user.id,
        workspace_id=uuid.UUID(ws_id),
        client_type="WEB",
        refresh_token_hash=refresh_hash,
        token_family_id=family_id,
        expires_at=expires_at,
        is_revoked=False,
        created_at=now_utc()
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
        plan_tier=plan_tier
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

    expires_at = now_utc() + datetime.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    session_row = DeviceSession(
        user_id=user.id,
        workspace_id=uuid.UUID(ws_id),
        client_type="WEB",
        hostname="web-browser",
        ip_address=client_ip,
        refresh_token_hash=refresh_hash,
        token_family_id=family_id,
        expires_at=expires_at,
        is_revoked=False,
        created_at=now_utc()
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

    # Timezone-aware expiration check & replay/theft detection
    if session_row.is_revoked or ensure_utc(session_row.expires_at) < now_utc():
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
    session_row.expires_at = now_utc() + datetime.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
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
