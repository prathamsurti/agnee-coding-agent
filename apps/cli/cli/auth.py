import os
import json
import time
import socket
import platform
import httpx
from pathlib import Path
from typing import Optional, Dict, Any

AGNI_DIR = Path.home() / ".agni"
CONFIG_FILE = AGNI_DIR / "config.json"
CREDENTIALS_FILE = AGNI_DIR / "credentials"

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
