import os
import sqlite3
import logging
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# =========================
# تنظیمات ربات
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN", "توکن_ربات_را_اینجا_بگذار")

ADMIN_ID = 7748250995
SUPPORT_ID = 7748250995

DOLLAR_PRICE = 225000

TRX_ADDRESS = "TUuNDqfEBSWUjZhwtEqi7NAzp4AuDTeGbj"

DB_NAME = "utopia_ani.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================
# دیتابیس
# =========================

def db():
    return sqlite3.connect(DB_NAME)


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            referrer_id INTEGER,
            referral_count INTEGER DEFAULT 0,
            referral_reward INTEGER DEFAULT 0,
            wallet_balance REAL DEFAULT 0,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            order_type TEXT,
            amount REAL,
            amount_toman INTEGER,
            status TEXT,
            payment_info TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            created_at TEXT
        )
    """)

    con.commit()
    con.close()


def add_user(user, referrer_id=None):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user.id,),
    )

    exists = cur.fetchone()

    if not exists:
        cur.execute("""
            INSERT INTO users (
                user_id,
                username,
                first_name,
                referrer_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            referrer_id,
            datetime.now().isoformat(),
        ))

        if referrer_id and referrer_id != user.id:
            cur.execute("""
                UPDATE users
                SET referral_count = referral_count + 1
                WHERE user_id = ?
            """, (referrer_id,))

            cur.execute("""
                SELECT referral_count, referral_reward
                FROM users
                WHERE user_id = ?
            """, (referrer_id,))

            result = cur.fetchone()

            if result:
                referral_count, referral_reward = result

                # هر ۱۰ دعوت موفق، یک دلار
                possible_reward = referral_count // 10

                if possible_reward > referral_reward:
                    new_reward = possible_reward - referral_reward

                    cur.execute("""
                        UPDATE users
                        SET referral_reward = ?,
                            wallet_balance = wallet_balance + ?
                        WHERE user_id = ?
                    """, (
                        possible_reward,
                        new_reward,
                        referrer_id,
                    ))

    con.commit()
    con.close()


def get_user(user_id):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,),
    )

    result = cur.fetchone()
    con.close()

    return result


