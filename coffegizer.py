import os
import asyncio
import logging
import sqlite3
import re
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web

# === НАСТРОЙКИ И РОЛИ ===
BOT_TOKEN = "8888700652:AAHGPgLcdDoaBaRcjBdjLxE1KzBDh_rHUyA"

# Список Telegram ID Администраторов/Директоров
ADMIN_IDS = [1864446293, 1344845997]  # <-- Вставьте ваш Telegram ID

EVOTOR_SECRET_TOKEN = "coffegizer_secret_123"  # Токен, который вы указали в поле "Ваш токен"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# === ВЕБ-СЕРВЕР ДЛЯ RENDER И ЭВОТОРА ===
async def handle_ping(request):
    return web.Response(text="Showcase & Evotor Bot is running!")

# Прием уведомлений о продажах и выручке от Эвотора
async def handle_evotor_webhook(request):
    try:
        data = await request.json()
        logging.info(f"Получены данные от Эвотор: {data}")
        
        # Если Эвотор передает сумму чека/продажи
        if isinstance(data, dict):
            amount = data.get("body", {}).get("total", 0) or data.get("totalSum", 0)
            if amount > 0:
                conn = sqlite3.connect("cafe_management.db")
                cursor = conn.cursor()
                cursor.execute("INSERT INTO revenue (amount, created_at) VALUES (?, CURRENT_DATE)", (float(amount),))
                conn.commit()
                conn.close()
                logging.info(f"Автоматически зачислена выручка с Эвотора: {amount} руб.")
    except Exception as e:
        logging.error(f"Ошибка при обработке вебхука Эвотора: {e}")
        
    return web.Response(text="OK", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    app.router.add_get('/health', handle_ping)
    app.router.add_post('/evotor-webhook', handle_evotor_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# === БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect("cafe_management.db")
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS showcase (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        quantity INTEGER DEFAULT 0,
        days_on_display INTEGER DEFAULT 1,
        max_days INTEGER DEFAULT 3
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT,
        amount REAL,
        description TEXT,
        created_at DATE DEFAULT CURRENT_DATE
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS revenue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        amount REAL,
        created_at DATE DEFAULT CURRENT_DATE
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
    waiting_for_day_report = State()
    waiting_for_edit_date = State()
    setting_new_revenue = State()

# === КЛАВИАТУРА ===
def get_main_keyboard(user_id: int):
    if user_id in ADMIN_IDS:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="☀️ Открытие (Витрина)"), KeyboardButton(text="🌙 Закрытие (Витрина)")],
                [KeyboardButton(text="📊 Итоги за месяц"), KeyboardButton(text="📆 Отчет за день")],
                [KeyboardButton(text="💸 Добавить расход"), KeyboardButton(text="💵 Внести выручку вручную")],
                [KeyboardButton(text="✏️ Редактировать день"), KeyboardButton(text="🔍 Контроль свежести")]
            ],
            resize_keyboard=True
        )
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

# --- ☀️ УТРЕННЕЕ ОТКРЫТИЕ ---
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

# --- 🌙 ВЕЧЕРНЕЕ ЗАКРЫТИЕ ---
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

# --- 🔍 ПОКАЗ СВЕЖЕСТИ ---
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

# --- 📊 БОЛЬШАЯ ТАБЛИЦА ЗА МЕСЯЦ ---
@dp.message(F.text.contains("Итоги за месяц"))
async def show_month_summary(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
        
    current_month = datetime.now().strftime("%Y-%m")
    
    conn = sqlite3.connect("cafe_management.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT DISTINCT created_at FROM (SELECT created_at FROM revenue WHERE created_at LIKE ? UNION SELECT created_at FROM expenses WHERE created_at LIKE ?) ORDER BY created_at ASC", (f"{current_month}%", f"{current_month}%"))
    dates = [row[0] for row in cursor.fetchall()]
    
    if not dates:
        await message.answer(f"📊 В месяце {current_month} записей пока нет.")
        conn.close()
        return
        
    report = f"📊 **БОЛЬШАЯ ТАБЛИЦА ЗА {current_month}:**\n\n"
    total_rev = 0
    total_exp = 0
    
    for d in dates:
        cursor.execute("SELECT SUM(amount) FROM revenue WHERE created_at = ?", (d,))
        r = cursor.fetchone()[0] or 0.0
        
        cursor.execute("SELECT description, amount FROM expenses WHERE created_at = ?", (d,))
        exp_rows = cursor.fetchall()
        e = sum(amt for _, amt in exp_rows)
        
        profit = r - e
        total_rev += r
        total_exp += e
        
        exp_details = ""
        if exp_rows:
            details_str = ", ".join([f"{desc}: {amt:,.0f}₽" for desc, amt in exp_rows])
            exp_details = f"\n   └ 💸 *Расходы:* {details_str}"
            
        report += f"• **{d[8:]}.{d[5:7]}**: Выручка (Эвотор): {r:,.0f} ₽ | Прибыль: {profit:+,.0f} ₽{exp_details}\n\n"
        
    conn.close()
    
    report += "----------------------------------\n"
    report += f"💰 **ИТОГО ЗА МЕСЯЦ:**\n"
    report += f"💵 Общая выручка: **{total_rev:,.2f} руб.**\n"
    report += f"💸 Всего расходов: **{total_exp:,.2f} руб.**\n"
    report += f"📈 **Чистая прибыль: {(total_rev - total_exp):,.2f} руб.**"
    
    await message.answer(report, reply_markup=get_main_keyboard(message.from_user.id), parse_mode="Markdown")

# --- ✏️ РЕДАКТИРОВАНИЕ ДНЯ ---
@dp.message(F.text.contains("Редактировать день"))
async def edit_day_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(BotStates.waiting_for_edit_date)
    await message.answer("✏️ **Введите дату, которую нужно изменить:**\n(Например: `2026-07-27` или напишите `сегодня`)", parse_mode="Markdown")

@dp.message(BotStates.waiting_for_edit_date)
async def process_edit_date(message: types.Message, state: FSMContext):
    target_date = datetime.now().strftime("%Y-%m-%d") if "сегодня" in message.text.lower() else message.text.strip()
    await state.update_data(target_date=target_date)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 Изменить выручку", callback_data="edit_rev")],
        [InlineKeyboardButton(text="🗑 Сбросить расходы за день", callback_data="edit_exp_clear")]
    ])
    await message.answer(f"Дата: **{target_date}**. Что вы хотите изменить?", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "edit_rev")
