import asyncpg
from config import DATABASE_URL

pool = None


async def connect_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)


async def get_pool():
    return pool


async def init_db():
    async with pool.acquire() as conn:
        await conn.execute(
            """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE,
            subscription_until TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """
        )
