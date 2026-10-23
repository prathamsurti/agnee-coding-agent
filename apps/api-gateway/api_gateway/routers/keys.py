import os
import secrets
import uuid
import datetime
import hashlib
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, desc
from shared_protocol.schemas import (
    HeadlessKeyCreate,
    HeadlessKeyResponse,
    LlmKeyCreate,
    LlmKeyResponse
)
from ..database import get_db
from ..models import ApiKey, LlmProviderKey, Workspace
from ..security import (
    hash_token,
    verify_access_token,
    encrypt_secret,
    decrypt_secret
)

router = APIRouter(prefix="/api/v1/keys", tags=["API Keys & BYOK Vault"])

VAULT_MASTER_KEY = hashlib.sha256(
    os.getenv("AGNI_VAULT_KEY", "agni-byok-vault-master-secret-key-2026").encode("utf-8")
).digest()

def now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)

async def get_current_workspace_id(request: Request, db: AsyncSession) -> uuid.UUID:
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
    elif "agni_access_token" in request.cookies:
        token = request.cookies.get("agni_access_token")

    if token:
        try:
            claims = verify_access_token(token)
            ws_str = claims.get("ws")
            if ws_str:
                return uuid.UUID(ws_str)
        except Exception:
            pass

    # Fallback to the first available workspace in development
    ws = (await db.execute(select(Workspace).order_by(desc(Workspace.created_at)))).scalars().first()
    if ws:
        return ws.id
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

# --- Headless CI/CD API Keys ---
@router.get("/headless", response_model=List[HeadlessKeyResponse])
async def list_headless_keys(request: Request, db: AsyncSession = Depends(get_db)):
    ws_id = await get_current_workspace_id(request, db)
    stmt = select(ApiKey).where(ApiKey.workspace_id == ws_id).order_by(desc(ApiKey.created_at))
    keys = (await db.execute(stmt)).scalars().all()
    return [
        HeadlessKeyResponse(
            id=str(k.id),
            name=k.name,
            key_prefix=k.key_prefix,
            scopes=k.scopes or [],
            created_at=k.created_at.isoformat() if k.created_at else "",
            last_used_at=k.last_used_at.isoformat() if k.last_used_at else None
        )
        for k in keys
    ]

@router.post("/headless", response_model=HeadlessKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_headless_key(req: HeadlessKeyCreate, request: Request, db: AsyncSession = Depends(get_db)):
    ws_id = await get_current_workspace_id(request, db)
    
    # Generate high entropy 24-hex live API key
    raw_secret = secrets.token_hex(24)
    prefix = "agni_sk_live_"
    full_key = f"{prefix}{raw_secret}"
    key_hash = hash_token(full_key)

    new_key = ApiKey(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        name=req.name.strip(),
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=req.scopes,
        created_at=now_utc()
    )
    db.add(new_key)
    await db.commit()

    return HeadlessKeyResponse(
        id=str(new_key.id),
        name=new_key.name,
        key_prefix=prefix,
        api_key=full_key,  # Returned in plaintext only upon creation
        scopes=new_key.scopes,
        created_at=new_key.created_at.isoformat()
    )

@router.delete("/headless/{key_id}", status_code=status.HTTP_200_OK)
async def delete_headless_key(key_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    ws_id = await get_current_workspace_id(request, db)
    key_uuid = uuid.UUID(key_id)
    stmt = delete(ApiKey).where((ApiKey.id == key_uuid) & (ApiKey.workspace_id == ws_id))
    result = await db.execute(stmt)
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    return {"message": "Key revoked successfully"}

# --- BYOK LLM Provider Keys (AES-256-GCM Encrypted Vault) ---
@router.get("/llm", response_model=List[LlmKeyResponse])
async def list_llm_keys(request: Request, db: AsyncSession = Depends(get_db)):
    ws_id = await get_current_workspace_id(request, db)
    stmt = select(LlmProviderKey).where(LlmProviderKey.workspace_id == ws_id).order_by(desc(LlmProviderKey.created_at))
    keys = (await db.execute(stmt)).scalars().all()
    return [
        LlmKeyResponse(
            id=str(k.id),
            provider=k.provider,
            created_at=k.created_at.isoformat() if k.created_at else ""
        )
        for k in keys
    ]

@router.post("/llm", response_model=LlmKeyResponse, status_code=status.HTTP_201_CREATED)
async def save_llm_key(req: LlmKeyCreate, request: Request, db: AsyncSession = Depends(get_db)):
    ws_id = await get_current_workspace_id(request, db)
    
    # Encrypt provider API key using AES-256-GCM
    encrypted_bytes, nonce = encrypt_secret(req.api_key.strip(), VAULT_MASTER_KEY)

    # Remove previous key for this provider if existing
    del_stmt = delete(LlmProviderKey).where(
        (LlmProviderKey.workspace_id == ws_id) & (LlmProviderKey.provider == req.provider)
    )
    await db.execute(del_stmt)

    new_llm_key = LlmProviderKey(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        provider=req.provider,
        encrypted_api_key=encrypted_bytes,
        nonce=nonce,
        created_at=now_utc()
    )
    db.add(new_llm_key)
    await db.commit()

    return LlmKeyResponse(
        id=str(new_llm_key.id),
        provider=new_llm_key.provider,
        created_at=new_llm_key.created_at.isoformat()
    )

@router.delete("/llm/{key_id}", status_code=status.HTTP_200_OK)
async def delete_llm_key(key_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    ws_id = await get_current_workspace_id(request, db)
    key_uuid = uuid.UUID(key_id)
    stmt = delete(LlmProviderKey).where((LlmProviderKey.id == key_uuid) & (LlmProviderKey.workspace_id == ws_id))
    result = await db.execute(stmt)
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="LLM provider key not found")
    return {"message": "LLM key deleted successfully"}
