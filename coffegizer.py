import os
import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web

# === НАСТРОЙКИ ===
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

# === БАЗА ДАННЫХ ВИТРИНЫ ===
def init_db():
    conn = sqlite3.connect("showcase.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS display_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        quantity INTEGER DEFAULT 0,
        days_on_display INTEGER DEFAULT 1,
        max_days INTEGER DEFAULT 3
    )''')
    
    # Ассортимент витрины и их максимальный срок хранения (в днях)
    items = [
        ("Чизкейк Нью-Йорк", 3),
        ("Чизкейк Сан-Себастьян", 3),
        ("Чизкейк Дубайский", 3),
        ("Торт Медовик", 2),
        ("Торт Наполеон", 2),
        ("Круассан классический", 1),
        ("Сэндвич с птицей", 1)
    ]
    for name, max_d in items:
        cursor.execute("INSERT OR IGNORE INTO display_items (name, max_days) VALUES (?, ?)", (name, max_d))
    conn.commit()
    conn.close()

# === СОСТОЯНИЯ ===
class ShowcaseStates(StatesGroup):
    setting_morning_qty = State()
    setting_evening_qty = State()
    answering_restock = State()

# === НОВАЯ КЛАВИАТУРА ВИТРИНЫ ===
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
    await message.answer("🍰 Бот контроля свежести витрины запущен!\nВыберите действие в меню ниже:", reply_markup=main_kb)

# --- 🔍 ПОКАЗ СТАТУСА СВЕЖЕСТИ ---
@dp.message(F.text.contains("Контроль свежести"))
async def check_showcase(message: types.Message):
    conn = sqlite3.connect("showcase.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, quantity, days_on_display, max_days FROM display_items WHERE quantity > 0")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        await message.answer("🍰 Витрина сейчас пуста.")
        return
        
    report = "🍰 **ТЕКУЩЕЕ СОСТОЯНИЕ ВИТРИНЫ:**\n\n"
    for name, qty, days, max_d in rows:
        if days > max_d:
            status = "❌ **ПРОСРОЧЕНО (Списать!)**"
        elif days == max_d:
            status = "⚠️ **Срок истекает сегодня**"
        else:
            status = "✅ Свежее"
            
        report += f"• **{name}**: {qty} шт.\n  └ Статус: {status} (На витрине: {days}-й день из {max_d})\n\n"
        
    await message.answer(report, parse_mode="Markdown")

# --- ☀️ УТРЕННЯЯ СМЕНА ---
@dp.message(F.text.contains("Открытие"))
async def start_morning(message: types.Message, state: FSMContext):
    conn = sqlite3.connect("showcase.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM display_items")
    items = cursor.fetchall()
    conn.close()
    
    await state.update_data(items=items, index=0, morning_data={})
    await ask_next_morning_item(message, state)

async def ask_next_morning_item(message: types.Message, state: FSMContext):
    data = await state.get_data()
    index = data['index']
    items = data['items']
    
    if index < len(items):
        item_name = items[index][0]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=str(i), callback_data=f"m_qty_{i}") for i in range(6)]
        ])
        await message.answer(f"☀️ Сколько **{item_name}** выставили на витрину?", reply_markup=kb, parse_mode="Markdown")
        await state.set_state(ShowcaseStates.setting_morning_qty)
    else:
        conn = sqlite3.connect("showcase.db")
        cursor = conn.cursor()
        for name, qty in data['morning_data'].items():
            cursor.execute("UPDATE display_items SET quantity = ? WHERE name = ?", (qty, name))
        conn.commit()
        conn.close()
        
        await message.answer("✅ Утренний учет витрины сохранен! Хорошей смены!", reply_markup=main_kb)
        await state.clear()

@dp.callback_query(F.data.startswith("m_qty_"), ShowcaseStates.setting_morning_qty)
async def process_morning_qty(callback: types.CallbackQuery, state: FSMContext):
    qty = int(callback.data.split("_")[2])
    data = await state.get_data()
    index = data['index']
    item_name = data['items'][index][0]
    
    morning_data = data['morning_data']
    morning_data[item_name] = qty
    
    await state.update_data(morning_data=morning_data, index=index + 1)
    await callback.answer()
    await ask_next_morning_item(callback.message, state)

# --- 🌙 ВЕЧЕРНЯЯ СМЕНА И ПРОВЕРКА РОТАЦИИ ---
@dp.message(F.text.contains("Закрытие"))
async def start_evening(message: types.Message, state: FSMContext):
    conn = sqlite3.connect("showcase.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, quantity FROM display_items WHERE quantity > 0")
    items = cursor.fetchall()
    conn.close()
    
    if not items:
        await message.answer("На витрине с утра ничего не было.")
        return

    await state.update_data(items=items, index=0, evening_data={})
    await ask_next_evening_item(message, state)

async def ask_next_evening_item(message: types.Message, state: FSMContext):
    data = await state.get_data()
    index = data['index']
    items = data['items']
    
    if index < len(items):
        item_name = items[index][0]
        max_q = items[index][1]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=str(i), callback_data=f"e_qty_{i}") for i in range(max_q + 1)]
        ])
        await message.answer(f"🌙 Сколько **{item_name}** осталось вечером? (Утром было: {max_q} шт.)", reply_markup=kb, parse_mode="Markdown")
        await state.set_state(ShowcaseStates.setting_evening_qty)
    else:
        await start_restock_check(message, state)

@dp.callback_query(F.data.startswith("e_qty_"), ShowcaseStates.setting_evening_qty)
async def process_evening_qty(callback: types.CallbackQuery, state: FSMContext):
    qty = int(callback.data.split("_")[2])
    data = await state.get_data()
    index = data['index']
    item_name = data['items'][index][0]
    
    evening_data = data['evening_data']
    evening_data[item_name] = qty
    
    await state.update_data(evening_data=evening_data, index=index + 1)
    await callback.answer()
    await ask_next_evening_item(callback.message, state)

async def start_restock_check(message: types.Message, state: FSMContext):
    data = await state.get_data()
    evening_data = data['evening_data']
    restock_questions = [name for name, qty in evening_data.items() if qty > 0]
    
    await state.update_data(restock_questions=restock_questions, q_index=0)
    await ask_restock_question(message, state)

async def ask_restock_question(message: types.Message, state: FSMContext):
    data = await state.get_data()
    q_index = data['q_index']
    questions = data['restock_questions']
    
    if q_index < len(questions):
        item_name = questions[q_index]
        qty = data['evening_data'][item_name]
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Докладывали свежие из морозильника", callback_data="restock_yes")],
            [InlineKeyboardButton(text="⏳ Лежит с утра / прошлых дней", callback_data="restock_no")]
        ])
        await message.answer(
            f"❓ Позиция **{item_name}** осталась на витрине ({qty} шт.).\n\nВы выставляли свежие десерты из заморозки в течение дня или это тот же десерт, что и с утра?",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        await state.set_state(ShowcaseStates.answering_restock)
    else:
        conn = sqlite3.connect("showcase.db")
        cursor = conn.cursor()
        for name, qty in data['evening_data'].items():
            cursor.execute("UPDATE display_items SET quantity = ? WHERE name = ?", (qty, name))
        conn.commit()
        conn.close()
        
        await message.answer("✅ Вечерний учет сохранен! Смена закрыта.", reply_markup=main_kb)
        await state.clear()

@dp.callback_query(F.data.startswith("restock_"), ShowcaseStates.answering_restock)
async def process_restock_answer(callback: types.CallbackQuery, state: FSMContext):
    answer = callback.data.split("_")[1]
    data = await state.get_data()
    q_index = data['q_index']
    item_name = data['restock_questions'][q_index]
    
    conn = sqlite3.connect("showcase.db")
    cursor = conn.cursor()
    if answer == "yes":
        cursor.execute("UPDATE display_items SET days_on_display = 1 WHERE name = ?", (item_name,))
    else:
        cursor.execute("UPDATE display_items SET days_on_display = days_on_display + 1 WHERE name = ?", (item_name,))
    conn.commit()
    conn.close()
    
    await state.update_data(q_index=q_index + 1)
    await callback.answer()
    await ask_restock_question(callback.message, state)

# === ЗАПУСК ===
async def main():
    init_db()
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
