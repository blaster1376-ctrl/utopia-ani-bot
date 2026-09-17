
import os
import sqlite3
import logging
import asyncio
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ==================================================
# تنظیمات
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

ADMIN_ID = 7748250995
SUPPORT_ID = 7748250995

PRICE_USD = 225000
REFERRAL_COUNT = 10
REFERRAL_REWARD_USD = 1

TRX_ADDRESS = "TUuNDqfEBSWUjZhwtEqi7NAzp4AuDTeGbj"

DB_FILE = "utopia.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# ==================================================
# دیتابیس
# ==================================================

def db():
    return sqlite3.connect(DB_FILE)


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        referrals INTEGER DEFAULT 0,
        wallet INTEGER DEFAULT 0,
        referred_by INTEGER,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        order_type TEXT,
        amount TEXT,
        payment_method TEXT,
        payment_info TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS support (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        created_at TEXT
    )
    """)

    con.commit()
    con.close()


def add_user(user, referred_by=None):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT user_id FROM users WHERE user_id=?",
        (user.id,)
    )

    exists = cur.fetchone()

    if not exists:
        cur.execute("""
        INSERT INTO users
        (user_id, username, first_name, referred_by, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            referred_by,
            datetime.now().isoformat()
        ))

        if referred_by and referred_by != user.id:
            cur.execute("""
            UPDATE users
            SET referrals = referrals + 1
            WHERE user_id=?
            """, (referred_by,))

            cur.execute("""
            SELECT referrals FROM users WHERE user_id=?
            """, (referred_by,))

            row = cur.fetchone()

            if row and row[0] % REFERRAL_COUNT == 0:
                cur.execute("""
                UPDATE users
                SET wallet = wallet + ?
                WHERE user_id=?
                """, (
                    REFERRAL_REWARD_USD,
                    referred_by
                ))

        con.commit()

    con.close()


def get_user(user_id):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    )

    row = cur.fetchone()
    con.close()

    return row


