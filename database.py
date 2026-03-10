import asyncpg
from typing import Optional

from config import DATABASE_URL

pool: Optional[asyncpg.Pool] = None


async def connect_db():
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=5,
        )


async def get_pool() -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError("Database pool is not initialized. Call connect_db() first.")
    return pool


async def init_db():
    db = await get_pool()

    async with db.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                is_blocked BOOLEAN NOT NULL DEFAULT FALSE,
                current_mode TEXT,
                current_step TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                plan_name TEXT NOT NULL DEFAULT 'premium',
                starts_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                ends_at TIMESTAMPTZ NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usage_logs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                usage_date DATE NOT NULL DEFAULT CURRENT_DATE,
                message_count INTEGER NOT NULL DEFAULT 0,
                token_input INTEGER NOT NULL DEFAULT 0,
                token_output INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (user_id, usage_date)
            );
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                amount_sum INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'UZS',
                card_number TEXT,
                payment_reference TEXT,
                screenshot_file_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                admin_note TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                reviewed_at TIMESTAMPTZ
            );
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS practice_sessions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                mode TEXT NOT NULL,
                user_message TEXT NOT NULL,
                ai_response TEXT NOT NULL,
                estimated_band NUMERIC(2,1),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )


# =========================
# USER FUNCTIONS
# =========================


async def register_user(
    telegram_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
) -> None:
    db = await get_pool()

    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (telegram_id, username, first_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (telegram_id)
            DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name
            """,
            telegram_id,
            username,
            first_name,
        )


async def get_user_by_telegram_id(telegram_id: int) -> Optional[asyncpg.Record]:
    db = await get_pool()

    async with db.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT *
            FROM users
            WHERE telegram_id = $1
            """,
            telegram_id,
        )


async def get_user_by_id(user_id: int) -> Optional[asyncpg.Record]:
    db = await get_pool()

    async with db.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT *
            FROM users
            WHERE id = $1
            """,
            user_id,
        )


async def block_user(telegram_id: int) -> None:
    db = await get_pool()

    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE users
            SET is_blocked = TRUE
            WHERE telegram_id = $1
            """,
            telegram_id,
        )


async def unblock_user(telegram_id: int) -> None:
    db = await get_pool()

    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE users
            SET is_blocked = FALSE
            WHERE telegram_id = $1
            """,
            telegram_id,
        )


# =========================
# MODE / STATE FUNCTIONS
# =========================


async def set_user_mode(telegram_id: int, mode: Optional[str]) -> None:
    db = await get_pool()

    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE users
            SET current_mode = $2
            WHERE telegram_id = $1
            """,
            telegram_id,
            mode,
        )


async def set_user_step(telegram_id: int, step: Optional[str]) -> None:
    db = await get_pool()

    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE users
            SET current_step = $2
            WHERE telegram_id = $1
            """,
            telegram_id,
            step,
        )


async def set_user_mode_and_step(
    telegram_id: int,
    mode: Optional[str],
    step: Optional[str],
) -> None:
    db = await get_pool()

    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE users
            SET current_mode = $2,
                current_step = $3
            WHERE telegram_id = $1
            """,
            telegram_id,
            mode,
            step,
        )


async def get_user_mode(telegram_id: int) -> Optional[str]:
    db = await get_pool()

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT current_mode
            FROM users
            WHERE telegram_id = $1
            """,
            telegram_id,
        )
        return row["current_mode"] if row else None


async def get_user_step(telegram_id: int) -> Optional[str]:
    db = await get_pool()

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT current_step
            FROM users
            WHERE telegram_id = $1
            """,
            telegram_id,
        )
        return row["current_step"] if row else None


async def get_user_state(telegram_id: int) -> dict:
    db = await get_pool()

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT current_mode, current_step
            FROM users
            WHERE telegram_id = $1
            """,
            telegram_id,
        )

        if row is None:
            return {"current_mode": None, "current_step": None}

        return {
            "current_mode": row["current_mode"],
            "current_step": row["current_step"],
        }


async def clear_user_state(telegram_id: int) -> None:
    db = await get_pool()

    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE users
            SET current_mode = NULL,
                current_step = NULL
            WHERE telegram_id = $1
            """,
            telegram_id,
        )


# =========================
# SUBSCRIPTION FUNCTIONS
# =========================


