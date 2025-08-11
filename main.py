# -*- coding: utf-8 -*-
import asyncio
import os
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from loguru import logger

from knowledge_base import get_faq_answer, normalize
from openai_helper import ask_gpt
from booking_router import router as booking_router, cmd_survey
from memory_store import append_message  # NEW: persist dialogue

# ---------------------- ЗАГРУЗКА .env ----------------------
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN пуст. Укажите токен бота в .env")

# ---------------------- ЛОГИРОВАНИЕ ----------------------
LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)
logger.add(LOGS_DIR / "bot.log",
           rotation="2 MB",
           retention=10,
           encoding="utf-8",
           enqueue=True,
           backtrace=True,
           diagnose=True)

# ---------------------- БОТ/DP ----------------------
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="Markdown"))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(booking_router)  # приоритет FSM
dp.include_router(router)

# ---------------------- УТИЛИТЫ ----------------------
DIALOG_LOG = Path(__file__).parent / "logs" / "dialog_log.txt"

def log_dialog(user_id: int, role: str, text: str) -> None:
    DIALOG_LOG.parent.mkdir(exist_ok=True)
    with DIALOG_LOG.open("a", encoding="utf-8") as f:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = text.replace("\n", " ").strip()
        f.write(f"[{ts}] {user_id} {role}: {text}\n")

GREETING_FULL = {"привет","здравствуйте","здрасте","здрасьте","здарова","здаров","приветствую","добрый день","добрый вечер","доброе утро","доброго дня","доброй ночи","hello","hi","хай","салют","ку","прив",}
GREETING_PREFIXES = ("здрав","здраст","здрась","здаров","привет","прив","добр","hello","hi","хай","салют","ку")

def is_greeting(text: str) -> bool:
    t = normalize(text)
    if not t:
        return False
    if len(t) <= 20:
        for tok in t.split():
            for pref in GREETING_PREFIXES:
                if tok.startswith(pref):
                    return True
        for g in GREETING_FULL:
            if SequenceMatcher(None, g, t).ratio() >= 0.72:
                return True
    toks = t.split()
    if len(toks) == 1:
        for pref in GREETING_PREFIXES:
            if toks[0].startswith(pref):
                return True
    return False

def build_menu_kb() -> ReplyKeyboardMarkup:
    rows = [["📝 Пройти опрос", "ℹ️ Задать вопрос"]]
    keyboard = [[KeyboardButton(text=txt) for txt in row] for row in rows]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, one_time_keyboard=False)

async def send_menu(message: Message, preface: str | None = None) -> None:
    text = preface or ("Чем помочь? Выберите режим:\n"
                       "📝 Пройти опрос — за 1–2 минуты соберём заявку (сад/школа, №, тип, кол-во детей, контакт).\n"
                       "ℹ️ Задать вопрос — свободный диалог с консьержем.")
    await message.answer(text, reply_markup=build_menu_kb())

# ---------------------- ХЕНДЛЕРЫ ----------------------
@router.message(CommandStart())
async def start(message: Message) -> None:
    hello = ("👋 Привет! Я *Олькин‑консьерж*.\n"
             "Могу ответить на вопросы или быстро оформить заявку через опрос.")
    await message.answer(hello)
    await send_menu(message)

@router.message(Command("menu"))
async def menu_cmd(message: Message) -> None:
    await send_menu(message)

@router.message(Command("survey"))
async def survey_cmd(message: Message, state: FSMContext) -> None:
    await cmd_survey(message, state)

@router.message(Command("book"))
async def book_cmd(message: Message, state: FSMContext) -> None:
    await cmd_survey(message, state)

@router.message(F.text == "📝 Пройти опрос")
async def survey_entry(message: Message, state: FSMContext) -> None:
    await cmd_survey(message, state)

@router.message(F.text == "ℹ️ Задать вопрос")
async def chat_entry(message: Message) -> None:
    await message.answer("Отлично! Задайте вопрос любыми словами — я помогу и подскажу.")

@router.message(Command("ping"))
async def ping(message: Message) -> None:
    await message.answer("pong")

@router.message(F.text)
async def text_router(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id if message.from_user else 0
    text = message.text or ""
    log_dialog(user_id, "user", text)

    # Если идёт опрос — не вмешиваемся (и не пишем в memory, чтобы не мешать анкете)
    if (await state.get_state()) is not None:
        return

    # Slash-команды ловятся отдельными хендлерами
    if text.strip().startswith("/"):
        return

    # Пишем сообщение пользователя в долговременную историю чата
    append_message(user_id, "user", text)

    # 0) Приветствия => меню
    if is_greeting(text):
        reply = "👋 Привет! Я здесь, чтобы помочь с альбомами."
        await send_menu(message, preface=reply)
        append_message(user_id, "assistant", reply)
        return

    # 1) FAQ
    res = get_faq_answer(text)
    if res.answer:
        await message.answer(res.answer)
        log_dialog(user_id, "bot", res.answer)
        append_message(user_id, "assistant", res.answer)

        if res.suggestions:
            kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text=s)] for s in res.suggestions],
                resize_keyboard=True, one_time_keyboard=True
            )
            await message.answer("📌 Возможно, вам будет интересно:", reply_markup=kb)
        return

    if res.suggestions:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=s)] for s in res.suggestions],
            resize_keyboard=True, one_time_keyboard=True
        )
        hint = "Я правильно понял вопрос? Выберите тему:"
        await message.answer(hint, reply_markup=kb)
        append_message(user_id, "assistant", hint)
        return

    # 2) GPT (с контекстом из memory_store)
    gpt_answer = await ask_gpt(user_id, text)
    if gpt_answer:
        await message.answer(gpt_answer)
        log_dialog(user_id, "bot", gpt_answer)
        # ask_gpt уже пишет в memory_store
        return

    # 3) fallback
    fallback = "🤔 Могу помочь в диалоге или оформить заявку через опрос. Что предпочитаете?"
    await message.answer(fallback)
    await send_menu(message)
    append_message(user_id, "assistant", fallback)
    log_dialog(user_id, "bot", fallback)

# ---------------------- ЗАПУСК ----------------------
async def main():
    logger.info("🚀 Бот запущен и готов к работе.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("⏹ Бот остановлен.")
