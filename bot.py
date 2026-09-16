import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


# =========================
# تنظیمات
# =========================
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "utopia_ani.db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

dp = Dispatcher()


# =========================
# ابزارهای عمومی
# =========================
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS vouchers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            amount INTEGER NOT NULL,
            price INTEGER NOT NULL,
            status TEXT DEFAULT 'available',
            seller_id INTEGER,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            voucher_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            price INTEGER NOT NULL,
            status TEXT DEFAULT 'pending_payment',
            receipt_file_id TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sell_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )

    con.execute(
        """
        INSERT OR IGNORE INTO settings(key, value)
        VALUES('payment_text', ?)
        """,
        ("پرداخت را طبق دستور ادمین انجام دهید و رسید را ارسال کنید.",),
    )
    con.commit()
    con.close()


def upsert_user(user):
    con = db()
    con.execute(
        """
        INSERT INTO users(id, username, first_name, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name
        """,
        (user.id, user.username, user.first_name, now_iso()),
    )
    con.commit()
    con.close()


def payment_text() -> str:
    con = db()
    row = con.execute(
        "SELECT value FROM settings WHERE key='payment_text'"
    ).fetchone()
    con.close()
    return row["value"] if row else "پرداخت را طبق دستور ادمین انجام دهید."


def is_admin(message: Message) -> bool:
    return bool(ADMIN_ID and message.from_user and message.from_user.id == ADMIN_ID)


def parse_number(value: str) -> int:
    value = (
        value.replace(",", "")
        .replace("٬", "")
        .replace(" ", "")
        .strip()
    )
    if not value.isdigit():
        raise ValueError
    number = int(value)
    if number <= 0:
        raise ValueError
    return number


# =========================
# کیبوردها
# =========================
def menu():
    kb = ReplyKeyboardBuilder()
    kb.button(text="🛒 خرید ووچر یوتوپیا")
    kb.button(text="💰 فروش ووچر یوتوپیا")
    kb.button(text="👤 حساب من")
    kb.button(text="📞 پشتیبانی")
    kb.button(text="❌ لغو عملیات")
    kb.adjust(1, 1, 2, 1)
    return kb.as_markup(resize_keyboard=True)


def amounts_keyboard():
    con = db()
    rows = con.execute(
        """
        SELECT amount, MIN(price) AS price
        FROM vouchers
        WHERE status='available'
        GROUP BY amount
        ORDER BY amount
        """
    ).fetchall()
    con.close()

    kb = InlineKeyboardBuilder()
    for row in rows:
        kb.button(
            text=f"ووچر {row['amount']:,} — {row['price']:,}",
            callback_data=f"buy_amount:{row['amount']}",
        )
    kb.adjust(1)
    return kb.as_markup()


# =========================
# حالت‌ها
# =========================
class SellStates(StatesGroup):
    amount = State()
    code = State()


class BuyStates(StatesGroup):
    waiting_receipt = State()


# =========================
# شروع و لغو
# =========================
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    upsert_user(message.from_user)
    await message.answer(
        "✨ <b>یوتوپیا آنی</b>\n\n"
        "خرید و فروش <b>ووچر یوتوپیا</b> با تحویل سریع.\n"
        "از منوی زیر انتخاب کنید:",
        reply_markup=menu(),
    )


@dp.message(F.text == "❌ لغو عملیات")
@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ عملیات لغو شد.", reply_markup=menu())


# =========================
# خرید
# =========================
@dp.message(F.text == "🛒 خرید ووچر یوتوپیا")
async def buy(message: Message, state: FSMContext):
    await state.clear()
    upsert_user(message.from_user)

    keyboard = amounts_keyboard()
    if not keyboard.inline_keyboard:
        await message.answer("❌ فعلاً ووچری برای فروش موجود نیست.", reply_markup=menu())
        return

    await message.answer(
        "مبلغ ووچر را انتخاب کنید:",
        reply_markup=keyboard,
    )


