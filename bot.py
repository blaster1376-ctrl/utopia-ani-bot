import asyncio
import logging
import os
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "utopia_ani.db")

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        balance INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS vouchers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        amount INTEGER NOT NULL,
        price INTEGER NOT NULL,
        status TEXT DEFAULT 'available',
        seller_id INTEGER,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        voucher_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        price INTEGER NOT NULL,
        status TEXT DEFAULT 'pending_payment',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sell_requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        code TEXT NOT NULL,
        amount INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)
    con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('payment_text','پرداخت را طبق دستور ادمین انجام دهید و رسید را ارسال کنید.')")
    con.commit()
    con.close()

def upsert_user(u):
    con = db()
    con.execute("""INSERT INTO users(id,username,first_name,created_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name""",
                (u.id, u.username, u.first_name, datetime.now().isoformat()))
    con.commit(); con.close()

def menu():
    kb = ReplyKeyboardBuilder()
    kb.button(text="🛒 خرید ووچر یوتوپیا")
    kb.button(text="💰 فروش ووچر یوتوپیا")
    kb.button(text="👤 حساب من")
    kb.button(text="📞 پشتیبانی")
    kb.adjust(1,1,2)
    return kb.as_markup(resize_keyboard=True)

def amounts_keyboard():
    con = db()
    rows = con.execute("SELECT amount, MIN(price) price FROM vouchers WHERE status='available' GROUP BY amount ORDER BY amount").fetchall()
    con.close()
    kb = InlineKeyboardBuilder()
    for r in rows:
        kb.button(text=f"ووچر {r['amount']:,} — {r['price']:,}", callback_data=f"buy_amount:{r['amount']}")
    kb.adjust(1)
    return kb.as_markup()

class SellStates(StatesGroup):
    amount = State()
    code = State()

class BuyStates(StatesGroup):
    waiting_receipt = State()

@dp.message(CommandStart())
async def start(message: Message):
    upsert_user(message.from_user)
    await message.answer(
        "✨ <b>یوتوپیا آنی</b>\n\n"
        "خرید و فروش <b>ووچر یوتوپیا</b> با تحویل سریع.\n"
        "از منوی زیر انتخاب کنید:",
        reply_markup=menu()
    )

@dp.message(F.text == "🛒 خرید ووچر یوتوپیا")
async def buy(message: Message):
    upsert_user(message.from_user)
    await message.answer("مبلغ ووچر را انتخاب کنید:", reply_markup=amounts_keyboard())

@dp.callback_query(F.data.startswith("buy_amount:"))
async def choose_buy(callback: CallbackQuery, state: FSMContext):
    amount = int(callback.data.split(":")[1])
    con = db()
    row = con.execute("SELECT * FROM vouchers WHERE amount=? AND status='available' ORDER BY price LIMIT 1", (amount,)).fetchone()
    if not row:
        con.close()
        await callback.answer("این مبلغ فعلاً موجود نیست.", show_alert=True)
        return
    cur = con.execute("""INSERT INTO orders(user_id,voucher_id,amount,price,status,created_at)
                         VALUES(?,?,?,?,?,?)""",
                      (callback.from_user.id,row["id"],row["amount"],row["price"],"pending_payment",datetime.now().isoformat()))
    order_id = cur.lastrowid
    con.commit(); con.close()
    await state.update_data(order_id=order_id)
    await callback.message.answer(
        f"🧾 سفارش <b>#{order_id}</b>\n"
        f"مبلغ ووچر: <b>{row['amount']:,}</b>\n"
        f"قیمت: <b>{row['price']:,}</b>\n\n"
        "برای ادامه، پرداخت را طبق دستور زیر انجام دهید و رسید را همینجا ارسال کنید:\n"
        f"{payment_text()}"
    )
    await state.set_state(BuyStates.waiting_receipt)
    await callback.answer()

