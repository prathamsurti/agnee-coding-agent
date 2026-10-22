import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from .config import settings

class Base(DeclarativeBase):
    pass

# Choose engine based on DATABASE_URL with sqlite fallback support
db_url = settings.DATABASE_URL
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

connect_args = {}
if "sqlite" in db_url:
    connect_args["check_same_thread"] = False

try:
    engine = create_async_engine(
        db_url,
        echo=(settings.ENV == "development"),
        connect_args=connect_args,
        future=True
    )
except Exception:
    fallback_url = "sqlite+aiosqlite:///./agni_dev.db"
    engine = create_async_engine(
        fallback_url,
        echo=False,
        connect_args={"check_same_thread": False},
        future=True
    )

async_session = async_sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
