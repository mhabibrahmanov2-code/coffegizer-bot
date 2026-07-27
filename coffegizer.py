import os
import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web

# === НАСТРОЙКИ ===
BOT_TOKEN = "8888700652:AAHGPgLcdDoaBaRcjBdjLxE1KzBDh_rHUyA"  

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# === ВЕБ-СЕРВЕР ДЛЯ RENDER (Health Check) ===
async def handle_ping(request):
    return web.Response(text="Bot is running!")

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
    conn = sqlite3.connect("cafe.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS packaging (
        name TEXT PRIMARY KEY,
        quantity INTEGER
    )''')
    
    initial_pack = [
        ("Стаканы 250 мл", 500),
        ("Стаканы 350 мл", 500),
        ("Стаканы лимонад 300 мл", 300),
        ("Стаканы лимонад 500 мл", 300),
        ("Крышки 250 мл", 500),
        ("Крышки 350 мл", 500),
        ("Крышки купольные", 600),
        ("Контейнер треугольный", 200),
        ("Уголок бумажный", 300),
        ("Пакет крафт с ручками", 150)
    ]
    cursor.executemany("INSERT OR IGNORE INTO packaging VALUES (?, ?)", initial_pack)
    conn.commit()
    conn.close()

def log_sale(item_name):
    conn = sqlite3.connect("cafe.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sales (item_name) VALUES (?)", (item_name,))
    
    name_low = item_name.lower()
    if "250" in name_low or "стандарт" in name_low:
        cursor.execute("UPDATE packaging SET quantity = quantity - 1 WHERE name = 'Стаканы 250 мл'")
        cursor.execute("UPDATE packaging SET quantity = quantity - 1 WHERE name = 'Крышки 250 мл'")
    elif "350" in name_low:
        cursor.execute("UPDATE packaging SET quantity = quantity - 1 WHERE name = 'Стаканы 350 мл'")
        cursor.execute("UPDATE packaging SET quantity = quantity - 1 WHERE name = 'Крышки 350 мл'")
    elif "чизкейк" in name_low or "торт" in name_low or "пирожное" in name_low:
        cursor.execute("UPDATE packaging SET quantity = quantity - 1 WHERE name = 'Контейнер треугольный'")
    elif "блин" in name_low or "хот-дог" in name_low or "круассан" in name_low or "сэндвич" in name_low:
        cursor.execute("UPDATE packaging SET quantity = quantity - 1 WHERE name = 'Уголок бумажный'")
    elif "лимонад" in name_low or "айс" in name_low or "мохито" in name_low or "300" in name_low or "500" in name_low:
        cursor.execute("UPDATE packaging SET quantity = quantity - 1 WHERE name = 'Стаканы лимонад 300 мл'")
        cursor.execute("UPDATE packaging SET quantity = quantity - 1 WHERE name = 'Крышки купольные'")
        
    conn.commit()
    conn.close()

# === КЛАВИАТУРЫ ===
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="☕ Горячие напитки"), KeyboardButton(text="🥤 Холодные / Лимонады")],
        [KeyboardButton(text="🍰 Чизкейки и Торты"), KeyboardButton(text="🥐 Выпечка, Десерты и Еда")],
        [KeyboardButton(text="📦 Заявка на упаковку"), KeyboardButton(text="📊 Продажи за смену")]
    ],
    resize_keyboard=True
)

hot_drinks_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Капучино 250", callback_data="sell_Капучино 250"), InlineKeyboardButton(text="Капучино 350", callback_data="sell_Капучино 350")],
    [InlineKeyboardButton(text="Латте 250", callback_data="sell_Латте 250"), InlineKeyboardButton(text="Латте 350", callback_data="sell_Латте 350")],
    [InlineKeyboardButton(text="Американо 250", callback_data="sell_Американо 250"), InlineKeyboardButton(text="Американо 350", callback_data="sell_Американо 350")],
    [InlineKeyboardButton(text="Раф 250", callback_data="sell_Раф 250"), InlineKeyboardButton(text="Раф 350", callback_data="sell_Раф 350")],
    [InlineKeyboardButton(text="Флэт Уайт", callback_data="sell_Флэт Уайт"), InlineKeyboardButton(text="Какао 250", callback_data="sell_Какао 250")],
    [InlineKeyboardButton(text="Чай 200", callback_data="sell_Чай 200 мл"), InlineKeyboardButton(text="Чай 300", callback_data="sell_Чай 300 мл")]
])

cheesecakes_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Чизкейк Нью-Йорк", callback_data="sell_Чизкейк Нью-Йорк")],
    [InlineKeyboardButton(text="Чизкейк Сан-Себастьян", callback_data="sell_Чизкейк Сан-Себастьян")],
    [InlineKeyboardButton(text="Чизкейк Дубайский", callback_data="sell_Чизкейк Дубайский шоколад")],
    [InlineKeyboardButton(text="Чизкейк Арахис кранч", callback_data="sell_Чизкейк Арахис кранч")],
    [InlineKeyboardButton(text="Чизкейк Фисташка-Малина", callback_data="sell_Чизкейк Фисташка малина")],
    [InlineKeyboardButton(text="Торт Медовик", callback_data="sell_Медовик ДОМАШНИЙ")],
    [InlineKeyboardButton(text="Торт Наполеон", callback_data="sell_Наполеон домашний")]
])

# === ХЕНДЛЕРЫ ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("☕ Бот учета для Кофейни запущен!\nВыберите категорию для продажи или учета:", reply_markup=main_kb)

@dp.message(F.text == "☕ Горячие напитки")
async def show_hot_drinks(message: types.Message):
    await message.answer("Выберите напиток:", reply_markup=hot_drinks_kb)

@dp.message(F.text == "🍰 Чизкейки и Торты")
async def show_cheesecakes(message: types.Message):
    await message.answer("Выберите чизкейк/торт:", reply_markup=cheesecakes_kb)

@dp.message(F.text == "📊 Продажи за смену")
async def show_stats(message: types.Message):
    conn = sqlite3.connect("cafe.db")
    cursor = conn.cursor()
    cursor.execute("SELECT item_name, COUNT(*) FROM sales WHERE date(timestamp) = date('now') GROUP BY item_name")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        await message.answer("Сегодня еще ничего не было продано.")
        return
        
    report = "📈 **Продано за сегодня:**\n\n"
    for name, count in rows:
        report += f"• {name}: {count} шт.\n"
    await message.answer(report, parse_mode="Markdown")

@dp.message(F.text == "📦 Заявка на упаковку")
async def show_pack_order(message: types.Message):
    conn = sqlite3.connect("cafe.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, quantity FROM packaging")
    rows = cursor.fetchall()
    conn.close()
    
    report = "📦 **Расчет остатков и Заявка на упаковку:**\n\n"
    low_stock = []
    
    for name, qty in rows:
        status = "✅" if qty > 100 else "⚠️ МАЛО!"
        report += f"{status} {name}: остаток ~{qty} шт.\n"
        if qty <= 100:
            low_stock.append(name)
            
    if low_stock:
        report += "\n🚨 **СРОЧНО ЗАКАЗАТЬ:**\n" + "\n".join([f"- {item}" for item in low_stock])
    else:
        report += "\nВся упаковка в достаточном количестве!"
        
    await message.answer(report, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("sell_"))
async def process_sale(callback: types.CallbackQuery):
    item_name = callback.data.split("sell_")[1]
    log_sale(item_name)
    await callback.answer(f"✅ Продано: {item_name}", show_alert=False)
    await callback.message.edit_text(f"Успешно записано: **{item_name}**!\nВыберите следующую позицию или категорию в меню ниже.", parse_mode="Markdown")

# === ЗАПУСК ===
async def main():
    init_db()
    await start_web_server()  # Запускаем фиктивный порт для Render
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
