from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime, timezone

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

# --- Auth Schemas ---
class UserSignupRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=10)

class VerifyEmailRequest(BaseModel):
    email: str
    code: str = Field(..., min_length=6, max_length=6)

class UserLoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900
    user_id: str
    workspace_id: str
    plan_tier: str = "FREE"

class RefreshTokenRequest(BaseModel):
    refresh_token: str

# --- RFC 8628 Device Authorization Schemas ---
class DeviceInitRequest(BaseModel):
    client_type: Literal["CLI", "VSCODE"] = "CLI"
    hostname: Optional[str] = "unknown"
    os_platform: Optional[str] = "unknown"

class DeviceInitResponse(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int = 300
    interval: int = 2

class DeviceApproveRequest(BaseModel):
    user_code: str
    workspace_id: Optional[str] = None

class DevicePollRequest(BaseModel):
    device_code: str

class DevicePollResponse(BaseModel):
    status: Literal["authorization_pending", "approved", "expired", "denied"]
    tokens: Optional[TokenResponse] = None

class DeviceLookupResponse(BaseModel):
    user_code: str
    client_type: str
    hostname: Optional[str] = None
    os_platform: Optional[str] = None
    ip: Optional[str] = None
    status: str

# --- API Keys & BYOK Schemas ---
class HeadlessKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: List[str] = ["read", "write"]

class HeadlessKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    api_key: Optional[str] = None
    scopes: List[str]
    created_at: str
    last_used_at: Optional[str] = None

class LlmKeyCreate(BaseModel):
    provider: Literal["ANTHROPIC", "OPENAI", "GOOGLE", "COHERE"]
    api_key: str

class LlmKeyResponse(BaseModel):
    id: str
    provider: str
    created_at: str

# --- Agent & Telemetry Schemas ---
class AgentRunCreate(BaseModel):
    workspace_id: UUID
    user_id: UUID
    repo_name: str
    task_prompt: str
    status: str = "PENDING"

class AgentRunTelemetry(BaseModel):
    run_id: str
    workspace_id: Optional[str] = None
    user_id: Optional[str] = None
    repo_name: Optional[str] = "default-repo"
    task_prompt: Optional[str] = "Agent task"
    status: str = "COMPLETED"
    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    final_diff: Optional[str] = None

# --- WebSocket RPC Event Schemas ---
class WsRpcMessage(BaseModel):
    event: Literal["PLAN_CREATED", "FILE_READ", "DIFF_APPLIED", "TEST_OUTPUT", "HUMAN_APPROVAL_REQUIRED", "ERROR", "DONE"]
    run_id: str
    payload: Dict[str, Any]
    timestamp: datetime = Field(default_factory=utc_now)