def create_order(
    user_id,
    order_type,
    amount,
    amount_toman,
    payment_info="",
):
    con = db()
    cur = con.cursor()

    cur.execute("""
        INSERT INTO orders (
            user_id,
            order_type,
            amount,
            amount_toman,
            status,
            payment_info,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        order_type,
        amount,
        amount_toman,
        "pending",
        payment_info,
        datetime.now().isoformat(),
    ))

    order_id = cur.lastrowid

    con.commit()
    con.close()

    return order_id


# =========================
# ابزارها
# =========================

async def notify_admin(context, text):
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=text,
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.error("Admin notification error: %s", e)


def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🛒 خرید ووچر",
                callback_data="buy",
            ),
            InlineKeyboardButton(
                "💸 فروش ووچر",
                callback_data="sell",
            ),
        ],
        [
            InlineKeyboardButton(
                "👥 دعوت دوستان",
                callback_data="referral",
            ),
            InlineKeyboardButton(
                "💰 کیف پول",
                callback_data="wallet",
            ),
        ],
        [
            InlineKeyboardButton(
                "📦 سفارش‌های من",
                callback_data="my_orders",
            ),
            InlineKeyboardButton(
                "🆘 پشتیبانی",
                callback_data="support",
            ),
        ],
    ])


# =========================
# شروع
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    referrer_id = None

    if context.args:
        try:
            referrer_id = int(context.args[0])
        except ValueError:
            referrer_id = None

    add_user(user, referrer_id)

    text = (
        "🌐 <b>به Utopia Ani خوش آمدید</b>\n\n"
        "خرید و فروش ووچر یوتوپیا با پشتیبانی دستی.\n\n"
        f"💵 قیمت هر دلار: <b>{DOLLAR_PRICE:,} تومان</b>\n"
        "🔒 پرداخت‌ها پس از بررسی ادمین تأیید می‌شوند."
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


# =========================
# منوی اصلی
# =========================

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    if data == "buy":
        context.user_data["state"] = "buy_amount"

        await query.edit_message_text(
            "🛒 <b>خرید ووچر</b>\n\n"
            "مقدار دلار موردنظر را به عدد وارد کن.\n"
            "مثال: <code>5</code>",
            parse_mode=ParseMode.HTML,
        )

    elif data == "sell":
        context.user_data["state"] = "sell_code"

        await query.edit_message_text(
            "💸 <b>فروش ووچر</b>\n\n"
            "کد ووچر خود را ارسال کن.",
            parse_mode=ParseMode.HTML,
        )

    elif data == "referral":
        bot_username = (await context.bot.get_me()).username

        referral_link = (
            f"https://t.me/{bot_username}?start={user_id}"
        )

        user = get_user(user_id)

        referral_count = user[4] if user else 0
        balance = user[6] if user else 0

        await query.edit_message_text(
            "👥 <b>سیستم دعوت دوستان</b>\n\n"
            "به ازای هر ۱۰ عضو واجد شرایط، ۱ دلار پاداش می‌گیری.\n\n"
            f"👤 تعداد دعوت‌ها: <b>{referral_count}</b>\n"
            f"💰 موجودی پاداش: <b>{balance}</b> دلار\n\n"
            "🔗 لینک دعوت شما:\n"
            f"<code>{referral_link}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="back",
                    )
                ]
            ]),
        )

    elif data == "wallet":
        user = get_user(user_id)

        balance = user[6] if user else 0

        await query.edit_message_text(
            "💰 <b>کیف پول</b>\n\n"
            f"موجودی شما: <b>{balance}</b> دلار\n\n"
            "این کیف پول فقط برای پاداش دعوت استفاده می‌شود.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="back",
                    )
                ]
            ]),
        )

    elif data == "support":
        context.user_data["state"] = "support"

        await query.edit_message_text(
            "🆘 پیام خود را برای پشتیبانی ارسال کن.",
            parse_mode=ParseMode.HTML,
        )

    elif data == "my_orders":
        con = db()
        cur = con.cursor()

        cur.execute("""
            SELECT id, order_type, amount, status, created_at
            FROM orders
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 10
        """, (user_id,))

        orders = cur.fetchall()
        con.close()

        if not orders:
            text = "📦 هنوز سفارشی ثبت نکرده‌ای."
        else:
            text = "📦 <b>سفارش‌های اخیر شما</b>\n\n"

            for order in orders:
                oid, otype, amount, status, created_at = order

                text += (
                    f"#{oid} | {otype} | {amount}\n"
                    f"وضعیت: {status}\n\n"
                )

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="back",
                    )
                ]
            ]),
        )

    elif data == "back":
        await query.edit_message_text(
            "🌐 <b>منوی اصلی Utopia Ani</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(),
        )


# =========================
# دریافت پیام‌های متنی
# =========================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    add_user(user)

    state = context.user_data.get("state")

    if state == "buy_amount":
        try:
            amount = float(text)

            if amount <= 0:
                raise ValueError

        except ValueError:
            await update.message.reply_text(
                "❌ مقدار واردشده صحیح نیست. مثال: 5"
            )
            return

        toman = int(amount * DOLLAR_PRICE)

        order_id = create_order(
            user_id=user.id,
            order_type="buy",
            amount=amount,
            amount_toman=toman,
        )

        context.user_data["state"] = f"buy_payment_{order_id}"

        await update.message.reply_text(
            "🛒 <b>جزئیات خرید</b>\n\n"
            f"💵 مقدار: <b>{amount} دلار</b>\n"
            f"💰 مبلغ: <b>{toman:,} تومان</b>\n\n"
            "برای پرداخت TRX روی شبکه TRC20، مبلغ معادل را به آدرس زیر ارسال کن:\n\n"
            f"<code>{TRX_ADDRESS}</code>\n\n"
            "بعد از پرداخت، هش تراکنش یا تصویر رسید را ارسال کن.",
            parse_mode=ParseMode.HTML,
        )

        await notify_admin(
            context,
            "🛒 <b>سفارش خرید جدید</b>\n\n"
            f"Order ID: {order_id}\n"
            f"User ID: {user.id}\n"
            f"Username: @{user.username or 'ندارد'}\n"
            f"Amount: {amount} USD\n"
            f"Price: {toman:,} تومان",
        )

    elif state and state.startswith("buy_payment_"):
        order_id = state.split("_")[-1]

        con = db()
        cur = con.cursor()

        cur.execute("""
            UPDATE orders
            SET payment_info = ?
            WHERE id = ?
        """, (text, order_id))

        con.commit()
        con.close()

        context.user_data["state"] = None

        await update.message.reply_text(
            "✅ اطلاعات پرداخت ثبت شد.\n"
            "پس از بررسی ادمین، ووچر برای شما ارسال می‌شود."
        )

        await notify_admin(
            context,
            "💳 <b>اطلاعات پرداخت خرید</b>\n\n"
            f"Order ID: {order_id}\n"
            f"User ID: {user.id}\n"
            f"Payment info:\n{text}",
        )

    elif state == "sell_code":
        context.user_data["voucher_code"] = text
        context.user_data["state"] = "sell_iban"

        await update.message.reply_text(
            "✅ کد ووچر دریافت شد.\n\n"
            "لطفاً شماره شبا خود را بدون فاصله ارسال کن."
        )

    elif state == "sell_iban":
        voucher_code = context.user_data.get("voucher_code", "")
        iban = text

        order_id = create_order(
            user_id=user.id,
            order_type="sell",
            amount=0,
            amount_toman=0,
            payment_info=(
                f"Voucher: {voucher_code}\n"
                f"IBAN: {iban}"
            ),
        )

        context.user_data["state"] = None
        context.user_data["voucher_code"] = None

        await update.message.reply_text(
            "✅ درخواست فروش شما ثبت شد.\n"
            "پس از بررسی ووچر، مبلغ به شماره شبای شما واریز می‌شود."
        )

        await notify_admin(
            context,
            "💸 <b>درخواست فروش ووچر</b>\n\n"
            f"Order ID: {order_id}\n"
            f"User ID: {user.id}\n"
            f"Username: @{user.username or 'ندارد'}\n\n"
            f"Voucher:\n{voucher_code}\n\n"
            f"IBAN:\n{iban}",
        )

    elif state == "support":
        context.user_data["state"] = None

        con = db()
        cur = con.cursor()

        cur.execute("""
            INSERT INTO messages (
                user_id,
                message,
                created_at
            )
