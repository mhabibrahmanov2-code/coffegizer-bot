import os
import asyncio
import logging
import sqlite3
import re
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web

BOT_TOKEN = "8888700652:AAHGPgLcdDoaBaRcjBdjLxE1KzBDh_rHUyA"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# === ВЕБ-СЕРВЕР ДЛЯ RENDER ===
async def handle_ping(request):
    return web.Response(text="Showcase Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    app.router.add_get('/health', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# === БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect("showcase.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS showcase (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        quantity INTEGER DEFAULT 0,
        days_on_display INTEGER DEFAULT 1
    )''')
    conn.commit()
    conn.close()

# Парсер текстового списка (находит название и цифру в конце строки)
def parse_text_items(text: str):
    items = []
    lines = text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Поиск числа в конце строки (например, "Чизкейк Дубайский 2" или "Наполеон - 1")
        match = re.search(r'^(.*?)\s*[-:]?\s*(\d+)\s*шт\.?$', line, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            qty = int(match.group(2))
            items.append((name, qty))
        else:
            # Если число не в конце, пробуем вытащить любое последнее число
            nums = re.findall(r'\d+', line)
            if nums:
                qty = int(nums[-1])
                name = re.sub(r'\d+', '', line).replace('-', '').strip()
                if name:
                    items.append((name, qty))
    return items

# === СОСТОЯНИЯ (FSM) ===
class ShowcaseStates(StatesGroup):
    waiting_for_morning_list = State()
    waiting_for_evening_list = State()
    answering_restock = State()

# === КЛАВИАТУРА ===
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="☀️ Открытие (Витрина утро)"), KeyboardButton(text="🌙 Закрытие (Витрина вечер)")],
        [KeyboardButton(text="🔍 Контроль свежести (Статус)")]
    ],
    resize_keyboard=True
)

# === ОБРАБОТЧИКИ ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🍰 **Бот учета и свежести витрины**\n\n"
        "Нажмите **☀️ Открытие** утром и отправьте список выставленных десертов текстом!",
        reply_markup=main_kb,
        parse_mode="Markdown"
    )

# --- ☀️ УТРЕННЕЕ ОТКРЫТИЕ ---
@dp.message(F.text.contains("Открытие"))
async def start_morning(message: types.Message, state: FSMContext):
    await state.set_state(ShowcaseStates.waiting_for_morning_list)
    await message.answer(
        "☀️ **Напишите, что именно вы выставили на витрину:**\n\n"
        "Каждую позицию пишите с новой строчки и указывайте количество.\n\n"
        "**Пример:**\n"
        "Чизкейк Дубайский 1\n"
        "Круассан с ветчиной 5\n"
        "Торт Медовик 2",
        parse_mode="Markdown"
    )

@dp.message(ShowcaseStates.waiting_for_morning_list)
async def process_morning_list(message: types.Message, state: FSMContext):
    parsed = parse_text_items(message.text)
    if not parsed:
        await message.answer("⚠️ Не удалось распознать количество. Напишите список в формате:\nНазвание количество\n(Например: `Наполеон 2`)", parse_mode="Markdown")
        return

    conn = sqlite3.connect("showcase.db")
    cursor = conn.cursor()
    
    # Сбрасываем старую витрину или обновляем позиции
    report = "✅ **Принято на утреннюю витрину:**\n\n"
    for name, qty in parsed:
        # Если позиция уже была, оставляем её дни, меняем кол-во
        cursor.execute("INSERT INTO showcase (name, quantity, days_on_display) VALUES (?, ?, 1) "
                       "ON CONFLICT(name) DO UPDATE SET quantity = ?", (name, qty, qty))
        report += f"• {name}: {qty} шт.\n"
        
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(report, reply_markup=main_kb, parse_mode="Markdown")

# --- 🌙 ВЕЧЕРНЕЕ ЗАКРЫТИЕ ---
@dp.message(F.text.contains("Закрытие"))
async def start_evening(message: types.Message, state: FSMContext):
    await state.set_state(ShowcaseStates.waiting_for_evening_list)
    await message.answer(
        "🌙 **Напишите, что осталось на витрине в конце смены:**\n\n"
        "**Пример:**\n"
        "Чизкейк Дубайский 1\n"
        "Торт Медовик 1\n\n"
        "*(Если витрина пустая — просто напишите: 0)*",
        parse_mode="Markdown"
    )

@dp.message(ShowcaseStates.waiting_for_evening_list)
async def process_evening_list(message: types.Message, state: FSMContext):
    if message.text.strip() == "0":
        parsed = []
    else:
        parsed = parse_text_items(message.text)

    conn = sqlite3.connect("showcase.db")
    cursor = conn.cursor()
    
    # Сверяем вечерний остаток
    evening_dict = {name: qty for name, qty in parsed}
    
    # Получаем все утренние позиции
    cursor.execute("SELECT name, quantity FROM showcase WHERE quantity > 0")
    morning_items = cursor.fetchall()
    
    restock_questions = []
    
    for name, m_qty in morning_items:
        e_qty = evening_dict.get(name, 0)
        cursor.execute("UPDATE showcase SET quantity = ? WHERE name = ?", (e_qty, name))
        if e_qty > 0:
            restock_questions.append(name)

    conn.commit()
    conn.close()
    
    if restock_questions:
        await state.update_data(questions=restock_questions, q_index=0)
        await ask_restock_question(message, state)
    else:
        await message.answer("✅ Вечерний остаток сохранен! Витрина пуста. Хорошего отдыха!", reply_markup=main_kb)
        await state.clear()

async def ask_restock_question(message: types.Message, state: FSMContext):
    data = await state.get_data()
    q_index = data['q_index']
    questions = data['questions']
    
    if q_index < len(questions):
        item_name = questions[q_index]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Докладывали свежий из заморозки", callback_data="restock_yes")],
            [InlineKeyboardButton(text="⏳ Лежит с утра / прошлых дней", callback_data="restock_no")]
        ])
        await message.answer(
            f"❓ Позиция **{item_name}** осталась на витрине.\n\n Вы выставляли свежий из заморозки в течение дня или это тот самый, что выставили с утра?",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        await state.set_state(ShowcaseStates.answering_restock)
    else:
        await message.answer("✅ Сверка свежести завершена! Вечерняя смена закрыта.", reply_markup=main_kb)
        await state.clear()

@dp.callback_query(F.data.startswith("restock_"), ShowcaseStates.answering_restock)
async def process_restock_answer(callback: types.CallbackQuery, state: FSMContext):
    answer = callback.data.split("_")[1]
    data = await state.get_data()
    q_index = data['q_index']
    item_name = data['questions'][q_index]
    
    conn = sqlite3.connect("showcase.db")
    cursor = conn.cursor()
    if answer == "yes":
        cursor.execute("UPDATE showcase SET days_on_display = 1 WHERE name = ?", (item_name,))
    else:
        cursor.execute("UPDATE showcase SET days_on_display = days_on_display + 1 WHERE name = ?", (item_name,))
    conn.commit()
    conn.close()
    
    await state.update_data(q_index=q_index + 1)
    await callback.answer()
    await ask_restock_question(callback.message, state)

# --- 🔍 ПОКАЗ СТАТУСА СВЕЖЕСТИ ---
@dp.message(F.text.contains("Контроль свежести"))
async def check_showcase(message: types.Message):
    conn = sqlite3.connect("showcase.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, quantity, days_on_display FROM showcase WHERE quantity > 0")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        await message.answer("🍰 Витрина пуста.")
        return
        
    report = "📋 **СТАТУС ВИТРИНЫ И СВЕЖЕСТЬ:**\n\n"
    for name, qty, days in rows:
        if days == 1:
            status = "🟢 Свежий (1-й день)"
        elif days == 2:
            status = "🟡 2-й день на витрине"
        else:
            status = f"🔴 {days}-й день (**ВНИМАНИЕ! Проверить / Списать**)"
            
        report += f"• **{name}**: {qty} шт.\n  └ {status}\n"
        
    await message.answer(report, parse_mode="Markdown")

# === ЗАПУСК ===
async def main():
    init_db()
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
