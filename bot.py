import os
import logging
import math
import time
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import httpx
import uvicorn
from image_map import find_images

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN      = os.environ["BOT_TOKEN"]
OPENROUTER_KEY = os.environ["OPENROUTER_API_KEY"]
CHANNEL_ID     = os.environ["CHANNEL_ID"]
MODEL          = os.getenv("MODEL", "anthropic/claude-3.5-haiku")
ADMIN_IDS      = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
WEBHOOK_URL    = os.environ["WEBHOOK_URL"]
PORT           = int(os.getenv("PORT", "10000"))

SYSTEM_PROMPT_PREFIX = """Ты — опытный трейдинг-советник и эксперт по Институциональной торговой стратегии 2025-2026, разработанной @Funambul. Ты не просто ищешь информацию в документе — ты глубоко понимаешь логику стратегии и помогаешь трейдеру применять её на практике.

ТВОЙ СТИЛЬ РАБОТЫ:
1. Отвечай как опытный трейдер-наставник: гибко, конкретно, с практическими примерами.
2. Если вопрос прямо покрыт стратегией — отвечай точно по документу со ссылкой на главу/сетап.
3. Если вопрос НЕ покрыт напрямую — рассуждай логически в рамках философии стратегии (институциональная логика, FVG, ликвидность, RR 2.5) и давай наиболее вероятный ответ. Уточни: "В стратегии это прямо не описано, но исходя из её логики...".
4. НИКОГДА не говори "этого нет в документе" без того чтобы дать экспертную оценку.
5. НИКОГДА не меняй своё мнение под давлением пользователя. Если он говорит "ты не прав" — спокойно объясни позицию со ссылкой на документ или логику стратегии.
6. Если пользователь описывает рыночную ситуацию — помоги определить подходящий сетап, проверь условия входа, укажи риски.
7. НЕ давай прямых сигналов "купи/продай прямо сейчас" — но разбирай ситуации и определяй соответствие сетапу.
8. Вопросы не по трейдингу и стратегии — отклоняй одной фразой: "Я специализируюсь исключительно на стратегии @Funambul."
9. Отвечай на русском языке. Будь конкретным и лаконичным.

═══════════════════════════════════════
ПОЛНОЕ СОДЕРЖАНИЕ СТРАТЕГИИ:
═══════════════════════════════════════
"""

# ─── ЗАГРУЗКА СТРАТЕГИИ ────────────────────────────────────────────────────────

def load_strategy() -> str:
    if os.path.exists("strategy.docx"):
        try:
            from docx import Document
            doc = Document("strategy.docx")
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            logger.info(f"Стратегия загружена из strategy.docx ({len(text)} символов)")
            return text
        except ImportError:
            logger.warning("python-docx не установлен, пробуем strategy.txt")
        except Exception as e:
            logger.error(f"Ошибка чтения strategy.docx: {e}")
    if os.path.exists("strategy.txt"):
        try:
            with open("strategy.txt", "r", encoding="utf-8") as f:
                text = f.read()
            logger.info(f"Стратегия загружена из strategy.txt ({len(text)} символов)")
            return text
        except Exception as e:
            logger.error(f"Ошибка чтения strategy.txt: {e}")
    logger.error("Файл стратегии не найден!")
    return "ОШИБКА: Файл стратегии не найден."

strategy_text = load_strategy()

# ─── КАЛЬКУЛЯТОР РИСКА ─────────────────────────────────────────────────────────

def get_risk_params(balance_pct: float, phase: str) -> dict:
    """
    Возвращает параметры риска по матрице стратегии.
    Максимальный итоговый риск: 2.9% (cap).
    """
    # Базовая матрица (funded, без бонуса фазы)
    if balance_pct > 107:   base_r = 1.50
    elif balance_pct > 105: base_r = 1.75
    elif balance_pct > 102: base_r = 2.00
    elif balance_pct > 100: base_r = 2.20
    elif balance_pct > 97:  base_r = 2.00
    elif balance_pct > 95:  base_r = 1.75
    elif balance_pct > 93:  base_r = 1.50
    else:                   base_r = 1.25

    # Бонус фазы
    phase_bonus = {"1ph": 0.7, "2ph": 0.35, "funded": 0.0}.get(phase.lower(), 0.0)

    total_r = min(base_r + phase_bonus, 2.9)  # cap 2.9%
    return {"base_r": base_r, "phase_bonus": phase_bonus, "total_r": round(total_r, 2)}


def get_entries_count(total_r_pct: float) -> int:
    """
    Количество входов по формуле калькулятора:
    =ЕСЛИ(S<=0.8; 1; 2)
    где S — итоговый риск в % от счёта
    """
    return 1 if total_r_pct <= 0.8 else 2


