import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, DateTime, ForeignKey, Integer, BigInteger, Text, JSON, LargeBinary
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import TypeDecorator, CHAR
from sqlalchemy.orm import relationship
from .database import Base

# Cross-database UUID type support (Postgres + SQLite)
class GUID(TypeDecorator):
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PG_UUID())
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return str(value)
        else:
            if not isinstance(value, uuid.UUID):
                return str(uuid.UUID(str(value)))
            else:
                return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if not isinstance(value, uuid.UUID):
                return uuid.UUID(value)
            return value

class User(Base):
    __tablename__ = "users"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    password_hash = Column(String(255), nullable=True)  # Argon2id; Nullable for OAuth
    github_id = Column(String(100), unique=True, nullable=True)
    email_verified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    workspaces = relationship("Workspace", back_populates="owner", cascade="all, delete-orphan")
    device_sessions = relationship("DeviceSession", back_populates="user", cascade="all, delete-orphan")
    agent_runs = relationship("AgentRun", back_populates="user", cascade="all, delete-orphan")

class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    owner_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=False, index=True)
    plan_tier = Column(String(20), default="FREE", nullable=False)  # FREE / PRO
    monthly_token_limit = Column(BigInteger, default=500_000, nullable=False)
    tokens_consumed = Column(BigInteger, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    owner = relationship("User", back_populates="workspaces")
    api_keys = relationship("ApiKey", back_populates="workspace", cascade="all, delete-orphan")
    device_sessions = relationship("DeviceSession", back_populates="workspace", cascade="all, delete-orphan")
    llm_keys = relationship("LlmProviderKey", back_populates="workspace", cascade="all, delete-orphan")
    agent_runs = relationship("AgentRun", back_populates="workspace", cascade="all, delete-orphan")

class DeviceSession(Base):
    __tablename__ = "device_sessions"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(GUID(), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    client_type = Column(String(20), nullable=False)  # CLI, VSCODE, WEB
    hostname = Column(String(255), nullable=True)
    os_platform = Column(String(100), nullable=True)
    ip_address = Column(String(64), nullable=True)
    refresh_token_hash = Column(String(64), nullable=False, index=True)  # SHA-256
    token_family_id = Column(GUID(), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="device_sessions")
    workspace = relationship("Workspace", back_populates="device_sessions")

class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(GUID(), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    key_prefix = Column(String(14), nullable=False)  # e.g. "agni_sk_live_"
    key_hash = Column(String(64), unique=True, nullable=False, index=True)  # SHA-256
    scopes = Column(JSON, default=list, nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    workspace = relationship("Workspace", back_populates="api_keys")

class LlmProviderKey(Base):
    __tablename__ = "llm_provider_keys"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(GUID(), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(50), nullable=False)  # ANTHROPIC, OPENAI, GOOGLE, COHERE
    encrypted_api_key = Column(LargeBinary, nullable=False)
    nonce = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    workspace = relationship("Workspace", back_populates="llm_keys")

class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(GUID(), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    repo_name = Column(String(255), nullable=False)
    task_prompt = Column(Text, nullable=False)
    status = Column(String(50), default="PENDING", nullable=False)  # PENDING, RUNNING, COMPLETED, FAILED
    iterations = Column(Integer, default=0, nullable=False)
    input_tokens = Column(BigInteger, default=0, nullable=False)
    output_tokens = Column(BigInteger, default=0, nullable=False)
    final_diff = Column(Text, nullable=True)
    duration_ms = Column(BigInteger, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    workspace = relationship("Workspace", back_populates="agent_runs")
    user = relationship("User", back_populates="agent_runs")
