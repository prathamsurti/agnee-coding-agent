import secrets
import uuid
import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from packages.shared_protocol.shared_protocol.schemas import (
    DeviceInitRequest,
    DeviceInitResponse,
    DeviceApproveRequest,
    DevicePollRequest,
    DevicePollResponse,
    TokenResponse
)
from ..database import get_db
from ..models import User, Workspace, DeviceSession
from ..security import create_access_token, hash_token, verify_access_token
from ..redis_client import redis_mgr
from ..config import settings

router = APIRouter(prefix="/api/v1/auth/device", tags=["RFC 8628 Device Flow"])

# Unambiguous alphabet without 0, O, 1, I
UNAMBIGUOUS_CHARS = "BCDFGHJKLMNPQRSTVWXYZ23456789"

def generate_user_code() -> str:
    part1 = "".join(secrets.choice(UNAMBIGUOUS_CHARS) for _ in range(4))
    part2 = "".join(secrets.choice(UNAMBIGUOUS_CHARS) for _ in range(4))
    return f"{part1}-{part2}"

@router.post("/init", response_model=DeviceInitResponse)
async def device_init(req: DeviceInitRequest, request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"
    device_code = secrets.token_hex(32)  # 64-char high-entropy code
    user_code = generate_user_code()     # 8-char human readable "ABCD-EFGH"

    device_payload = {
        "user_code": user_code,
        "client_type": req.client_type,
        "hostname": req.hostname,
        "os_platform": req.os_platform,
        "ip": client_ip,
        "status": "PENDING",
        "user_id": None,
        "workspace_id": None
    }

    # Store in Redis hot path (TTL 300s)
    await redis_mgr.set_json(f"oauth:device:{device_code}", device_payload, ttl=settings.DEVICE_CODE_EXPIRE_SECONDS)
    await redis_mgr.set_str(f"oauth:user_code:{user_code}", device_code, ttl=settings.DEVICE_CODE_EXPIRE_SECONDS)

    verification_uri = f"{settings.FRONTEND_URL}/activate"
    verification_uri_complete = f"{verification_uri}?code={user_code}"

    return DeviceInitResponse(
        device_code=device_code,
        user_code=user_code,
        verification_uri=verification_uri,
        verification_uri_complete=verification_uri_complete,
        expires_in=settings.DEVICE_CODE_EXPIRE_SECONDS,
        interval=settings.DEVICE_POLL_INTERVAL_SECONDS
    )

@router.post("/approve")
async def device_approve(req: DeviceApproveRequest, request: Request, db: AsyncSession = Depends(get_db)):
    # Extract access token from header or cookie
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
    elif "agni_access_token" in request.cookies:
        token = request.cookies.get("agni_access_token")

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required to approve device.")

    try:
        claims = verify_access_token(token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session token.")

    user_id = claims.get("sub")
    workspace_id = req.workspace_id or claims.get("ws")

    code_key = req.user_code.strip().upper()
    device_code = await redis_mgr.get_str(f"oauth:user_code:{code_key}")
    if not device_code:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired device code.")

    device_data = await redis_mgr.get_json(f"oauth:device:{device_code}")
    if not device_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device session expired.")

    # Approve device
    device_data["status"] = "APPROVED"
    device_data["user_id"] = user_id
    device_data["workspace_id"] = workspace_id

    await redis_mgr.set_json(f"oauth:device:{device_code}", device_data, ttl=settings.DEVICE_CODE_EXPIRE_SECONDS)

    return {
        "message": f"Successfully authorized machine '{device_data.get('hostname')}' ({device_data.get('os_platform')}).",
        "client_type": device_data.get("client_type"),
        "hostname": device_data.get("hostname")
    }

@router.post("/poll", response_model=DevicePollResponse)
async def device_poll(req: DevicePollRequest, db: AsyncSession = Depends(get_db)):
    device_data = await redis_mgr.get_json(f"oauth:device:{req.device_code}")
    if not device_data:
        return DevicePollResponse(status="expired")

    current_status = device_data.get("status")

    if current_status == "PENDING":
        return DevicePollResponse(status="authorization_pending")

    if current_status == "DENIED":
        await redis_mgr.delete(f"oauth:device:{req.device_code}")
        await redis_mgr.delete(f"oauth:user_code:{device_data.get('user_code')}")
        return DevicePollResponse(status="denied")

    if current_status == "APPROVED":
        user_id = device_data.get("user_id")
        workspace_id = device_data.get("workspace_id")

        # Fetch workspace tier
        ws = (await db.execute(select(Workspace).where(Workspace.id == uuid.UUID(workspace_id)))).scalars().first()
        plan_tier = ws.plan_tier if ws else "FREE"

        # Mint session & tokens for the CLI/IDE client
        access_token = create_access_token(user_id, workspace_id, plan_tier)
        raw_refresh = f"agni_rt_{secrets.token_urlsafe(32)}"
        refresh_hash = hash_token(raw_refresh)
        family_id = uuid.uuid4()

        expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        session_row = DeviceSession(
            user_id=uuid.UUID(user_id),
            workspace_id=uuid.UUID(workspace_id),
            client_type=device_data.get("client_type", "CLI"),
            hostname=device_data.get("hostname"),
            os_platform=device_data.get("os_platform"),
            ip_address=device_data.get("ip"),
            refresh_token_hash=refresh_hash,
            token_family_id=family_id,
            expires_at=expires_at,
            is_revoked=False
        )
        db.add(session_row)
        await db.commit()

        # Clean up Redis keys
        await redis_mgr.delete(f"oauth:device:{req.device_code}")
        await redis_mgr.delete(f"oauth:user_code:{device_data.get('user_code')}")

        return DevicePollResponse(
            status="approved",
            tokens=TokenResponse(
                access_token=access_token,
                refresh_token=raw_refresh,
                expires_in=900,
                user_id=user_id,
                workspace_id=workspace_id,
                plan_tier=plan_tier
            )
        )

    return DevicePollResponse(status="expired")
