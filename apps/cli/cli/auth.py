import os
import json
import time
import socket
import platform
import base64
import httpx
from pathlib import Path
from typing import Optional, Dict, Any, Generator

AGNI_DIR = Path.home() / ".agni"
CONFIG_FILE = AGNI_DIR / "config.json"
CREDENTIALS_FILE = AGNI_DIR / "credentials"
JWKS_FILE = AGNI_DIR / "jwks.json"

def get_base_url() -> str:
    return os.getenv("AGNI_API_URL", "http://localhost:8000")

def ensure_config_dir():
    AGNI_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps({}))
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except Exception:
            pass

def save_auth_session(user_email: str, workspace_id: str, access_token: str, refresh_token: str, plan_tier: str = "FREE"):
    ensure_config_dir()
    config = {
        "user_email": user_email,
        "workspace_id": workspace_id,
        "access_token": access_token,
        "plan_tier": plan_tier,
        "saved_at": time.time()
    }
    CONFIG_FILE.write_text(json.dumps(config, indent=2))
    
    # Store refresh token securely in OS Keychain with fallback to protected file
    try:
        import keyring
        keyring.set_password("agni-cli", user_email, refresh_token)
    except Exception:
        CREDENTIALS_FILE.write_text(json.dumps({user_email: refresh_token}))
        try:
            os.chmod(CREDENTIALS_FILE, 0o600)
        except Exception:
            pass

def get_auth_session() -> Dict[str, Any]:
    ensure_config_dir()
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}

def get_stored_refresh_token(email: str) -> Optional[str]:
    try:
        import keyring
        token = keyring.get_password("agni-cli", email)
        if token:
            return token
    except Exception:
        pass

    if CREDENTIALS_FILE.exists():
        try:
            data = json.loads(CREDENTIALS_FILE.read_text())
            return data.get(email)
        except Exception:
            pass
    return None

def clear_auth_session():
    session = get_auth_session()
    email = session.get("user_email")
    if email:
        try:
            import keyring
            keyring.delete_password("agni-cli", email)
        except Exception:
            pass
    if CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps({}))
    if CREDENTIALS_FILE.exists():
        try:
            CREDENTIALS_FILE.unlink()
        except Exception:
            pass

def fetch_and_cache_jwks() -> Optional[Dict[str, Any]]:
    """Fetches API Gateway JWKS and caches locally at ~/.agni/jwks.json."""
    ensure_config_dir()
    base_url = get_base_url()
    try:
        resp = httpx.get(f"{base_url}/.well-known/jwks.json", timeout=3.0)
        if resp.status_code == 200:
            jwks_data = resp.json()
            JWKS_FILE.write_text(json.dumps(jwks_data, indent=2))
            return jwks_data
    except Exception:
        pass

    if JWKS_FILE.exists():
        try:
            return json.loads(JWKS_FILE.read_text())
        except Exception:
            pass
    return None

def verify_token_locally(token: str) -> Dict[str, Any]:
    """Verifies Ed25519 JWT locally in ~0.2ms using cached public key."""
    import jwt
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization

    jwks_data = None
    if JWKS_FILE.exists():
        try:
            jwks_data = json.loads(JWKS_FILE.read_text())
        except Exception:
            pass
    if not jwks_data:
        jwks_data = fetch_and_cache_jwks()

    if not jwks_data or "keys" not in jwks_data or not jwks_data["keys"]:
        # Fallback decode without key if offline
        return jwt.decode(token, options={"verify_signature": False})

    key_dict = jwks_data["keys"][0]
    x_b64 = key_dict["x"]
    # Pad base64 if needed
    rem = len(x_b64) % 4
    if rem:
        x_b64 += "=" * (4 - rem)
    raw_pub_bytes = base64.urlsafe_b64decode(x_b64)
    pub_key = ed25519.Ed25519PublicKey.from_public_bytes(raw_pub_bytes)
    pub_pem = pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return jwt.decode(token, pub_pem, algorithms=["EdDSA"], issuer="agni-api-gateway")

def silent_refresh_sync() -> Optional[str]:
    """Synchronous silent refresh for CLI requests."""
    session = get_auth_session()
    email = session.get("user_email")
    if not email:
        return None
    refresh_tok = get_stored_refresh_token(email)
    if not refresh_tok:
        return None

    base_url = get_base_url()
    try:
        resp = httpx.post(
            f"{base_url}/api/v1/auth/refresh",
            json={"refresh_token": refresh_tok},
            timeout=5.0
        )
        if resp.status_code == 200:
            data = resp.json()
            save_auth_session(
                user_email=email,
                workspace_id=data["workspace_id"],
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                plan_tier=data.get("plan_tier", "FREE")
            )
            return data["access_token"]
    except Exception:
        pass
    return None

async def silent_refresh() -> Optional[str]:
    session = get_auth_session()
    email = session.get("user_email")
    if not email:
        return None
    refresh_tok = get_stored_refresh_token(email)
    if not refresh_tok:
        return None

    base_url = get_base_url()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{base_url}/api/v1/auth/refresh",
                json={"refresh_token": refresh_tok},
                timeout=5.0
            )
            if resp.status_code == 200:
                data = resp.json()
                save_auth_session(
                    user_email=email,
                    workspace_id=data["workspace_id"],
                    access_token=data["access_token"],
                    refresh_token=data["refresh_token"],
                    plan_tier=data.get("plan_tier", "FREE")
                )
                return data["access_token"]
    except Exception:
        pass
    return None

class AgniAuthFlow(httpx.Auth):
    """
    HTTPX Auth handler that checks token lifetime (exp - now < 60s)
    and automatically executes silent refresh before sending requests.
    """
    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        session = get_auth_session()
        token = session.get("access_token")
        
        # Check if expired or within 60 seconds of expiry
        should_refresh = False
        if not token:
            should_refresh = True
        else:
            try:
                import jwt
                unverified = jwt.decode(token, options={"verify_signature": False})
                exp = unverified.get("exp", 0)
                if exp - time.time() < 60:
                    should_refresh = True
            except Exception:
                should_refresh = True

        if should_refresh:
            new_token = silent_refresh_sync()
            if new_token:
                token = new_token

        if token:
            request.headers["Authorization"] = f"Bearer {token}"

        response = yield request
        if response.status_code == 401:
            # Token might have been revoked or expired; retry with a fresh refresh
            new_token = silent_refresh_sync()
            if new_token:
                request.headers["Authorization"] = f"Bearer {new_token}"
                yield request
