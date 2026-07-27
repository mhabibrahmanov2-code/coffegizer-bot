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

# === НАСТРОЙКИ И РОЛИ ===
BOT_TOKEN = "8888700652:AAHGPgLcdDoaBaRcjBdjLxE1KzBDh_rHUyA"

# Список Telegram ID Администраторов и Директоров (узнать в @userinfobot)
ADMIN_IDS = [1864446293, 1344845997]  # <-- ВСТАВЬТЕ СЮДА ВАШ TELEGRAM ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# === ВЕБ-СЕРВЕР ДЛЯ RENDER ===
async def handle_ping(request):
    return web.Response(text="Showcase & Finance Bot is running!")

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
    conn = sqlite3.connect("cafe_management.db")
    cursor = conn.cursor()
    # Таблица витрины
    cursor.execute('''CREATE TABLE IF NOT EXISTS showcase (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        quantity INTEGER DEFAULT 0,
        days_on_display INTEGER DEFAULT 1,
        max_days INTEGER DEFAULT 3
    )''')
    # Таблица расходов
    cursor.execute('''CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT,
        amount REAL,
        description TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    # Таблица выручки
    cursor.execute('''CREATE TABLE IF NOT EXISTS revenue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        amount REAL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

def parse_text_items(text: str):
    items = []
    lines = text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        match = re.search(r'^(.*?)\s*[-:]?\s*(\d+)\s*шт\.?$', line, re.IGNORECASE)
        if match:
            items.append((match.group(1).strip(), int(match.group(2))))
        else:
            nums = re.findall(r'\d+', line)
            if nums:
                qty = int(nums[-1])
                name = re.sub(r'\d+', '', line).replace('-', '').strip()
                if name:
                    items.append((name, qty))
    return items

# === СОСТОЯНИЯ ===
class BotStates(StatesGroup):
    waiting_for_morning_list = State()
    waiting_for_evening_list = State()
    answering_restock = State()
    adding_expense = State()
    adding_revenue = State()

# === КЛАВИАТУРЫ ПО РОЛЯМ ===
def get_main_keyboard(user_id: int):
    # Если пользователь АДМИН / ДИРЕКТОР
    if user_id in ADMIN_IDS:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="☀️ Открытие (Витрина)"), KeyboardButton(text="🌙 Закрытие (Витрина)")],
                [KeyboardButton(text="📊 Финансы и Выручка"), KeyboardButton(text="💸 Добавить расход")],
                [KeyboardButton(text="💵 Внести выручку"), KeyboardButton(text="🔍 Контроль свежести")]
            ],
            resize_keyboard=True
        )
    # Если обычный БАРИСТА
    else:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="☀️ Открытие (Витрина)"), KeyboardButton(text="🌙 Закрытие (Витрина)")],
                [KeyboardButton(text="🔍 Контроль свежести")]
            ],
            resize_keyboard=True
        )

# === ОБРАБОТЧИКИ ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    role_title = "👑 Администратор / Директор" if message.from_user.id in ADMIN_IDS else "☕ Бариста"
    await message.answer(
        f"Добро пожаловать! Ваш статус: **{role_title}**\n\n"
        "Выберите нужное действие в меню ниже:",
        reply_markup=get_main_keyboard(message.from_user.id),
        parse_mode="Markdown"
    )

# --- ☀️ УТРЕННЕЕ ОТКРЫТИЕ (Для всех) ---
@dp.message(F.text.contains("Открытие"))
async def start_morning(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.waiting_for_morning_list)
    await message.answer(
        "☀️ **Напишите список выставленной витрины:**\n\n"
        "**Пример:**\n"
        "Чизкейк Дубайский 1\n"
        "Круассан с ветчиной 5\n"
        "Торт Медовик 2",
        parse_mode="Markdown"
    )

@dp.message(BotStates.waiting_for_morning_list)
async def process_morning_list(message: types.Message, state: FSMContext):
    parsed = parse_text_items(message.text)
    if not parsed:
        await message.answer("⚠️ Не удалось разобрать текст. Напишите в формате: `Название количество`", parse_mode="Markdown")
        return

    conn = sqlite3.connect("cafe_management.db")
    cursor = conn.cursor()
    report = "✅ **Принято на утреннюю витрину:**\n\n"
    for name, qty in parsed:
        cursor.execute("INSERT INTO showcase (name, quantity, days_on_display) VALUES (?, ?, 1) "
                       "ON CONFLICT(name) DO UPDATE SET quantity = ?", (name, qty, qty))
        report += f"• {name}: {qty} шт.\n"
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(report, reply_markup=get_main_keyboard(message.from_user.id), parse_mode="Markdown")

# --- 🌙 ВЕЧЕРНЕЕ ЗАКРЫТИЕ (Для всех) ---
@dp.message(F.text.contains("Закрытие"))
async def start_evening(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.waiting_for_evening_list)
    await message.answer("🌙 **Напишите, что осталось на витрине вечером:**\n(Если ничего не осталось — отправьте 0)", parse_mode="Markdown")