@dp.callback_query(F.data.startswith("buy_amount:"))
async def choose_buy(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    try:
        amount = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("مبلغ نامعتبر است.", show_alert=True)
        return

    con = db()
    row = con.execute(
        """
        SELECT *
        FROM vouchers
        WHERE amount=? AND status='available'
        ORDER BY price ASC, id ASC
        LIMIT 1
        """,
        (amount,),
    ).fetchone()

    if not row:
        con.close()
        await callback.answer("این مبلغ فعلاً موجود نیست.", show_alert=True)
        return

    cur = con.execute(
        """
        INSERT INTO orders(
            user_id, voucher_id, amount, price, status, created_at
        )
        VALUES (?, ?, ?, ?, 'pending_payment', ?)
        """,
        (
            callback.from_user.id,
            row["id"],
            row["amount"],
            row["price"],
            now_iso(),
        ),
    )
    order_id = cur.lastrowid
    con.commit()
    con.close()

    await state.update_data(order_id=order_id)
    await state.set_state(BuyStates.waiting_receipt)

    await callback.message.answer(
        f"🧾 سفارش <b>#{order_id}</b>\n"
        f"مبلغ ووچر: <b>{row['amount']:,}</b>\n"
        f"قیمت: <b>{row['price']:,}</b>\n\n"
        "پرداخت را طبق دستور زیر انجام دهید و سپس رسید را همینجا بفرستید:\n\n"
        f"{payment_text()}\n\n"
        "برای لغو، روی «❌ لغو عملیات» بزنید.",
        reply_markup=menu(),
    )
    await callback.answer()


@dp.message(BuyStates.waiting_receipt)
async def receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")

    if not order_id:
        await state.clear()
        await message.answer("سفارش پیدا نشد. دوباره از منو شروع کنید.", reply_markup=menu())
        return

    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document:
        file_id = message.document.file_id
    elif message.text:
        file_id = message.text[:1000]

    if not file_id:
        await message.answer("لطفاً عکس رسید، فایل رسید یا متن رسید را ارسال کنید.")
        return

    con = db()
    con.execute(
        """
        UPDATE orders
        SET status='receipt_sent', receipt_file_id=?
        WHERE id=? AND user_id=?
        """,
        (file_id, order_id, message.from_user.id),
    )
    con.commit()
    con.close()

    await state.clear()
    await message.answer(
        "✅ رسید دریافت شد. پس از تأیید ادمین، ووچر برای شما ارسال می‌شود.",
        reply_markup=menu(),
    )

    if ADMIN_ID:
        await message.bot.send_message(
            ADMIN_ID,
            f"🔔 رسید سفارش #{order_id}\n"
            f"کاربر: {message.from_user.id} "
            f"(@{message.from_user.username or '-'})\n"
            "برای بررسی: /orders",
        )


# =========================
# فروش
# =========================
@dp.message(F.text == "💰 فروش ووچر یوتوپیا")
async def sell_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(SellStates.amount)
    await message.answer("مبلغ ووچر را به عدد وارد کنید (مثلاً 100000):")


@dp.message(SellStates.amount)
async def sell_amount(message: Message, state: FSMContext):
    try:
        amount = parse_number(message.text or "")
    except ValueError:
        await message.answer("لطفاً مبلغ را فقط به صورت عددی وارد کنید.")
        return

    await state.update_data(amount=amount)
    await state.set_state(SellStates.code)
    await message.answer("حالا کد ووچر را ارسال کنید:")


@dp.message(SellStates.code)
async def sell_code(message: Message, state: FSMContext):
    data = await state.get_data()
    code = (message.text or "").strip()

    if not code:
        await message.answer("کد ووچر نمی‌تواند خالی باشد.")
        return

    con = db()
    try:
        cur = con.execute(
            """
            INSERT INTO sell_requests(
                user_id, code, amount, status, created_at
            )
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (message.from_user.id, code, data["amount"], now_iso()),
        )
        request_id = cur.lastrowid
        con.commit()
    except sqlite3.IntegrityError:
        con.close()
        await message.answer("این کد قبلاً ثبت شده است.")
        return

    con.close()
    await state.clear()

    await message.answer(
        f"✅ درخواست فروش #{request_id} ثبت شد.\n"
        "پس از بررسی ووچر، نتیجه و مبلغ تسویه اعلام می‌شود.",
        reply_markup=menu(),
    )

    if ADMIN_ID:
        await message.bot.send_message(
            ADMIN_ID,
            f"🔔 درخواست فروش #{request_id}\n"
            f"کاربر: {message.from_user.id}\n"
            f"مبلغ: {data['amount']:,}\n"
            f"کد: <code>{code}</code>\n"
            "برای بررسی از /sell_requests استفاده کنید.",
        )


# =========================
# حساب و پشتیبانی
# =========================
@dp.message(F.text == "👤 حساب من")
async def account(message: Message, state: FSMContext):
    await state.clear()
    upsert_user(message.from_user)

    con = db()
    user = con.execute(
        "SELECT * FROM users WHERE id=?",
        (message.from_user.id,),
    ).fetchone()
    buys = con.execute(
        """
        SELECT COUNT(*) AS n
        FROM orders
        WHERE user_id=? AND status='completed'
        """,
        (message.from_user.id,),
    ).fetchone()["n"]
    sells = con.execute(
        """
        SELECT COUNT(*) AS n
        FROM sell_requests
        WHERE user_id=? AND status='approved'
        """,
        (message.from_user.id,),
    ).fetchone()["n"]
    con.close()

    await message.answer(
        f"👤 <b>حساب شما</b>\n\n"
        f"آیدی: <code>{message.from_user.id}</code>\n"
        f"موجودی: {user['balance']:,}\n"
        f"خریدهای تکمیل‌شده: {buys}\n"
        f"فروش‌های تأییدشده: {sells}",
        reply_markup=menu(),
    )


@dp.message(F.text == "📞 پشتیبانی")
async def support(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "📞 پیام خود را همینجا ارسال کنید.\n"
        "در صورت آنلاین بودن ادمین، پاسخ داده می‌شود.",
        reply_markup=menu(),
    )


# =========================
# دستورات ادمین
# =========================
@dp.message(Command("orders"))
async def orders(message: Message):
    if not is_admin(message):
        return

    con = db()
    rows = con.execute(
        """
        SELECT o.id, o.user_id, o.amount, o.price, o.status, v.code
        FROM orders o
        JOIN vouchers v ON v.id=o.voucher_id
        WHERE o.status!='completed'
        ORDER BY o.id DESC
        LIMIT 30
        """
    ).fetchall()
    con.close()

    if not rows:
        await message.answer("سفارشی برای بررسی نیست.")
        return

    text = "📋 <b>سفارش‌های در انتظار</b>\n\n"
    for row in rows:
        text += (
            f"#{row['id']} | user {row['user_id']} | "
            f"{row['amount']:,} | {row['price']:,} | {row['status']}\n"
        )

    await message.answer(
        text
        + "\nبرای تأیید: /approve_order ID"
        + "\nبرای رد: /reject_order ID"
    )


@dp.message(Command("approve_order"))
async def approve_order(message: Message):
    if not is_admin(message):
        return

    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("مثال: /approve_order 12")
        return

    order_id = int(parts[1])
    con = db()
    row = con.execute(
        """
        SELECT o.*, v.code, v.id AS voucher_id
        FROM orders o
        JOIN vouchers v ON v.id=o.voucher_id
        WHERE o.id=?
        """,
        (order_id,),
    ).fetchone()

    if not row:
        con.close()
        await message.answer("سفارش پیدا نشد.")
        return

    if row["status"] == "completed":
        con.close()
        await message.answer("این سفارش قبلاً تأیید شده است.")
        return

    con.execute(
        "UPDATE orders SET status='completed' WHERE id=?",
        (order_id,),
    )
    con.execute(
        "UPDATE vouchers SET status='sold' WHERE id=?",
        (row["voucher_id"],),
    )
    con.commit()
    con.close()

    await message.bot.send_message(
        row["user_id"],
        f"🎉 پرداخت تأیید شد!\n\n"
        f"ووچر یوتوپیا شما:\n<code>{row['code']}</code>\n\n"
        f"مبلغ: {row['amount']:,}",
    )
    await message.answer("✅ سفارش تأیید و ووچر ارسال شد.")


@dp.message(Command("reject_order"))
async def reject_order(message: Message):
    if not is_admin(message):
        return

    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("مثال: /reject_order 12")
        return

    order_id = int(parts[1])
    con = db()
    row = con.execute(
        "SELECT user_id, status FROM orders WHERE id=?",
        (order_id,),
    ).fetchone()

    if not row:
        con.close()
        await message.answer("سفارش پیدا نشد.")
        return

    con.execute(
        "UPDATE orders SET status='rejected' WHERE id=?",
        (order_id,),
    )
    con.commit()
    con.close()

    await message.bot.send_message(
        row["user_id"],
        "❌ پرداخت سفارش شما تأیید نشد. برای پیگیری با پشتیبانی تماس بگیرید.",
    )
    await message.answer("سفارش رد شد.")


@dp.message(Command("addvoucher"))
async def addvoucher(message: Message):
    if not is_admin(message):
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) != 4:
        await message.answer(
            "فرمت:\n"
            "/addvoucher مبلغ قیمت کد\n\n"
            "مثال:\n"
            "/addvoucher 100000 95000 ABC123"
        )
        return

    try:
        amount = parse_number(parts[1])
        price = parse_number(parts[2])
    except ValueError:
        await message.answer("مبلغ و قیمت باید عددی باشند.")
        return

    code = parts[3].strip()
    if not code:
        await message.answer("کد ووچر خالی است.")
        return

    con = db()
    try:
        con.execute(
            """
            INSERT INTO vouchers(
                code, amount, price, status, created_at
            )
            VALUES (?, ?, ?, 'available', ?)
            """,
            (code, amount, price, now_iso()),
        )
        con.commit()
    except sqlite3.IntegrityError:
        con.close()
        await message.answer("این کد قبلاً ثبت شده است.")
        return

    con.close()
    await message.answer("✅ ووچر به موجودی اضافه شد.")


@dp.message(Command("inventory"))
async def inventory(message: Message):
    if not is_admin(message):
        return

    con = db()
    rows = con.execute(
        """
        SELECT amount, COUNT(*) AS n, MIN(price) AS p
        FROM vouchers
        WHERE status='available'
        GROUP BY amount
        ORDER BY amount
        """
    ).fetchall()
    con.close()

    if not rows:
        await message.answer("موجودی خالی است.")
        return

    await message.answer(
        "\n".join(
            f"{row['amount']:,}: {row['n']} عدد | از {row['p']:,}"
            for row in rows
        )
    )


@dp.message(Command("sell_requests"))
async def sell_requests(message: Message):
    if not is_admin(message):
        return

    con = db()
    rows = con.execute(
        """
        SELECT id, user_id, amount, code, status
        FROM sell_requests
        WHERE status='pending'
        ORDER BY id DESC
        LIMIT 30
        """
    ).fetchall()
    con.close()

    if not rows:
        await message.answer("درخواست فروش در انتظار نیست.")
        return

    text = "📋 <b>درخواست‌های فروش</b>\n\n"
    for row in rows:
        text += (
            f"#{row['id']} | user {row['user_id']} | "
            f"{row['amount']:,} | {row['status']}\n"
            f"کد: <code>{row['code']}</code>\n\n"
        )

    await message.answer(text)


# =========================
# اجرای ربات
# =========================
async def main():
    if not TOKEN:
        raise RuntimeError(
            "متغیر BOT_TOKEN در Railway تنظیم نشده است."
        )

    if not ADMIN_ID:
        logging.warning(
            "ADMIN_ID تنظیم نشده؛ دستورات ادمین کار نمی‌کنند."
        )

    init_db()

    bot = Bot(
        TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
