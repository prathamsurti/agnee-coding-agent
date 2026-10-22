import hashlib
import os
import json
import base64
import time
import secrets
from typing import Dict, Any, Tuple, Optional
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import jwt
from passlib.context import CryptContext
from .config import settings

# Password Hashing context (Argon2id with PBKDF2 fallback)
try:
    from passlib.context import CryptContext
    pwd_context = CryptContext(
        schemes=["argon2"],
        deprecated="auto",
        argon2__memory_cost=65536,
        argon2__time_cost=3,
        argon2__parallelism=4
    )
except ImportError:
    pwd_context = None

DUMMY_ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$dGVzdHNhbHQ$abcdefghijklmnopqrstuvwxyz123456"

# Ed25519 Keys Initialization
_priv_key_obj: Optional[ed25519.Ed25519PrivateKey] = None
_pub_key_obj: Optional[ed25519.Ed25519PublicKey] = None

def get_ed25519_keys() -> Tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
    global _priv_key_obj, _pub_key_obj
    if _priv_key_obj is not None and _pub_key_obj is not None:
        return _priv_key_obj, _pub_key_obj

    if settings.ED25519_PRIVATE_KEY_PEM:
        _priv_key_obj = serialization.load_pem_private_key(
            settings.ED25519_PRIVATE_KEY_PEM.encode("utf-8"),
            password=None
        )
        _pub_key_obj = _priv_key_obj.public_key()
    else:
        # In-memory ephemeral keypair for development if not provided in env
        _priv_key_obj = ed25519.Ed25519PrivateKey.generate()
        _pub_key_obj = _priv_key_obj.public_key()

    return _priv_key_obj, _pub_key_obj

def hash_password(password: str) -> str:
    if pwd_context:
        return pwd_context.hash(password)
    # Pure Python PBKDF2 fallback
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return f"pbkdf2${base64.b64encode(salt).decode()}${base64.b64encode(key).decode()}"

def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    if not hashed_password:
        if pwd_context:
            pwd_context.verify(plain_password, DUMMY_ARGON2_HASH)
        return False
    if pwd_context and hashed_password.startswith("$argon2"):
        return pwd_context.verify(plain_password, hashed_password)
    if hashed_password.startswith("pbkdf2$"):
        parts = hashed_password.split("$")
        salt = base64.b64decode(parts[1])
        expected_key = base64.b64decode(parts[2])
        key = hashlib.pbkdf2_hmac('sha256', plain_password.encode('utf-8'), salt, 100000)
        return secrets.compare_digest(key, expected_key)
    return False

def hash_token(token: str) -> str:
    """Computes SHA-256 hash of a refresh token or API key."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def create_access_token(user_id: str, workspace_id: str, plan_tier: str = "FREE") -> str:
    priv_key, _ = get_ed25519_keys()
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "ws": str(workspace_id),
        "tier": plan_tier,
        "iat": now,
        "exp": now + (settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60),
        "iss": "agni-api-gateway"
    }
    priv_pem = priv_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    token = jwt.encode(payload, priv_pem, algorithm="EdDSA")
    return token

def verify_access_token(token: str) -> Dict[str, Any]:
    _, pub_key = get_ed25519_keys()
    pub_pem = pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return jwt.decode(token, pub_pem, algorithms=["EdDSA"], issuer="agni-api-gateway")

def get_jwks() -> Dict[str, Any]:
    """Returns JWKS format for public key verification."""
    _, pub_key = get_ed25519_keys()
    raw_pub_bytes = pub_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    x_b64 = base64.urlsafe_b64encode(raw_pub_bytes).rstrip(b'=').decode('utf-8')
    return {
        "keys": [
            {
                "kty": "OKP",
                "crv": "Ed25519",
                "use": "sig",
                "kid": "agni-ed25519-key-1",
                "x": x_b64,
                "alg": "EdDSA"
            }
        ]
    }

# AES-256-GCM Helper for LLM Keys Vault
def encrypt_secret(secret: str, master_key: bytes) -> Tuple[bytes, bytes]:
    aesgcm = AESGCM(master_key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, secret.encode("utf-8"), None)
    return ciphertext, nonce

def decrypt_secret(ciphertext: bytes, nonce: bytes, master_key: bytes) -> str:
    aesgcm = AESGCM(master_key)
    decrypted = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted.decode("utf-8")