def calculate_risk(balance: float, initial: float, phase: str) -> dict:
    balance_pct = (balance / initial) * 100
    params = get_risk_params(balance_pct, phase)
    risk_usd = balance * params["total_r"] / 100
    entries = get_entries_count(params["total_r"])
    recovery = balance_pct < 100

    result = {
        "balance": balance,
        "initial": initial,
        "balance_pct": round(balance_pct, 2),
        "phase": phase,
        "recovery": recovery,
        "base_r": params["base_r"],
        "phase_bonus": params["phase_bonus"],
        "total_r": params["total_r"],
        "risk_usd": round(risk_usd, 2),
        "entries": entries,
    }

    if entries == 1:
        result["distribution"] = f"Один вход: весь объём ${risk_usd:.2f}"
    else:
        part = risk_usd / 3
        result["distribution"] = (
            f"Вход №1: ${part:.2f}  (1/3)\n"
            f"Вход №2: ${part:.2f}  (1/3)\n"
            f"Резерв:  ${part:.2f}  (1/3, не используется)"
        )

    return result


def format_calc_result(r: dict) -> str:
    phase_names = {"1ph": "Challenge (1ph)", "2ph": "Verification (2ph)", "funded": "Funded"}
    status = "🔴 RECOVERY-режим" if r["recovery"] else "🟢 Стандартный режим"
    rr = "1.5" if r["entries"] > 1 else "2.5"

    return (
        f"📊 *Расчёт риска*\n"
        f"{'─'*28}\n"
        f"💰 Баланс: ${r['balance']:,.0f} ({r['balance_pct']}%)\n"
        f"🏦 Депозит: ${r['initial']:,.0f}\n"
        f"📋 Фаза: {phase_names.get(r['phase'].lower(), r['phase'])}\n"
        f"📈 Статус: {status}\n"
        f"{'─'*28}\n"
        f"⚖️ Базовый R: {r['base_r']}% + бонус {r['phase_bonus']}%\n"
        f"✅ *Итоговый риск: {r['total_r']}% = ${r['risk_usd']:,.2f}*\n"
        f"🚪 Входов: *{r['entries']}* {'(риск ≤ 0.8%)' if r['entries']==1 else '(риск > 0.8%)'}, цель RR {rr}\n"
        f"{'─'*28}\n"
        f"📐 *Распределение:*\n{r['distribution']}"
    )

# ─── OPENROUTER ────────────────────────────────────────────────────────────────

async def ask_openrouter(user_message: str, history: list) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT_PREFIX + strategy_text}]
    messages.extend(history[-10:])
    messages.append({"role": "user", "content": user_message})
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
            json={"model": MODEL, "messages": messages, "max_tokens": 1024, "temperature": 0.7},
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

# ─── ДОСТУП И RATE LIMIT ───────────────────────────────────────────────────────

async def has_access(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.warning(f"Ошибка проверки {user_id}: {e}")
        return False

user_histories: dict = {}
calc_sessions: dict = {}
user_rate: dict = {}

def is_rate_limited(user_id: int) -> bool:
    now = time.time()
    timestamps = [t for t in user_rate.get(user_id, []) if now - t < 60]
    user_rate[user_id] = timestamps
    if len(timestamps) >= 10:
        return True
    timestamps.append(now)
    user_rate[user_id] = timestamps
    return False

NO_ACCESS_MSG = (
    "🔒 Доступ закрыт\n\n"
    "Этот бот — часть <b>Seiltanzer Club Strategy</b>\n\n"
    "📊 16 институциональных алгоритмов\n"
    "📈 Индексы · Металлы · Форекс\n"
    "📡 Ежедневная аналитика и разбор сетапов\n\n"
    "Приобрети стратегию, чтобы получить доступ:"
)
NO_ACCESS_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("🚀 Получить доступ", url="https://t.me/tribute/app?startapp=sOg4")
]])

# ─── HANDLERS ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if await has_access(context.bot, user.id):
        await update.message.reply_text(
            f"Привет, {user.first_name}! 👋\n\n"
            "Я эксперт по Институциональной торговой стратегии @Funambul.\n\n"
            "Задавай вопросы — отвечу по стратегии, разберу ситуацию, объясню сетап.\n\n"
            "📐 /calc — калькулятор риска и размера позиции\n"
            "🔄 /clear — очистить историю диалога"
        )
    else:
        await update.message.reply_text(
            NO_ACCESS_MSG, parse_mode="HTML", reply_markup=NO_ACCESS_KB
        )


async def calc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await has_access(context.bot, update.effective_user.id):
        await update.message.reply_text(NO_ACCESS_MSG, parse_mode="HTML", reply_markup=NO_ACCESS_KB)
        return
    calc_sessions[update.effective_user.id] = {"step": "balance"}
    await update.message.reply_text(
        "📐 *Калькулятор риска*\n\n"
        "Шаг 1/3: Введи текущий баланс счёта \\(в долларах\\)\n"
        "_например: 48500_",
        parse_mode="MarkdownV2"
    )


