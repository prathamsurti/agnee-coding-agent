from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime

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

# --- Agent & Telemetry Schemas ---
class AgentRunCreate(BaseModel):
    workspace_id: UUID
    user_id: UUID
    repo_name: str
    task_prompt: str
    status: str = "PENDING"

class AgentRunTelemetry(BaseModel):
    run_id: str
    status: str
    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    final_diff: Optional[str] = None

# --- WebSocket RPC Event Schemas ---
class WsRpcMessage(BaseModel):
    event: Literal["PLAN_CREATED", "FILE_READ", "DIFF_APPLIED", "TEST_OUTPUT", "ERROR", "DONE"]
    run_id: str
    payload: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
