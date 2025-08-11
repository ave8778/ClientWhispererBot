# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import re
import os

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from dotenv import load_dotenv

from knowledge_base import normalize
from memory_store import update_profile

router = Router()

# --- ENV for OWNER notification ---
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

OWNER_ID = int(os.getenv("OWNER_ID", "0") or "0")

# --- States ---
class Survey(StatesGroup):
    level = State()            # школа/сад
    org_number = State()       # номер школы/сада
    album_type = State()       # общий/индивидуальный
    count_children = State()   # сколько детей берут альбомы
    contact_method = State()   # VK/WhatsApp
    contact_value = State()    # ссылка/номер
    confirm = State()          # подтверждение

# --- Helpers / Keyboards ---
PHONE_RE = re.compile(r"^\+?\d[\d\s\-\(\)]{7,}$", re.U | re.I)

def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _lead_path() -> Path:
    p = Path(__file__).parent / "data"
    p.mkdir(exist_ok=True)
    return p / "leads.csv"

def save_lead(row: list[str]) -> None:
    path = _lead_path()
    if not path.exists():
        path.write_text("ts,user_id,level,org_number,album_type,count_children,contact_method,contact,username,full_name\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(",".join(x.replace(",", " ").strip() for x in row) + "\n")

def level_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Детский сад", callback_data="level_kinder"),
         InlineKeyboardButton(text="Школа", callback_data="level_school")]
    ])

def album_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Общий", callback_data="album_common"),
         InlineKeyboardButton(text="Индивидуальный", callback_data="album_individual")]
    ])

def contact_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="VK", callback_data="contact_vk"),
         InlineKeyboardButton(text="WhatsApp", callback_data="contact_wa")]
    ])

def confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить", callback_data="confirm_send")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="confirm_cancel")]
    ])

def summary_text(data: dict) -> str:
    return (
        "📝 *Проверьте заявку:*\n"
        f"• Уровень: **{data.get('level','–')}**\n"
        f"• № школы/сада: **{data.get('org_number','–')}**\n"
        f"• Тип альбома: **{data.get('album_type','–')}**\n"
        f"• Кол-во детей: **{data.get('count_children','–')}**\n"
        f"• Связь: **{data.get('contact_method','–')} — {data.get('contact','–')}**\n"
    )

def explain_diff(level: str | None) -> str:
    lvl = (level or "").lower()
    if "сад" in lvl:
        return (
            "Разница:\n"
            "• *Общий* — вёрстка одна на всех, ребёнок не на всех фото. Формат 20×30, 20 стр. — **3500 ₽**.\n"
            "• *Индивидуальный* — персональная вёрстка; Мини **2700 ₽**, Лайт **3700 ₽**, Макси **4600 ₽**.\n"
            "_Условия: от 15 альбомов и съёмка до марта._"
        )
    if "школ" in lvl:
        return (
            "Разница:\n"
            "• *Общий* — «Классный» **2200 ₽**, «Дружный» **3200 ₽**, «Большой» **4400 ₽**.\n"
            "• *Индивидуальный* — «Планшет» **2000 ₽**, «Мини» **3300 ₽**, «Макси» **4100 ₽**.\n"
            "_Условия: от 15 альбомов и съёмка до марта._"
        )
    # если уровень неизвестен — попросим выбрать
    return (
        "Для точной разницы подскажите, это для *детского сада* или *школы*? "
        "Выберите ниже.",)

# --- Start survey ---
@router.message(Command("survey"))
@router.message(Command("book"))
async def cmd_survey(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Давайте быстро оформим заявку.\n"
        "Сначала выберите, это *детский сад* или *школа*:",
        reply_markup=level_kb()
    )
    await state.set_state(Survey.level)

@router.message(F.text.func(lambda t: t and ("пройти опрос" in t.lower() or "забронировать" in t.lower())))
async def trigger_survey(message: Message, state: FSMContext):
    if await state.get_state() is None:
        await cmd_survey(message, state)

# --- Flow ---
@router.callback_query(Survey.level, F.data.in_(("level_kinder", "level_school")))
async def set_level(cb: CallbackQuery, state: FSMContext):
    level = "детский сад" if cb.data == "level_kinder" else "школа"
    await state.update_data(level=level)
    update_profile(cb.from_user.id, level=level)  # persist
    await cb.message.edit_text("Укажите номер школы/сада (только цифры), например: 27")
    await state.set_state(Survey.org_number)
    await cb.answer()

# Позволяем вводить уровень текстом на шаге выбора
@router.message(Survey.level, F.text)
async def set_level_by_text(message: Message, state: FSMContext):
    t = normalize(message.text or "")
    if "сад" in t:
        level = "детский сад"
    elif "школ" in t:
        level = "школа"
    else:
        await message.answer("Пожалуйста, выберите кнопкой: *Детский сад* или *Школа*.")
        return
    await state.update_data(level=level)
    update_profile(message.from_user.id, level=level)
    await message.answer("Укажите номер школы/сада (только цифры), например: 27")
    await state.set_state(Survey.org_number)