@dp.message(BotStates.waiting_for_evening_list)
async def process_evening_list(message: types.Message, state: FSMContext):
    parsed = [] if message.text.strip() == "0" else parse_text_items(message.text)
    conn = sqlite3.connect("cafe_management.db")
    cursor = conn.cursor()
    
    evening_dict = {name: qty for name, qty in parsed}
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
        await message.answer("✅ Смена закрыта! Витрина пуста.", reply_markup=get_main_keyboard(message.from_user.id))
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
        await message.answer(f"❓ Позиция **{item_name}** осталась на витрине.\n\nВы докладывали свежий из заморозки в течение дня или он лежит с утра?", reply_markup=kb, parse_mode="Markdown")
        await state.set_state(BotStates.answering_restock)
    else:
        await message.answer("✅ Сверка завершена! Вечерняя смена закрыта.", reply_markup=get_main_keyboard(message.from_user.id))
        await state.clear()

@dp.callback_query(F.data.startswith("restock_"), BotStates.answering_restock)
async def process_restock_answer(callback: types.CallbackQuery, state: FSMContext):
    answer = callback.data.split("_")[1]
    data = await state.get_data()
    q_index = data['q_index']
    item_name = data['questions'][q_index]
    
    conn = sqlite3.connect("cafe_management.db")
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

# --- 🔍 ПОКАЗ СВЕЖЕСТИ (Для всех) ---
@dp.message(F.text.contains("Контроль свежести"))
async def check_showcase(message: types.Message):
    conn = sqlite3.connect("cafe_management.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, quantity, days_on_display, max_days FROM showcase WHERE quantity > 0")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        await message.answer("🍰 Витрина пуста.")
        return
        
    report = "📋 **СТАТУС СВЕЖЕСТИ ВИТРИНЫ:**\n\n"
    for name, qty, days, max_d in rows:
        if days > max_d:
            status = "🔴 **ПРОСРОЧЕНО (Списать!)**"
        elif days == max_d:
            status = f"🟡 {days}-й день (Срок истекает сегодня)"
        else:
            status = f"🟢 Свежий ({days}-й день)"
        report += f"• **{name}**: {qty} шт.\n  └ Status: {status}\n"
        
    await message.answer(report, parse_mode="Markdown")

# --- 👑 ФИНАНСЫ И АДМИНИСТРИРОВАНИЕ (Только для ADMIN_IDS) ---
@dp.message(F.text.contains("Финансы"))
async def show_finances(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
        
    conn = sqlite3.connect("cafe_management.db")
    cursor = conn.cursor()
    
    # Выручка за сегодня
    cursor.execute("SELECT SUM(amount) FROM revenue WHERE date(created_at) = date('now')")
    rev_today = cursor.fetchone()[0] or 0.0
    
    # Расходы за сегодня
    cursor.execute("SELECT SUM(amount) FROM expenses WHERE date(created_at) = date('now')")
    exp_today = cursor.fetchone()[0] or 0.0
    
    # Последние 5 расходов
    cursor.execute("SELECT description, amount FROM expenses ORDER BY id DESC LIMIT 5")
    expenses_list = cursor.fetchall()
    conn.close()
    
    report = f"📊 **ФИНАНСОВЫЙ ОТЧЕТ ЗА СЕГОДНЯ:**\n\n"
    report += f"💵 **Выручка:** {rev_today:,.2f} руб.\n"
    report += f"💸 **Расходы:** {exp_today:,.2f} руб.\n"
    report += f"📈 **Чистая прибыль:** {(rev_today - exp_today):,.2f} руб.\n\n"
    
    if expenses_list:
        report += "📝 **Последние внесенные расходы:**\n"
        for desc, amt in expenses_list:
            report += f"• {desc}: {amt} руб.\n"
            
    await message.answer(report, parse_mode="Markdown")

@dp.message(F.text.contains("Добавить расход"))
async def add_expense_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(BotStates.adding_expense)
    await message.answer("💸 **Введите расход и сумму через пробел:**\n(Например: `Закупка молока 450` или `Такси 300`)", parse_mode="Markdown")

@dp.message(BotStates.adding_expense)
async def process_add_expense(message: types.Message, state: FSMContext):
    nums = re.findall(r'\d+', message.text)
    if not nums:
        await message.answer("⚠️ Не удалось распознать сумму. Напишите: `Описание Сумма`")
        return
    
    amount = float(nums[-1])
    desc = re.sub(r'\d+', '', message.text).strip()
    
    conn = sqlite3.connect("cafe_management.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO expenses (description, amount) VALUES (?, ?)", (desc, amount))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(f"✅ Расход **{desc}** на сумму **{amount} руб.** успешно записан!", reply_markup=get_main_keyboard(message.from_user.id), parse_mode="Markdown")

@dp.message(F.text.contains("Внести выручку"))
async def add_revenue_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(BotStates.adding_revenue)
    await message.answer("💵 **Введите сумму кассовой выручки за день:**", parse_mode="Markdown")

@dp.message(BotStates.adding_revenue)
async def process_add_revenue(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").strip())
        conn = sqlite3.connect("cafe_management.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO revenue (amount) VALUES (?)", (amount,))
        conn.commit()
        conn.close()
        
        await state.clear()
        await message.answer(f"✅ Выручка **{amount} руб.** успешно внесена!", reply_markup=get_main_keyboard(message.from_user.id))
    except ValueError:
        await message.answer("⚠️ Введите корректное число (сумму выручки).")

# === ЗАПУСК ===
async def main():
    init_db()
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