def payment_text():
    con=db()
    x=con.execute("SELECT value FROM settings WHERE key='payment_text'").fetchone()
    con.close()
    return x["value"] if x else "پرداخت را طبق دستور ادمین انجام دهید."

@dp.message(BuyStates.waiting_receipt)
async def receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    if not order_id:
        await state.clear(); return
    con=db()
    con.execute("UPDATE orders SET status='receipt_sent' WHERE id=? AND user_id=?", (order_id,message.from_user.id))
    con.commit(); con.close()
    await state.clear()
    await message.answer("✅ رسید دریافت شد. پس از تأیید ادمین، ووچر برای شما ارسال می‌شود.", reply_markup=menu())
    if ADMIN_ID:
        await message.bot.send_message(
            ADMIN_ID,
            f"🔔 رسید سفارش #{order_id}\nکاربر: {message.from_user.id} (@{message.from_user.username or '-'})\n"
            "برای بررسی از پنل دستوری استفاده کنید: /orders"
        )

@dp.message(F.text == "💰 فروش ووچر یوتوپیا")
async def sell_start(message: Message, state: FSMContext):
    await state.set_state(SellStates.amount)
    await message.answer("مبلغ ووچر را به عدد وارد کنید (مثلاً 100000):")

@dp.message(SellStates.amount)
async def sell_amount(message: Message, state: FSMContext):
    try:
        amount=int(message.text.replace(",","").replace("٬",""))
        if amount <= 0: raise ValueError
    except:
        await message.answer("لطفاً مبلغ را به صورت عددی وارد کنید.")
        return
    await state.update_data(amount=amount)
    await state.set_state(SellStates.code)
    await message.answer("حالا کد ووچر را ارسال کنید:")

@dp.message(SellStates.code)
async def sell_code(message: Message, state: FSMContext):
    data=await state.get_data()
    code=message.text.strip()
    con=db()
    try:
        cur=con.execute("""INSERT INTO sell_requests(user_id,code,amount,status,created_at)
                           VALUES(?,?,?,?,?)""",
                        (message.from_user.id,code,data["amount"],"pending",datetime.now().isoformat()))
        rid=cur.lastrowid
        con.commit()
    except sqlite3.IntegrityError:
        con.close()
        await message.answer("این کد قبلاً ثبت شده یا نامعتبر است.")
        return
    con.close()
    await state.clear()
    await message.answer(f"✅ درخواست فروش #{rid} ثبت شد.\nپس از بررسی ووچر، نتیجه و مبلغ تسویه اعلام می‌شود.", reply_markup=menu())
    if ADMIN_ID:
        await message.bot.send_message(ADMIN_ID, f"🔔 درخواست فروش #{rid}\nکاربر: {message.from_user.id}\nمبلغ: {data['amount']:,}\nکد: <code>{code}</code>\n/orders برای بررسی")

@dp.message(F.text == "👤 حساب من")
async def account(message: Message):
    con=db()
    u=con.execute("SELECT * FROM users WHERE id=?", (message.from_user.id,)).fetchone()
    buys=con.execute("SELECT COUNT(*) n FROM orders WHERE user_id=? AND status='completed'", (message.from_user.id,)).fetchone()["n"]
    sells=con.execute("SELECT COUNT(*) n FROM sell_requests WHERE user_id=? AND status='approved'", (message.from_user.id,)).fetchone()["n"]
    con.close()
    await message.answer(f"👤 <b>حساب شما</b>\n\nآیدی: <code>{message.from_user.id}</code>\nخریدهای تکمیل‌شده: {buys}\nفروش‌های تأییدشده: {sells}")

@dp.message(F.text == "📞 پشتیبانی")
async def support(message: Message):
    await message.answer("📞 برای پشتیبانی، پیام خود را همینجا ارسال کنید. ادمین پاسخ می‌دهد.")

