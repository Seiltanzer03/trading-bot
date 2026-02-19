import os
import logging
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import httpx
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN       = os.environ["BOT_TOKEN"]
OPENROUTER_KEY  = os.environ["OPENROUTER_API_KEY"]
CHANNEL_ID      = os.environ["CHANNEL_ID"]
MODEL           = os.getenv("MODEL", "anthropic/claude-3.5-haiku")
ADMIN_IDS       = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
WEBHOOK_URL     = os.environ["WEBHOOK_URL"]
PORT            = int(os.getenv("PORT", "10000"))

SYSTEM_PROMPT_PREFIX = """Ты — умный торговый ассистент по Институциональной торговой стратегии 2025-2026, разработанной @Funambul.
Объясняй стратегию простым языком. НЕ давай конкретных торговых советов.
Отвечай на русском языке. Если вопрос вне стратегии — скажи об этом.

═══════════════════════════════════════
ПОЛНОЕ СОДЕРЖАНИЕ СТРАТЕГИИ:
═══════════════════════════════════════
"""

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

async def has_access(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.warning(f"Ошибка проверки {user_id}: {e}")
        return False

user_histories: dict = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if await has_access(context.bot, user.id):
        await update.message.reply_text(
            f"Привет, {user.first_name}! 👋\n\n"
            "Я помогу разобраться в Институциональной торговой стратегии @Funambul.\n\n"
            "Задавай вопросы по сетапам №1–16, риск-менеджменту, калькулятору.\n\n"
            "/clear — очистить историю диалога"
        )
    else:
        await update.message.reply_text(
            "👋 Привет!\n\n"
            "Этот бот доступен только для участников закрытого клуба.\n\n"
            "https://t.me/tribute/app?startapp=sOg4"
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await has_access(context.bot, user.id):
        await update.message.reply_text(
            "⛔ У тебя нет доступа к боту.\n\n"
            "https://t.me/tribute/app?startapp=sOg4"
        )
        return
    user_text = update.message.text
    if not user_text:
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
    except Exception as e:
        logger.error(f"OpenRouter error: {e}")
        await update.message.reply_text("⚠️ Ошибка AI. Попробуй снова.")

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_histories[update.effective_user.id] = []
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
    application.add_handler(CommandHandler("clear", clear))
    application.add_handler(CommandHandler("reload", reload_strategy))
    application.add_handler(CommandHandler("status", status_cmd))
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
    uvicorn.run("bot:app_fastapi", host="0.0.0.0", port=PORT)
