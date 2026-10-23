import asyncio
import uuid
import datetime
import secrets
from sqlalchemy import select
from .database import engine, Base, async_session
from .models import User, Workspace, ApiKey, AgentRun, DeviceSession
from .security import hash_password, hash_token

SAMPLE_DIFF = """--- a/src/core/router.py
+++ b/src/core/router.py
@@ -14,6 +14,14 @@ class ModelRouter:
         self.fast_model = fast_model
         self.reasoning_model = reasoning_model
 
+    async def route_task(self, prompt: str, is_complex: bool = False) -> str:
+        \"\"\"Routes code editing vs deep architectural tasks.\"\"\"
+        if is_complex or "refactor architecture" in prompt.lower():
+            return self.reasoning_model
+        # High-speed surgical edits run on the fast executor
+        return self.fast_model
+
     def get_status(self) -> dict:
         return {"ready": True, "pool_size": 2}
"""

async def seed_database():
    print("[SEED] Initializing Agni Dev Database Seeding...")

    active_engine = engine
    active_session_maker = async_session

    # Ensure tables exist, with fallback to SQLite if PostgreSQL connection fails
    try:
        async with active_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        print(f"[WARN] PostgreSQL connection unavailable ({e}); falling back to local SQLite (agni_dev.db)...")
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
        active_engine = create_async_engine(
            "sqlite+aiosqlite:///./agni_dev.db",
            connect_args={"check_same_thread": False},
            future=True
        )
        active_session_maker = async_sessionmaker(active_engine, class_=AsyncSession, expire_on_commit=False)
        async with active_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async with active_session_maker() as db:
        # Check if admin already exists
        admin_email = "admin@agni.dev"
        stmt = select(User).where(User.email == admin_email)
        res = await db.execute(stmt)
        existing_admin = res.scalars().first()

        if existing_admin:
            print("[SEED] Admin user already seeded, skipping duplicate creation.")
            return

        now = datetime.datetime.now(datetime.timezone.utc)

        # 1. Create Admin User
        admin_id = uuid.uuid4()
        admin_user = User(
            id=admin_id,
            email=admin_email,
            name="Agni Admin",
            password_hash=hash_password("Password123!"),
            email_verified=True,
            created_at=now
        )
        db.add(admin_user)

        # 2. Create Pro Workspace
        workspace_id = uuid.uuid4()
        workspace = Workspace(
            id=workspace_id,
            owner_id=admin_id,
            name="Agni Core Workspace",
            slug="agni-core",
            plan_tier="PRO",
            monthly_token_limit=5_000_000,
            tokens_consumed=124_500,
            created_at=now
        )
        db.add(workspace)

        # 3. Create Headless API Key
        raw_api_key = "agni_sk_live_masterkey999988887777"
        api_key = ApiKey(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            name="CI/CD Headless Key",
            key_prefix="agni_sk_live_",
            key_hash=hash_token(raw_api_key),
            scopes=["read", "write", "sandbox", "telemetry"],
            created_at=now
        )
        db.add(api_key)

        # 4. Create Sample Telemetry Agent Runs
        run1 = AgentRun(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            user_id=admin_id,
            repo_name="agni-dev/core-engine",
            task_prompt="Implement dual-model routing logic for Fast-Apply Executor in router.py",
            status="COMPLETED",
            iterations=3,
            input_tokens=14200,
            output_tokens=1850,
            final_diff=SAMPLE_DIFF,
            duration_ms=2840,
            created_at=now - datetime.timedelta(hours=2)
        )
        run2 = AgentRun(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            user_id=admin_id,
            repo_name="agni-dev/api-gateway",
            task_prompt="Optimize RFC 8628 device flow Redis polling interval",
            status="COMPLETED",
            iterations=2,
            input_tokens=8900,
            output_tokens=620,
            final_diff="""--- a/config.py\n+++ b/config.py\n@@ -10,1 +10,1 @@\n-DEVICE_POLL_INTERVAL=5\n+DEVICE_POLL_INTERVAL=2\n""",
            duration_ms=1430,
            created_at=now - datetime.timedelta(minutes=30)
        )
        db.add(run1)
        db.add(run2)

        await db.commit()

        print("\n[OK] Database Seeding Completed Successfully!")
        print("--------------------------------------------------")
        print(f"Admin Email:        {admin_email}")
        print("Admin Password:     Password123!")
        print(f"Workspace Name:     Agni Core Workspace (PRO Tier)")
        print(f"Live Headless Key:  {raw_api_key}")
        print("Telemetry Runs:     2 Sample Runs Seeded")
        print("--------------------------------------------------")

if __name__ == "__main__":
    asyncio.run(seed_database())
