# -*- coding: utf-8 -*-
import os
from pathlib import Path
from dotenv import load_dotenv
from openai import AsyncOpenAI
from loguru import logger

from knowledge_base import faq_knowledge
from memory_store import get_history, append_message, get_profile

# ---------------------- ЗАГРУЗКА .env ----------------------
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY пуст — GPT fallback не будет работать.")

_client: AsyncOpenAI | None = None
def client() -> AsyncOpenAI | None:
    global _client
    if not OPENAI_API_KEY:
        return None
    if _client is None:
        _client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _client

SEALED_TOPICS_INSTRUCTIONS = (
    "ВАЖНО: Все цены, скидки, условия (минимум альбомов, сроки «до марта», "
    "стоимость дубликатов, стоимость доп. разворотов, форматы и количественные "
    "параметры) — отвечай ТОЛЬКО по фактам из блока Facts. Если вопрос не даёт "
    "контекста (сад/школа/тип альбома), сначала уточни ИЛИ покажи краткие цены "
    "для обоих вариантов (общий и индивидуальный) для соответствующего уровня "
    "(сад/школа) из Facts, затем спроси, что выбрать. Если в Facts нет нужной "
    "цены/условия — не придумывай, скажи, что уточнишь у фотографа."
)

BASE_TONE = (
    "Говори кратко и по делу, дружелюбно. Можешь уточнять 1–2 ключевых момента, "
    "предлагай помощь с бронированием. Не используй канцелярит."
)

SYSTEM_PROMPT_TEMPLATE = """
Ты — дружелюбный консьерж‑ассистент фотографа. Общайся свободно: приветствуй, поддерживай диалог,
помогай выбрать альбом, объясняй процесс съёмки, давай советы по подготовке, мягко направляй к бронированию.

{sealed}
{tone}

— Ниже факты (Facts). Они приоритетны для цен и условий.
— Если вопрос о ценах/условиях не покрыт фактами — ответь: «Не могу назвать точную цену. Давайте я уточню у фотографа.»

— Ниже краткая карточка клиента (Client Profile) — учитывай её контекст в ответах.

Facts:
{facts}

Client Profile:
{profile}
"""

KNOWN_FACT_NUMBERS = {"2700","3700","4600","3500","2000","3300","4100","2200","3200","4400","400","600"}
def looks_like_untrusted_price(answer: str) -> bool:
    ans = answer.lower()
    if "₽" not in ans and "руб" not in ans:
        return False
    if "50%" in ans or "50 %" in ans:
        return False
    for n in KNOWN_FACT_NUMBERS:
        if n in ans:
            return False
    return True

async def ask_gpt(user_id: int, user_query: str) -> str | None:
    cli = client()
    if cli is None:
        return None

    # Профиль клиента (persisted)
    profile = get_profile(user_id)
    prof_lines = []
    if profile:
        for k in ["level","org_number","album_type","count_children","contact_method"]:
            if k in profile and profile[k]:
                prof_lines.append(f"- {k}: {profile[k]}")
    profile_text = "\n".join(prof_lines) if prof_lines else "- (пока нет данных)"

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        sealed=SEALED_TOPICS_INSTRUCTIONS,
        tone=BASE_TONE,
        facts=faq_knowledge,
        profile=profile_text,
    )

    # История чата клиента (persisted)
    history_msgs = get_history(user_id, limit=12)

    try:
        msgs = [{"role": "system", "content": system_prompt}, *history_msgs, {"role": "user", "content": user_query}]
        resp = await cli.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.3,
            messages=msgs,
        )
        answer = (resp.choices[0].message.content or "").strip()

        # Сохраняем диалог
        append_message(user_id, "user", user_query)
        append_message(user_id, "assistant", answer)

        if looks_like_untrusted_price(answer):
            safe = "Не могу назвать точную цену. Давайте я уточню у фотографа."
            append_message(user_id, "assistant", safe)
            return safe

        return answer or None

    except Exception as e:
        logger.error(f"GPT error: {e}")
        return None
