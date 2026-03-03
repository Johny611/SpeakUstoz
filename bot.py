import asyncio
from aiogram import Bot, Dispatcher, types
from config import BOT_TOKEN
from db import connect_db, init_db
from ai_engine import evaluate_answer

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message()
async def handle_message(message: types.Message):
    await message.answer("Analyzing your IELTS answer...")
    result = await evaluate_answer(message.text)
    await message.answer(result)


async def main():
    await connect_db()
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
