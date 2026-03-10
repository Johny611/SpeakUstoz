import asyncio

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from config import (
    BOT_TOKEN,
    ADMIN_ID,
    SUBSCRIPTION_PRICE_UZS,
    SUBSCRIPTION_DURATION_DAYS,
    CARD_NUMBER,
    FREE_DAILY_LIMIT,
    PAID_DAILY_LIMIT,
)
from database import (
    connect_db,
    init_db,
    register_user,
    get_user_by_telegram_id,
    set_user_mode_and_step,
    get_user_state,
    clear_user_state,
    has_active_subscription,
    activate_subscription,
    ensure_daily_usage_row,
    get_daily_message_count,
    increment_daily_usage,
    create_payment,
    save_practice_session,
)
from ai_engine import (
    evaluate_writing_task1,
    evaluate_writing_task2,
    evaluate_speaking_part1,
    evaluate_speaking_part2,
    evaluate_speaking_part3,
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# =========================
# KEYBOARDS
# =========================

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Writing"), KeyboardButton(text="Speaking")],
        [KeyboardButton(text="Buy Subscription"), KeyboardButton(text="My Status")],
        [KeyboardButton(text="Cancel Mode")],
    ],
    resize_keyboard=True,
)

writing_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Writing Task 1"), KeyboardButton(text="Writing Task 2")],
        [KeyboardButton(text="Back to Main Menu")],
    ],
    resize_keyboard=True,
)

speaking_menu = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="Speaking Part 1"),
            KeyboardButton(text="Speaking Part 2"),
        ],
        [
            KeyboardButton(text="Speaking Part 3"),
            KeyboardButton(text="Speaking Full Mock"),
        ],
        [KeyboardButton(text="Back to Main Menu")],
    ],
    resize_keyboard=True,
)


# =========================
# HELPERS
# =========================