@router.message(Survey.org_number, F.text)
async def set_org_number(message: Message, state: FSMContext):
    # ГАРАНТИЯ ПОРЯДКА: если уровень не выбран, возвращаем на шаг выбора
    data = await state.get_data()
    if not data.get("level"):
        await message.answer("Сначала выберите: это *детский сад* или *школа*.", reply_markup=level_kb())
        await state.set_state(Survey.level)
        return

    txt = re.sub(r"[^\d]", "", message.text or "")
    if not txt:
        await message.answer("Введите, пожалуйста, *номер* цифрами.")
        return
    await state.update_data(org_number=txt)
    update_profile(message.from_user.id, org_number=txt)
    await message.answer("Какой тип альбома интересует — *Общий* или *Индивидуальный*?", reply_markup=album_kb())
    await state.set_state(Survey.album_type)

@router.callback_query(Survey.album_type, F.data.in_(("album_common", "album_individual")))
async def set_album_type(cb: CallbackQuery, state: FSMContext):
    album = "общий" if cb.data == "album_common" else "индивидуальный"
    await state.update_data(album_type=album)
    update_profile(cb.from_user.id, album_type=album)
    await cb.message.edit_text("Сколько *детей* будут брать альбомы? (числом)")
    await state.set_state(Survey.count_children)
    await cb.answer()

@router.message(Survey.album_type, F.text)
async def album_type_text(message: Message, state: FSMContext):
    data = await state.get_data()
    t = normalize(message.text or "")
    if "разниц" in t or "что такое" in t or "объяс" in t:
        diff = explain_diff(data.get("level"))
        if isinstance(diff, tuple):  # неизвестен уровень
            await message.answer(diff[0], reply_markup=level_kb())
            await state.set_state(Survey.level)
        else:
            await message.answer(diff, reply_markup=album_kb())
        return
    if "общ" in t:
        await state.update_data(album_type="общий")
        update_profile(message.from_user.id, album_type="общий")
        await message.answer("Принято: *общий*. Сколько детей будут брать альбомы? (числом)")
        await state.set_state(Survey.count_children)
        return
    if "инд" in t:
        await state.update_data(album_type="индивидуальный")
        update_profile(message.from_user.id, album_type="индивидуальный")
        await message.answer("Принято: *индивидуальный*. Сколько детей будут брать альбомы? (числом)")
        await state.set_state(Survey.count_children)
        return
    await message.answer("Выберите, пожалуйста, тип альбома кнопкой ниже:", reply_markup=album_kb())

@router.message(Survey.count_children, F.text)
async def set_count_children(message: Message, state: FSMContext):
    txt = message.text.strip()
    if not txt.isdigit() or int(txt) <= 0 or int(txt) > 1000:
        await message.answer("Введите, пожалуйста, *число* от 1 до 1000.")
        return
    await state.update_data(count_children=int(txt))
    update_profile(message.from_user.id, count_children=int(txt))
    await message.answer("Как удобнее связаться — *VK* или *WhatsApp*?", reply_markup=contact_kb())
    await state.set_state(Survey.contact_method)

@router.callback_query(Survey.contact_method, F.data.in_(("contact_vk", "contact_wa")))
async def set_contact_method(cb: CallbackQuery, state: FSMContext):
    method = "VK" if cb.data == "contact_vk" else "WhatsApp"
    await state.update_data(contact_method=method)
    update_profile(cb.from_user.id, contact_method=method)
    if method == "VK":
        await cb.message.edit_text("Пришлите *ссылку на VK* или @ник.")
    else:
        await cb.message.edit_text("Пришлите *номер WhatsApp* в формате +7...")
    await state.set_state(Survey.contact_value)
    await cb.answer()

@router.message(Survey.contact_value, F.text)
async def set_contact_value(message: Message, state: FSMContext):
    contact = message.text.strip()
    data = await state.get_data()
    if data.get("contact_method") == "WhatsApp" and not PHONE_RE.match(contact):
        await message.answer("Похоже, номер не в формате. Пример: +7 999 123-45-67")
        return
    await state.update_data(contact=contact)
    update_profile(message.from_user.id, contact=contact)
    data = await state.get_data()
    await message.answer(summary_text(data), reply_markup=confirm_kb())
    await state.set_state(Survey.confirm)

@router.callback_query(Survey.confirm, F.data == "confirm_cancel")
async def cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Заявка отменена. Если нужно — можно начать заново: /survey")
    await cb.answer()

@router.callback_query(Survey.confirm, F.data == "confirm_send")
async def send(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    user = cb.from_user
    ts = _now()
    row = [
        ts,
        str(user.id),
        data.get("level",""),
        data.get("org_number",""),
        data.get("album_type",""),
        str(data.get("count_children","")),
        data.get("contact_method",""),
        data.get("contact",""),
        (user.username or ""),
        f"{user.first_name or ''} {user.last_name or ''}".strip(),
    ]
    save_lead(row)

    # Notify owner
    if OWNER_ID:
        owner_text = (
            "🆕 *Новая заявка (опрос)*\n"
            f"{summary_text(data)}\n"
            f"От: @{user.username or '—'} (id {user.id})"
        )
        try:
            await cb.message.bot.send_message(OWNER_ID, owner_text, parse_mode="Markdown")
        except Exception:
            pass

    await cb.message.edit_text("Спасибо! Заявка отправлена. Мы свяжемся с вами в ближайшее время.")
    await cb.answer()
