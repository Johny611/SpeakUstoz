from openai import OpenAI
from config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """
You are a certified IELTS Speaking examiner.
After user answer:
1. Continue exam briefly.
2. Provide band score (0-9).
3. Grammar feedback.
4. Vocabulary feedback.
5. Fluency feedback.
Be concise.
"""


async def evaluate_answer(user_text):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        max_tokens=400,
    )

    return response.choices[0].message.content