def format_price(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def payment_reference_for_user(telegram_id: int) -> str:
    return f"IELTS-{telegram_id}"


async def ensure_user(message: types.Message):
    await register_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    return await get_user_by_telegram_id(message.from_user.id)


async def get_user_limit(telegram_id: int) -> int:
    is_paid = await has_active_subscription(telegram_id)
    return PAID_DAILY_LIMIT if is_paid else FREE_DAILY_LIMIT


async def can_user_continue(user_id: int, telegram_id: int) -> tuple[bool, int, int]:
    await ensure_daily_usage_row(user_id)
    current_count = await get_daily_message_count(user_id)
    limit = await get_user_limit(telegram_id)
    return current_count < limit, current_count, limit


async def get_status_text(telegram_id: int, user_id: int) -> str:
    is_paid = await has_active_subscription(telegram_id)
    await ensure_daily_usage_row(user_id)
    current_count = await get_daily_message_count(user_id)
    daily_limit = await get_user_limit(telegram_id)
    state = await get_user_state(telegram_id)

    return (
        "Your status:\n"
        f"- Premium: {'Yes' if is_paid else 'No'}\n"
        f"- Daily usage: {current_count}/{daily_limit}\n"
        f"- Current mode: {state['current_mode'] if state['current_mode'] else 'None'}\n"
        f"- Current submode: {state['current_step'] if state['current_step'] else 'None'}"
    )


# =========================
# COMMANDS
# =========================


@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await ensure_user(message)
    await message.answer(
        "Welcome to the IELTS bot.\n\n"
        "Choose a main mode:\n"
        "- Writing\n"
        "- Speaking",
        reply_markup=main_menu,
    )


@dp.message(Command("menu"))
async def menu_handler(message: types.Message):
    await ensure_user(message)
    await message.answer("Main menu:", reply_markup=main_menu)


@dp.message(Command("subscribe"))
async def subscribe_handler(message: types.Message):
    await ensure_user(message)

    reference = payment_reference_for_user(message.from_user.id)

    text = (
        "Premium subscription\n\n"
        f"Price: {format_price(SUBSCRIPTION_PRICE_UZS)} so'm\n"
        f"Duration: {SUBSCRIPTION_DURATION_DAYS} days\n"
        f"Card number: {CARD_NUMBER}\n"
        f"Payment reference: {reference}\n\n"
        "After payment, send the screenshot here."
    )

    await message.answer(text, reply_markup=main_menu)


@dp.message(Command("status"))
async def status_handler(message: types.Message):
    user = await ensure_user(message)
    text = await get_status_text(message.from_user.id, user["id"])
    await message.answer(text, reply_markup=main_menu)


@dp.message(Command("approve"))
async def approve_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("Access denied.")

    parts = (message.text or "").split()
    if len(parts) != 3:
        return await message.answer("Usage: /approve <telegram_id> <days>")

    try:
        telegram_id = int(parts[1])
        days = int(parts[2])
    except ValueError:
        return await message.answer("Invalid values. Example: /approve 123456789 30")

    try:
        await activate_subscription(telegram_id, days)
        await message.answer(
            f"Subscription activated for {telegram_id} for {days} days."
        )

        try:
            await bot.send_message(
                telegram_id, f"Your premium subscription is now active for {days} days."
            )
        except Exception:
            pass

    except Exception as e:
        await message.answer(f"Failed to activate subscription: {e}")


# =========================
# MENU ROUTING
# =========================


@dp.message(F.text == "Writing")
async def writing_menu_handler(message: types.Message):
    await ensure_user(message)
    await set_user_mode_and_step(message.from_user.id, "writing", None)
    await message.answer(
        "Writing mode selected.\nChoose a task:",
        reply_markup=writing_menu,
    )


@dp.message(F.text == "Speaking")
async def speaking_menu_handler(message: types.Message):
    await ensure_user(message)
    await set_user_mode_and_step(message.from_user.id, "speaking", None)
    await message.answer(
        "Speaking mode selected.\nChoose a part:",
        reply_markup=speaking_menu,
    )


@dp.message(F.text == "Back to Main Menu")
async def back_to_main_menu_handler(message: types.Message):
    await ensure_user(message)
    await clear_user_state(message.from_user.id)
    await message.answer("Back to main menu.", reply_markup=main_menu)


@dp.message(F.text == "Cancel Mode")
async def cancel_mode_handler(message: types.Message):
    await ensure_user(message)
    await clear_user_state(message.from_user.id)
    await message.answer("Current mode cleared.", reply_markup=main_menu)


@dp.message(F.text == "Buy Subscription")
async def buy_subscription_button(message: types.Message):
    await subscribe_handler(message)


@dp.message(F.text == "My Status")
async def my_status_button(message: types.Message):
    await status_handler(message)


# =========================
# WRITING SUBMODES
# =========================


@dp.message(F.text == "Writing Task 1")
async def writing_task1_handler(message: types.Message):
    await ensure_user(message)
    await set_user_mode_and_step(message.from_user.id, "writing", "writing_task1")
    await message.answer(
        "Writing Task 1 mode is active.\nSend your Task 1 response as text.",
        reply_markup=writing_menu,
    )


@dp.message(F.text == "Writing Task 2")
async def writing_task2_handler(message: types.Message):
    await ensure_user(message)
    await set_user_mode_and_step(message.from_user.id, "writing", "writing_task2")
    await message.answer(
        "Writing Task 2 mode is active.\nSend your essay as text.",
        reply_markup=writing_menu,
    )


# =========================
# SPEAKING SUBMODES
# =========================


@dp.message(F.text == "Speaking Part 1")
async def speaking_part1_handler(message: types.Message):
    await ensure_user(message)
    await set_user_mode_and_step(message.from_user.id, "speaking", "speaking_part1")
    await message.answer(
        "Speaking Part 1 mode is active.\n\n"
        "First question:\n"
        "Do you work or are you a student?",
        reply_markup=speaking_menu,
    )


@dp.message(F.text == "Speaking Part 2")
async def speaking_part2_handler(message: types.Message):
    await ensure_user(message)
    await set_user_mode_and_step(message.from_user.id, "speaking", "speaking_part2")
    await message.answer(
        "Speaking Part 2 mode is active.\n\n"
        "Cue card:\n"
        "Describe a person who has influenced you.\n"
        "You should say:\n"
        "- who this person is\n"
        "- how you know them\n"
        "- what impact they had on you\n\n"
        "Now send your answer.",
        reply_markup=speaking_menu,
    )


@dp.message(F.text == "Speaking Part 3")
async def speaking_part3_handler(message: types.Message):
    await ensure_user(message)
    await set_user_mode_and_step(message.from_user.id, "speaking", "speaking_part3")
    await message.answer(
        "Speaking Part 3 mode is active.\n\n"
        "Discussion question:\n"
        "Why do some people have a strong influence on others?",
        reply_markup=speaking_menu,
    )


@dp.message(F.text == "Speaking Full Mock")
async def speaking_full_mock_handler(message: types.Message):
    await ensure_user(message)
    await set_user_mode_and_step(message.from_user.id, "speaking", "speaking_full_mock")
    await message.answer(
        "Speaking Full Mock is selected.\n"
        "For now, this mode is not implemented yet.\n"
        "Use Speaking Part 1, 2, or 3 first.",
        reply_markup=speaking_menu,
    )


# =========================
# PAYMENT SCREENSHOT HANDLER
# =========================


@dp.message(F.photo)
async def payment_screenshot_handler(message: types.Message):
    user = await ensure_user(message)

    screenshot_file_id = message.photo[-1].file_id
    reference = payment_reference_for_user(message.from_user.id)

    await create_payment(
        user_id=user["id"],
        amount_sum=SUBSCRIPTION_PRICE_UZS,
        card_number=CARD_NUMBER,
        payment_reference=reference,
        screenshot_file_id=screenshot_file_id,
    )

    await message.answer(
        "Payment screenshot received.\nYour request is pending admin review.",
        reply_markup=main_menu,
    )

    if ADMIN_ID:
        try:
            username = (
                f"@{message.from_user.username}"
                if message.from_user.username
                else "no_username"
            )
            caption = (
                "New payment submitted\n"
                f"User ID: {message.from_user.id}\n"
                f"Username: {username}\n"
                f"Reference: {reference}\n"
                f"Amount: {format_price(SUBSCRIPTION_PRICE_UZS)} so'm"
            )
            await bot.send_photo(
                chat_id=ADMIN_ID,
                photo=screenshot_file_id,
                caption=caption,
            )
        except Exception:
            pass


# =========================
# MAIN TEXT HANDLER
# =========================


@dp.message(F.text)
async def text_handler(message: types.Message):
    text = (message.text or "").strip()
    if not text:
        return

    user = await ensure_user(message)

    if user["is_blocked"]:
        return await message.answer("Your account is blocked.")

    state = await get_user_state(message.from_user.id)
    current_mode = state["current_mode"]
    current_step = state["current_step"]

    if current_mode is None:
        return await message.answer(
            "Choose a mode first from the menu.",
            reply_markup=main_menu,
        )

    if current_step is None:
        if current_mode == "writing":
            return await message.answer(
                "Choose a writing task first.",
                reply_markup=writing_menu,
            )
        if current_mode == "speaking":
            return await message.answer(
                "Choose a speaking part first.",
                reply_markup=speaking_menu,
            )

    allowed, current_count, daily_limit = await can_user_continue(
        user_id=user["id"],
        telegram_id=message.from_user.id,
    )

    if not allowed:
        return await message.answer(
            f"Daily limit reached: {current_count}/{daily_limit}\n"
            "Upgrade your subscription for more access.",
            reply_markup=main_menu,
        )

    if current_step.startswith("writing"):
        await message.answer("Checking your writing...")
    else:
        await message.answer("Analyzing your speaking answer...")

    try:
        if current_step == "writing_task1":
            result = await evaluate_writing_task1(text)
        elif current_step == "writing_task2":
            result = await evaluate_writing_task2(text)
        elif current_step == "speaking_part1":
            result = await evaluate_speaking_part1(text)
        elif current_step == "speaking_part2":
            result = await evaluate_speaking_part2(text)
        elif current_step == "speaking_part3":
            result = await evaluate_speaking_part3(text)
        elif current_step == "speaking_full_mock":
            result = "Full mock mode is not implemented yet."
        else:
            result = "Unknown mode selected. Please choose a mode again."
    except Exception:
        return await message.answer(
            "AI service is temporarily unavailable. Please try again later.",
            reply_markup=main_menu,
        )

    await increment_daily_usage(user["id"])

    await save_practice_session(
        user_id=user["id"],
        mode=current_step,
        user_message=text,
        ai_response=result,
        estimated_band=None,
    )

    reply_markup = writing_menu if current_mode == "writing" else speaking_menu
    await message.answer(result, reply_markup=reply_markup)


# =========================
# MAIN
# =========================


async def main():
    await connect_db()
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