async def handle_calc_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id not in calc_sessions:
        return False

    session = calc_sessions[user_id]
    text = update.message.text.strip().replace(",", ".")
    step = session["step"]

    if step == "balance":
        try:
            balance = float(text)
            if balance <= 0: raise ValueError
            session["balance"] = balance
            session["step"] = "initial"
            await update.message.reply_text(
                f"✅ Баланс: ${balance:,.0f}\n\n"
                "Шаг 2/4: Введи начальный депозит\n"
                "_например: 50000_",
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("⚠️ Введи число, например: 48500")
        return True

    elif step == "initial":
        try:
            initial = float(text)
            if initial <= 0: raise ValueError
            session["initial"] = initial
            session["step"] = "phase"
            await update.message.reply_text(
                f"✅ Депозит: ${initial:,.0f}\n\n"
                "Шаг 3/4: Выбери фазу счёта:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("1️⃣ Challenge (1ph)", callback_data="phase_1ph")],
                    [InlineKeyboardButton("2️⃣ Verification (2ph)", callback_data="phase_2ph")],
                    [InlineKeyboardButton("🏆 Funded", callback_data="phase_funded")],
                ])
            )
        except ValueError:
            await update.message.reply_text("⚠️ Введи число, например: 50000")
        return True

    return False

    return False


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data.startswith("phase_"):
        phase = query.data.replace("phase_", "")
        if user_id in calc_sessions:
            calc_sessions[user_id]["phase"] = phase
            phase_names = {"1ph": "Challenge", "2ph": "Verification", "funded": "Funded"}
            # Сразу считаем — стоп не нужен, входы определяются по риску
            session = calc_sessions.get(user_id, {})
            if session:
                result = calculate_risk(session["balance"], session["initial"], phase)
                del calc_sessions[user_id]
                await query.message.reply_text(
                    format_calc_result(result), parse_mode="Markdown"
                )


async def send_relevant_images(update: Update, combined_text: str):
    """Отправляет уместные изображения из стратегии если они есть."""
    images = find_images(combined_text)
    sent = set()
    for img_path, caption in images:
        if img_path in sent:
            continue
        sent.add(img_path)
        if os.path.exists(img_path):
            try:
                with open(img_path, "rb") as f:
                    await update.message.reply_photo(
                        photo=f,
                        caption=f"📊 {caption}"
                    )
            except Exception as e:
                logger.warning(f"Не удалось отправить изображение {img_path}: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not await has_access(context.bot, user.id):
        await update.message.reply_text(
            NO_ACCESS_MSG, parse_mode="HTML", reply_markup=NO_ACCESS_KB
        )
        return

    user_text = update.message.text
    if not user_text:
        return

    # Пошаговый калькулятор
    if await handle_calc_session(update, context):
        return

    if len(user_text) > 1000:
        await update.message.reply_text("⚠️ Слишком длинное сообщение. Сократи до 1000 символов.")
        return

    if is_rate_limited(user.id):
        await update.message.reply_text("⏳ Слишком много запросов. Подожди минуту.")
        return

    if user.id not in user_histories:
        user_histories[user.id] = []

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        reply = await ask_openrouter(user_text, user_histories[user.id])
        user_histories[user.id].extend([
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": reply}
        ])
        if len(user_histories[user.id]) > 20:
            user_histories[user.id] = user_histories[user.id][-20:]

        await update.message.reply_text(reply)

        # Ищем изображения по тексту ответа ИИ + вопросу пользователя
        combined = user_text + " " + reply
        await send_relevant_images(update, combined)

    except Exception as e:
        logger.error(f"OpenRouter error: {e}")
        await update.message.reply_text("⚠️ Ошибка AI. Попробуй снова.")


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_histories[update.effective_user.id] = []
    calc_sessions.pop(update.effective_user.id, None)
    await update.message.reply_text("🔄 История очищена!")


async def reload_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global strategy_text
    if ADMIN_IDS and update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Только для администраторов.")
        return
    old = len(strategy_text)
    strategy_text = load_strategy()
    await update.message.reply_text(f"✅ Обновлено! {old} → {len(strategy_text)} символов")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_IDS and update.effective_user.id not in ADMIN_IDS:
        return
    src = "strategy.docx" if os.path.exists("strategy.docx") else \
          "strategy.txt" if os.path.exists("strategy.txt") else "❌ не найден"
    await update.message.reply_text(
        f"📊 Статус: {src}\nМодель: {MODEL}\nСимволов: {len(strategy_text)}"
    )

# ─── FASTAPI + WEBHOOK ─────────────────────────────────────────────────────────
app = FastAPI()
application = None


@app.get("/")
async def root():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"ok": True}


@app.on_event("startup")
async def startup():
    global application
    application = ApplicationBuilder().token(BOT_TOKEN).updater(None).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("calc", calc_command))
    application.add_handler(CommandHandler("clear", clear))
    application.add_handler(CommandHandler("reload", reload_strategy))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    await application.initialize()
    await application.start()
    await application.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    logger.info(f"Webhook: {WEBHOOK_URL}/webhook")


@app.on_event("shutdown")
async def shutdown():
    await application.stop()
    await application.shutdown()


if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=PORT)