@dp.message(Command("orders"))
async def orders(message: Message):
    if message.from_user.id != ADMIN_ID: return
    con=db()
    rows=con.execute("""SELECT o.id,o.user_id,o.amount,o.price,o.status,v.code
                        FROM orders o JOIN vouchers v ON v.id=o.voucher_id
                        WHERE o.status!='completed' ORDER BY o.id DESC LIMIT 20""").fetchall()
    con.close()
    if not rows:
        await message.answer("سفارشی برای بررسی نیست."); return
    text="📋 <b>سفارش‌های در انتظار</b>\n\n"
    for r in rows:
        text += f"#{r['id']} | user {r['user_id']} | {r['amount']:,} | {r['price']:,} | {r['status']}\n"
    await message.answer(text + "\nبرای تأیید: /approve_order ID\nبرای رد: /reject_order ID")

@dp.message(Command("approve_order"))
async def approve_order(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts=message.text.split()
    if len(parts)!=2: await message.answer("مثال: /approve_order 12"); return
    oid=int(parts[1])
    con=db()
    row=con.execute("""SELECT o.*,v.code,v.id vid FROM orders o JOIN vouchers v ON v.id=o.voucher_id WHERE o.id=?""",(oid,)).fetchone()
    if not row: con.close(); await message.answer("سفارش پیدا نشد."); return
    con.execute("UPDATE orders SET status='completed' WHERE id=?", (oid,))
    con.execute("UPDATE vouchers SET status='sold' WHERE id=?", (row["vid"],))
    con.commit(); con.close()
    await message.bot.send_message(row["user_id"], f"🎉 پرداخت تأیید شد!\n\nووچر یوتوپیا شما:\n<code>{row['code']}</code>\n\nمبلغ: {row['amount']:,}")
    await message.answer("✅ سفارش تأیید و ووچر ارسال شد.")

@dp.message(Command("reject_order"))
async def reject_order(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts=message.text.split()
    if len(parts)!=2: await message.answer("مثال: /reject_order 12"); return
    oid=int(parts[1])
    con=db()
    row=con.execute("SELECT voucher_id,user_id FROM orders WHERE id=?",(oid,)).fetchone()
    if not row: con.close(); await message.answer("سفارش پیدا نشد."); return
    con.execute("UPDATE orders SET status='rejected' WHERE id=?", (oid,))
    con.commit(); con.close()
    await message.bot.send_message(row["user_id"], "❌ پرداخت سفارش شما تأیید نشد. برای پیگیری با پشتیبانی تماس بگیرید.")
    await message.answer("سفارش رد شد.")

@dp.message(Command("addvoucher"))
async def addvoucher(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts=message.text.split(maxsplit=3)
    if len(parts)!=4:
        await message.answer("فرمت: /addvoucher مبلغ قیمت کد\nمثال: /addvoucher 100000 95000 ABC123")
        return
    amount,price,code=int(parts[1]),int(parts[2]),parts[3].strip()
    con=db()
    try:
        con.execute("""INSERT INTO vouchers(code,amount,price,status,created_at)
                       VALUES(?,?,?,'available',?)""",(code,amount,price,datetime.now().isoformat()))
        con.commit()
    except sqlite3.IntegrityError:
        con.close(); await message.answer("این کد قبلاً ثبت شده."); return
    con.close()
    await message.answer("✅ ووچر به موجودی اضافه شد.")

@dp.message(Command("inventory"))
async def inventory(message: Message):
    if message.from_user.id != ADMIN_ID: return
    con=db()
    rows=con.execute("SELECT amount,COUNT(*) n,MIN(price) p FROM vouchers WHERE status='available' GROUP BY amount ORDER BY amount").fetchall()
    con.close()
    if not rows: await message.answer("موجودی خالی است."); return
    await message.answer("\n".join(f"{r['amount']:,}: {r['n']} عدد | از {r['p']:,}" for r in rows))

async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN را در فایل .env تنظیم کنید.")
    init_db()
    bot=Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)

if __name__=="__main__":
    asyncio.run(main())