async def edit_rev_prompt(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotStates.setting_new_revenue)
    await callback.message.answer("💵 Введите **новую сумму выручки** для этой даты:")
    await callback.answer()

@dp.message(BotStates.setting_new_revenue)
async def process_new_revenue(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").strip())
        data = await state.get_data()
        target_date = data['target_date']
        
        conn = sqlite3.connect("cafe_management.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM revenue WHERE created_at = ?", (target_date,))
        cursor.execute("INSERT INTO revenue (amount, created_at) VALUES (?, ?)", (amount, target_date))
        conn.commit()
        conn.close()
        
        await state.clear()
        await message.answer(f"✅ Выручка за **{target_date}** успешно изменена на **{amount:,.2f} руб.**!", reply_markup=get_main_keyboard(message.from_user.id))
    except ValueError:
        await message.answer("⚠️ Пожалуйста, введите корректное число.")

@dp.callback_query(F.data == "edit_exp_clear")
async def clear_exp_process(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    target_date = data['target_date']
    
    conn = sqlite3.connect("cafe_management.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM expenses WHERE created_at = ?", (target_date,))
    conn.commit()
    conn.close()
    
    await state.clear()
    await callback.message.answer(f"🗑 Все расходы за **{target_date}** успешно очищены!", reply_markup=get_main_keyboard(callback.from_user.id))
    await callback.answer()

# --- 📆 ОТЧЕТ ЗА ДЕНЬ И ВВОД РАСХОДОВ ---
@dp.message(F.text.contains("Отчет за день"))
async def day_report_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(BotStates.waiting_for_day_report)
    await message.answer("📆 **Введите дату для отчета:**\n(Например: `2026-07-27` или напишите `сегодня`)", parse_mode="Markdown")

@dp.message(BotStates.waiting_for_day_report)
async def process_day_report(message: types.Message, state: FSMContext):
    target_date = datetime.now().strftime("%Y-%m-%d") if "сегодня" in message.text.lower() else message.text.strip()
    
    conn = sqlite3.connect("cafe_management.db")
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(amount) FROM revenue WHERE created_at = ?", (target_date,))
    rev = cursor.fetchone()[0] or 0.0
    
    cursor.execute("SELECT description, amount FROM expenses WHERE created_at = ?", (target_date,))
    exp_list = cursor.fetchall()
    exp_total = sum(amt for _, amt in exp_list)
    conn.close()
    
    report = f"📆 **ФИНАНСЫ ЗА {target_date}:**\n\n"
    report += f"💵 **Выручка (Эвотор):** {rev:,.2f} руб.\n"
    report += f"💸 **Расходы:** {exp_total:,.2f} руб.\n"
    report += f"📈 **Прибыль:** {(rev - exp_total):,.2f} руб.\n\n"
    
    if exp_list:
        report += "📝 **Список расходов за день:**\n"
        for desc, amt in exp_list:
            report += f"• {desc}: {amt:,.2f} руб.\n"
            
    await state.clear()
    await message.answer(report, reply_markup=get_main_keyboard(message.from_user.id), parse_mode="Markdown")

@dp.message(F.text.contains("Добавить расход"))
async def add_expense_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(BotStates.adding_expense)
    await message.answer("💸 **Введите расход и сумму:**\n(Например: `Закупка молока 450`)", parse_mode="Markdown")

@dp.message(BotStates.adding_expense)
async def process_add_expense(message: types.Message, state: FSMContext):
    nums = re.findall(r'\d+', message.text)
    if not nums:
        await message.answer("⚠️ Не удалось разобрать сумму. Напишите: `Описание Сумма`")
        return
    
    amount = float(nums[-1])
    desc = re.sub(r'\d+', '', message.text).strip()
    
    conn = sqlite3.connect("cafe_management.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO expenses (description, amount) VALUES (?, ?)", (desc, amount))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(f"✅ Расход **{desc}** ({amount} руб.) сохранен!", reply_markup=get_main_keyboard(message.from_user.id), parse_mode="Markdown")

@dp.message(F.text.contains("Внести выручку вручную"))
async def add_revenue_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(BotStates.adding_revenue)
    await message.answer("💵 **Введите сумму кассовой выручки за сегодня:**", parse_mode="Markdown")

@dp.message(BotStates.adding_revenue)
async def process_add_revenue(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").strip())
        conn = sqlite3.connect("cafe_management.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO revenue (amount, created_at) VALUES (?, CURRENT_DATE)", (amount,))
        conn.commit()
        conn.close()
        
        await state.clear()
        await message.answer(f"✅ Выручка **{amount} руб.** за сегодня внесена!", reply_markup=get_main_keyboard(message.from_user.id))
    except ValueError:
        await message.answer("⚠️ Введите число (сумму выручки).")

# === ЗАПУСК ===
async def main():
    init_db()
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
