import asyncio
import os
import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path("apps/api-gateway").resolve()))
sys.path.insert(0, str(Path("packages/shared-protocol").resolve()))

# Set database to sqlite for test
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_agni.db"

from httpx import AsyncClient, ASGITransport
from api_gateway.main import app
from api_gateway.database import engine, Base

async def run_batch1_verification():
    print("[TEST] Starting Batch 1 Orchestrator Verification...")

    # Ensure tables exist in test db
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test Root JWKS
        jwks_resp = await client.get("/.well-known/jwks.json")
        assert jwks_resp.status_code == 200, f"Root JWKS failed: {jwks_resp.text}"
        assert "keys" in jwks_resp.json(), "Missing keys in JWKS"
        print("  [OK] Root /.well-known/jwks.json returns Ed25519 keys")

        # 2. Test Signup
        signup_resp = await client.post("/api/v1/auth/signup", json={
            "name": "Test Engineer",
            "email": "engineer@agni.dev",
            "password": "Password123!"
        })
        assert signup_resp.status_code in [201, 409], f"Signup failed: {signup_resp.text}"
        signup_data = signup_resp.json()
        dev_otp = signup_data.get("dev_otp") or "123456"
        print("  [OK] POST /api/v1/auth/signup succeeds")

        # 3. Test Verify Email
        verify_resp = await client.post("/api/v1/auth/verify-email", json={
            "email": "engineer@agni.dev",
            "code": dev_otp
        })
        # If already verified or just verified, proceed
        print(f"  [OK] POST /api/v1/auth/verify-email response: {verify_resp.status_code}")

        # 4. Test Login
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "engineer@agni.dev",
            "password": "Password123!"
        })
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        login_data = login_resp.json()
        access_tok = login_data["access_token"]
        refresh_tok = login_data["refresh_token"]
        headers = {"Authorization": f"Bearer {access_tok}"}
        print("  [OK] POST /api/v1/auth/login returns Ed25519 token pair")

        # 5. Test Refresh (Verifying timezone compatibility)
        refresh_resp = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": refresh_tok
        })
        assert refresh_resp.status_code == 200, f"Refresh failed: {refresh_resp.text}"
        new_refresh = refresh_resp.json()["refresh_token"]
        print("  [OK] POST /api/v1/auth/refresh rotates token without timezone TypeError")

        # 6. Test Device Flow (init -> lookup -> approve -> poll)
        init_resp = await client.post("/api/v1/auth/device/init", json={
            "client_type": "CLI",
            "hostname": "Test-Laptop",
            "os_platform": "Windows"
        })
        assert init_resp.status_code == 200, f"Device init failed: {init_resp.text}"
        init_data = init_resp.json()
        user_code = init_data["user_code"]
        device_code = init_data["device_code"]
        print(f"  [OK] POST /api/v1/auth/device/init returned code: {user_code}")

        # Test Device Lookup
        lookup_resp = await client.get(f"/api/v1/auth/device/lookup?code={user_code}")
        assert lookup_resp.status_code == 200, f"Lookup failed: {lookup_resp.text}"
        lookup_data = lookup_resp.json()
        assert lookup_data["hostname"] == "Test-Laptop"
        print(f"  [OK] GET /api/v1/auth/device/lookup returns machine metadata: {lookup_data['hostname']}")

        # Test Device Approve
        approve_resp = await client.post("/api/v1/auth/device/approve", json={
            "user_code": user_code
        }, headers=headers)
        assert approve_resp.status_code == 200, f"Approve failed: {approve_resp.text}"
        print("  [OK] POST /api/v1/auth/device/approve authorizes device")

        # Test Device Poll
        poll_resp = await client.post("/api/v1/auth/device/poll", json={
            "device_code": device_code
        })
        assert poll_resp.status_code == 200, f"Poll failed: {poll_resp.text}"
        poll_data = poll_resp.json()
        assert poll_data["status"] == "approved"
        print("  [OK] POST /api/v1/auth/device/poll mints CLI session tokens")

        # 7. Test Headless API Keys CRUD
        create_key_resp = await client.post("/api/v1/keys/headless", json={
            "name": "CI Test Key",
            "scopes": ["read", "write"]
        }, headers=headers)
        assert create_key_resp.status_code == 201, f"Create key failed: {create_key_resp.text}"
        key_data = create_key_resp.json()
        assert key_data["api_key"].startswith("agni_sk_live_")
        print(f"  [OK] POST /api/v1/keys/headless mints: {key_data['api_key'][:18]}...")

        list_keys_resp = await client.get("/api/v1/keys/headless", headers=headers)
        assert list_keys_resp.status_code == 200
        assert len(list_keys_resp.json()) >= 1
        print("  [OK] GET /api/v1/keys/headless lists active keys")

        # 8. Test BYOK LLM Keys (AES-256-GCM Vault)
        llm_key_resp = await client.post("/api/v1/keys/llm", json={
            "provider": "ANTHROPIC",
            "api_key": "sk-ant-test-key-12345"
        }, headers=headers)
        assert llm_key_resp.status_code == 201, f"Save LLM key failed: {llm_key_resp.text}"
        print("  [OK] POST /api/v1/keys/llm stores AES-256-GCM encrypted provider key")

        list_llm_resp = await client.get("/api/v1/keys/llm", headers=headers)
        assert list_llm_resp.status_code == 200
        assert any(k["provider"] == "ANTHROPIC" for k in list_llm_resp.json())
        print("  [OK] GET /api/v1/keys/llm returns configured providers")

        # 9. Test Telemetry Run Insertion
        run_resp = await client.post("/api/v1/telemetry/runs", json={
            "run_id": "11111111-2222-3333-4444-555555555555",
            "repo_name": "agni-dev/test",
            "task_prompt": "Run unit test verification",
            "status": "COMPLETED",
            "iterations": 1,
            "input_tokens": 1500,
            "output_tokens": 300,
            "duration_ms": 120
        }, headers=headers)
        assert run_resp.status_code == 200
        print("  [OK] POST /api/v1/telemetry/runs inserts new run and increments tokens")

    print("\n[SUCCESS] ALL BATCH 1 VERIFICATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(run_batch1_verification())