async def has_active_subscription(telegram_id: int) -> bool:
    db = await get_pool()

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1
            FROM subscriptions s
            JOIN users u ON u.id = s.user_id
            WHERE u.telegram_id = $1
              AND s.is_active = TRUE
              AND s.ends_at > NOW()
            LIMIT 1
            """,
            telegram_id,
        )
        return row is not None


async def activate_subscription(
    telegram_id: int,
    days: int,
    plan_name: str = "premium",
) -> None:
    db = await get_pool()

    async with db.acquire() as conn:
        user = await conn.fetchrow(
            """
            SELECT id
            FROM users
            WHERE telegram_id = $1
            """,
            telegram_id,
        )

        if user is None:
            raise ValueError("User not found")

        user_id = user["id"]

        await conn.execute(
            """
            UPDATE subscriptions
            SET is_active = FALSE
            WHERE user_id = $1 AND is_active = TRUE
            """,
            user_id,
        )

        await conn.execute(
            """
            INSERT INTO subscriptions (user_id, plan_name, starts_at, ends_at, is_active)
            VALUES ($1, $2, NOW(), NOW() + ($3 || ' days')::INTERVAL, TRUE)
            """,
            user_id,
            plan_name,
            days,
        )


async def deactivate_expired_subscriptions() -> None:
    db = await get_pool()

    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE subscriptions
            SET is_active = FALSE
            WHERE is_active = TRUE
              AND ends_at <= NOW()
            """
        )


async def get_subscription_info(telegram_id: int) -> Optional[asyncpg.Record]:
    db = await get_pool()

    async with db.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT s.*
            FROM subscriptions s
            JOIN users u ON u.id = s.user_id
            WHERE u.telegram_id = $1
            ORDER BY s.ends_at DESC
            LIMIT 1
            """,
            telegram_id,
        )


# =========================
# USAGE FUNCTIONS
# =========================


async def ensure_daily_usage_row(user_id: int) -> None:
    db = await get_pool()

    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO usage_logs (user_id, usage_date, message_count, token_input, token_output)
            VALUES ($1, CURRENT_DATE, 0, 0, 0)
            ON CONFLICT (user_id, usage_date) DO NOTHING
            """,
            user_id,
        )


async def get_daily_message_count(user_id: int) -> int:
    db = await get_pool()

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT message_count
            FROM usage_logs
            WHERE user_id = $1
              AND usage_date = CURRENT_DATE
            """,
            user_id,
        )
        return row["message_count"] if row else 0


async def get_daily_token_usage(user_id: int) -> dict:
    db = await get_pool()

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT token_input, token_output
            FROM usage_logs
            WHERE user_id = $1
              AND usage_date = CURRENT_DATE
            """,
            user_id,
        )

        if row is None:
            return {"token_input": 0, "token_output": 0}

        return {
            "token_input": row["token_input"],
            "token_output": row["token_output"],
        }


async def increment_daily_usage(
    user_id: int,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    db = await get_pool()

    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO usage_logs (user_id, usage_date, message_count, token_input, token_output)
            VALUES ($1, CURRENT_DATE, 1, $2, $3)
            ON CONFLICT (user_id, usage_date)
            DO UPDATE SET
                message_count = usage_logs.message_count + 1,
                token_input = usage_logs.token_input + EXCLUDED.token_input,
                token_output = usage_logs.token_output + EXCLUDED.token_output
            """,
            user_id,
            input_tokens,
            output_tokens,
        )


# =========================
# PAYMENT FUNCTIONS
# =========================


async def create_payment(
    user_id: int,
    amount_sum: int,
    card_number: Optional[str] = None,
    payment_reference: Optional[str] = None,
    screenshot_file_id: Optional[str] = None,
) -> None:
    db = await get_pool()

    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO payments (
                user_id,
                amount_sum,
                card_number,
                payment_reference,
                screenshot_file_id,
                status
            )
            VALUES ($1, $2, $3, $4, $5, 'pending')
            """,
            user_id,
            amount_sum,
            card_number,
            payment_reference,
            screenshot_file_id,
        )


async def update_payment_status(
    payment_id: int,
    status: str,
    admin_note: Optional[str] = None,
) -> None:
    db = await get_pool()

    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE payments
            SET status = $2,
                admin_note = $3,
                reviewed_at = NOW()
            WHERE id = $1
            """,
            payment_id,
            status,
            admin_note,
        )


async def get_pending_payments() -> list[asyncpg.Record]:
    db = await get_pool()

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.*, u.telegram_id, u.username, u.first_name
            FROM payments p
            JOIN users u ON u.id = p.user_id
            WHERE p.status = 'pending'
            ORDER BY p.created_at ASC
            """
        )
        return list(rows)


# =========================
# PRACTICE SESSION FUNCTIONS
# =========================


async def save_practice_session(
    user_id: int,
    mode: str,
    user_message: str,
    ai_response: str,
    estimated_band: Optional[float] = None,
) -> None:
    db = await get_pool()

    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO practice_sessions (
                user_id,
                mode,
                user_message,
                ai_response,
                estimated_band
            )
            VALUES ($1, $2, $3, $4, $5)
            """,
            user_id,
            mode,
            user_message,
            ai_response,
            estimated_band,
        )


async def get_recent_sessions(user_id: int, limit: int = 10) -> list[asyncpg.Record]:
    db = await get_pool()

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM practice_sessions
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
        return list(rows)