def create_order(
    user_id,
    order_type,
    amount,
    payment_method,
    payment_info=""
):
    con = db()
    cur = con.cursor()

    cur.execute("""
    INSERT INTO orders
    (user_id, order_type, amount, payment_method, payment_info, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        order_type,
        amount,
        payment_method,
        payment_info,
        datetime.now().isoformat()
    ))

    order_id = cur.lastrowid

    con.commit()
    con.close()

    return order_id


def save_support(user_id, message):
    con = db()
    cur = con.cursor()

    cur.execute("""
    INSERT INTO support (user_id, message, created_at)
    VALUES (?, ?, ?)
    """, (
        user_id,
        message,
        datetime.now().isoformat()
    ))

    con.commit()
    con.close()


# ==================================================
# کیبورد اصلی
# ==================================================

def main_keyboard():
    return ReplyKeyboardMarkup([
        [
            KeyboardButton("🛒 خرید ووچر یوتوپیا"),
            KeyboardButton("💰 فروش ووچر یوتوپیا")
        ],
        [
            KeyboardButton("👤 حساب من"),
            KeyboardButton("👥 دعوت دوستان")
        ],
        [
            KeyboardButton("💳 کیف پول"),
            KeyboardButton("📞 پشتیبانی")
        ],
    ], resize_keyboard=True)


# ==================================================
# /start
# ==================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    referred_by = None

    if context.args:
        try:
            referred_by = int(context.args[0])
        except ValueError:
            pass

    add_user(user, referred_by)

    await update.message.reply_text(
        "🌟 به ربات Utopia Ani خوش آمدید!\n\n"
        "خرید و فروش ووچر یوتوپیا با پشتیبانی اختصاصی.\n\n"
        "یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=main_keyboard()
    )


# ==================================================
# خرید ووچر
# ==================================================

async def buy_voucher(update, context):

    keyboard = [
        [
            InlineKeyboardButton(
                "💎 پرداخت با TRX",
                callback_data="buy_trx"
            )
        ],
        [
            InlineKeyboardButton(
                "💳 کارت‌به‌کارت",
                callback_data="buy_card"
            )
        ],
    ]

    await update.message.reply_text(
        "🛒 خرید ووچر یوتوپیا\n\n"
        f"قیمت هر دلار: {PRICE_USD:,} تومان\n\n"
        "روش پرداخت را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def buy_trx(update, context):

    query = update.callback_query
    await query.answer()

    context.user_data["state"] = "buy_trx_amount"

    await query.message.reply_text(
        "💎 خرید با TRX روی شبکه TRC20\n\n"
        "مبلغ خرید خود را به تومان وارد کنید.\n"
        "مثال: 100000"
    )


async def buy_card(update, context):

    query = update.callback_query
    await query.answer()

    context.user_data["state"] = "buy_card_amount"

    await query.message.reply_text(
        "💳 خرید کارت‌به‌کارت\n\n"
        "مبلغ خرید به تومان را وارد کنید:"
    )


# ==================================================
# فروش ووچر
# ==================================================

async def sell_voucher(update, context):

    context.user_data["state"] = "sell_code"

    await update.message.reply_text(
        "💰 فروش ووچر یوتوپیا\n\n"
        "کد ووچر خود را ارسال کنید:"
    )


# ==================================================
# حساب کاربری
# ==================================================

async def account(update, context):

    user_id = update.effective_user.id
    row = get_user(user_id)

    if not row:
        await update.message.reply_text("ابتدا /start را بزنید.")
        return

    wallet = row[4]
    referrals = row[3]

    await update.message.reply_text(
        "👤 حساب کاربری شما\n\n"
        f"🆔 شناسه: {user_id}\n"
        f"👥 تعداد دعوت‌ها: {referrals}\n"
        f"💰 موجودی کیف پول: {wallet} دلار یوتوپیا\n"
        f"💵 ارزش موجودی: {wallet * PRICE_USD:,} تومان"
    )


# ==================================================
# دعوت دوستان
# ==================================================

async def referrals(update, context):

    user_id = update.effective_user.id

    link = f"https://t.me/{context.bot.username}?start={user_id}"

    await update.message.reply_text(
        "👥 دعوت دوستان\n\n"
        f"با هر {REFERRAL_COUNT} نفر دعوت واجد شرایط، "
        f"{REFERRAL_REWARD_USD} دلار یوتوپیا دریافت می‌کنید.\n\n"
        "🔗 لینک دعوت شما:\n"
        f"{link}\n\n"
        "لینک را برای دوستان خود ارسال کنید."
    )


# ==================================================
# کیف پول
# ==================================================

async def wallet(update, context):

    row = get_user(update.effective_user.id)

    if not row:
        return

    await update.message.reply_text(
        "💳 کیف پول شما\n\n"
        f"موجودی: {row[4]} دلار یوتوپیا\n"
        f"ارزش تقریبی: {row[4] * PRICE_USD:,} تومان\n\n"
        "برای برداشت، با پشتیبانی تماس بگیرید."
    )


# ==================================================
# پشتیبانی
# ==================================================

async def support(update, context):

    context.user_data["state"] = "support"

    await update.message.reply_text(
        "📞 پشتیبانی Utopia Ani\n\n"
        "پیام خود را ارسال کنید.\n"
        "پیام شما مستقیماً برای ادمین ارسال می‌شود."
    )


# ==================================================
# پیام‌های متنی
# ==================================================

async def text_handler(update, context):

    text = update.message.text
    user = update.effective_user
    state = context.user_data.get("state")

    if text == "🛒 خرید ووچر یوتوپیا":
        await buy_voucher(update, context)
        return

    if text == "💰 فروش ووچر یوتوپیا":
        await sell_voucher(update, context)
        return

    if text == "👤 حساب من":
        await account(update, context)
        return

    if text == "👥 دعوت دوستان":
        await referrals(update, context)
        return

    if text == "💳 کیف پول":
        await wallet(update, context)
        return

    if text == "📞 پشتیبانی":
        await support(update, context)
        return

    # ----------------------------------------------
    # خرید TRX
    # ----------------------------------------------

    if state == "buy_trx_amount":

        try:
            amount = int(text)
            if amount <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ مبلغ معتبر وارد کنید. مثال: 100000"
            )
            return

        order_id = create_order(
            user.id,
            "buy",
            str(amount),
            "TRX_TRON",
            TRX_ADDRESS
        )

        await update.message.reply_text(
            "💎 سفارش خرید ثبت شد.\n\n"
            f"شماره سفارش: #{order_id}\n"
            f"مبلغ: {amount:,} تومان\n"
            f"تعداد دلار: {amount / PRICE_USD:.4f}\n\n"
            "آدرس پرداخت TRC20:\n"
            f"{TRX_ADDRESS}\n\n"
            "پس از پرداخت، رسید یا TXID را ارسال کنید."
        )

        await context.bot.send_message(
            ADMIN_ID,
            f"🛒 سفارش خرید جدید #{order_id}\n\n"
            f"کاربر: {user.first_name}\n"
            f"ID: {user.id}\n"
            f"مبلغ: {amount:,} تومان\n"
            f"روش: TRX TRC20\n\n"
            "وضعیت: در انتظار رسید"
        )

        context.user_data["state"] = "buy_trx_receipt"
        return

    # ----------------------------------------------
    # خرید کارت‌به‌کارت
    # ----------------------------------------------

    if state == "buy_card_amount":

        try:
            amount = int(text)
            if amount <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("مبلغ معتبر وارد کنید.")
            return

        order_id = create_order(
            user.id,
            "buy",
            str(amount),
            "CARD_TO_CARD"
        )

        await update.message.reply_text(
            f"سفارش #{order_id} ثبت شد.\n\n"
            f"مبلغ: {amount:,} تومان\n\n"
            "اطلاعات کارت‌به‌کارت توسط پشتیبانی ارسال می‌شود."
        )

        await context.bot.send_message(
            ADMIN_ID,
            f"💳 سفارش کارت‌به‌کارت #{order_id}\n"
            f"کاربر: {user.id}\n"
            f"مبلغ: {amount:,} تومان"
        )

        context.user_data["state"] = "buy_card_receipt"
        return

    # ----------------------------------------------
    # رسید خرید
    # ----------------------------------------------

    if state in ["buy_trx_receipt", "buy_card_receipt"]:

        await context.bot.send_message(
            ADMIN_ID,
            f"🧾 رسید خرید از کاربر {user.id}\n\n{text}"
        )

        await update.message.reply_text(
            "✅ رسید شما برای ادمین ارسال شد.\n"
            "پس از بررسی، سفارش تأیید می‌شود."
        )

        context.user_data["state"] = None
        return

    # ----------------------------------------------
    # فروش: دریافت کد
    # ----------------------------------------------

    if state == "sell_code":

        context.user_data["sell_code"] = text
        context.user_data["state"] = "sell_iban"

        await update.message.reply_text(
            "✅ کد ووچر دریافت شد.\n\n"
            "لطفاً شماره شبا بانکی خود را وارد کنید.\n"
            "مثال: IR..."
        )
        return

    # ----------------------------------------------
    # فروش: دریافت شبا
    # ----------------------------------------------

    if state == "sell_iban":

        iban = text
        code = context.user_data.get("sell_code", "")

        order_id = create_order(
            user.id,
            "sell",
            "نامشخص",
            "BANK_IBAN",
            f"CODE: {code}\nIBAN: {iban}"
        )

        await update.message.reply_text(
            f"✅ درخواست فروش شما ثبت شد.\n\n"
            f"شماره سفارش: #{order_id}\n"
            "پس از بررسی کد ووچر، پرداخت انجام می‌شود."
        )

        await context.bot.send_message(
            ADMIN_ID,
            f"💰 فروش ووچر جدید #{order_id}\n\n"
            f"کاربر: {user.first_name}\n"
            f"ID: {user.id}\n"
            f"کد ووچر: {code}\n"
            f"شماره شبا: {iban}\n\n"
            "وضعیت: در انتظار بررسی"
        )

        context.user_data["state"] = None
        return

    # ----------------------------------------------
    # پشتیبانی
    # ----------------------------------------------

    if state == "support":

        save_support(user.id, text)

        await context.bot.send_message(
            ADMIN_ID,
            f"📞 پیام پشتیبانی جدید\n\n"
            f"کاربر: {user.first_name}\n"
            f"ID: {user.id}\n\n"
            f"{text}\n\n"
            f"برای پاسخ:\n/reply {user.id} متن پاسخ"
        )

        await update.message.reply_text(
            "✅ پیام شما برای پشتیبانی ارسال شد."
        )

        context.user_data["state"] = None
        return

    await update.message.reply_text(
        "لطفاً یکی از گزینه‌های منو را انتخاب کنید.",
        reply_markup=main_keyboard()
    )


# ==================================================
# دریافت رسید عکس
# ==================================================

async def photo_handler(update, context):

    state = context.user_data.get("state")

    if state not in ["buy_trx_receipt", "buy_card_receipt"]:
        return

    user = update.effective_user

    await context.bot.send_message(
        ADMIN_ID,
        f"🧾 رسید تصویری از کاربر {user.id}"
    )

    await update.message.forward(ADMIN_ID)

    await update.message.reply_text(
        "✅ رسید تصویری شما برای ادمین ارسال شد."
    )

    context.user_data["state"] = None


# ==================================================
# پاسخ ادمین
# ==================================================

async def reply_command(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "فرمت:\n/reply USER_ID متن پاسخ"
        )
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("شناسه کاربر نامعتبر است.")
        return

    message = " ".join(context.args[1:])

    try:
        await context.bot.send_message(
            user_id,
            f"📞 پاسخ پشتیبانی:\n\n{message}"
        )

        await update.message.reply_text("✅ پاسخ ارسال شد.")

    except Exception as e:
        await update.message.reply_text(
            f"❌ ارسال ناموفق بود:\n{e}"
        )


# ==================================================
# لیست سفارش‌ها
# ==================================================

async def orders_command(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    con = db()
    cur = con.cursor()

    cur.execute("""
    SELECT id, user_id, order_type, amount, status
    FROM orders
    ORDER BY id DESC
    LIMIT 20
    """)

    rows = cur.fetchall()
    con.close()

    if not rows:
        await update.message.reply_text("هنوز سفارشی ثبت نشده.")
        return

    text = "📋 آخرین سفارش‌ها\n\n"

    for row in rows:
        text += (
            f"#{row[0]} | "
            f"User: {row[1]} | "
            f"{row[2]} | "
            f"{row[3]} | "
            f"{row[4]}\n"
        )

    await update.message.reply_text(text)


# ==================================================
# اجرای ربات
# ==================================================

def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN در Environment Variables تنظیم نشده است."
        )

    init_db()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("reply", reply_command)
    )

    application.add_handler(
        CommandHandler("orders", orders_command)
    )

    application.add_handler(
        CallbackQueryHandler(buy_trx, pattern="^buy_trx$")
    )

    application.add_handler(
        CallbackQueryHandler(buy_card, pattern="^buy_card$")
    )

    application.add_handler(
        MessageHandler(filters.PHOTO, photo_handler)
    )

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
    )

    logger.info("Utopia Ani is starting...")

    application.run_polling()


if __name__ == "__main__":
    main()