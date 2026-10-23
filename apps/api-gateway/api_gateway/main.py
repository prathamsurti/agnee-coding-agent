from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .database import engine, Base
from .redis_client import redis_mgr
from .security import get_jwks
from .routers import auth, device, telemetry, keys

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: connect redis & ensure tables exist
    await redis_mgr.connect()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown
    await redis_mgr.close()
    await engine.dispose()

app = FastAPI(
    title="Agni API Gateway",
    description="FastAPI Auth Server, Ed25519 Token Proxy, RFC 8628 Device Flow & Telemetry for Agni Dev",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://app.agni.dev"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Standard Root JWKS endpoint for discovery
@app.get("/.well-known/jwks.json", tags=["Authentication"])
async def root_jwks():
    return get_jwks()

# Mount Routers
app.include_router(auth.router)
app.include_router(device.router)
app.include_router(telemetry.router)
app.include_router(keys.router)

@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "ok",
        "service": "agni-api-gateway",
        "version": "1.0.0",
        "redis_connected": redis_mgr.client is not None
    }

@app.get("/", tags=["Root"])
async def root():
    return {
        "name": "agni-dev API Gateway",
        "docs": "/docs",
        "jwks": "/.well-known/jwks.json",
        "device_init": "/api/v1/auth/device/init"
    }
