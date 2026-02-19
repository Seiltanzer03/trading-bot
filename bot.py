import os
import logging
import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── CONFIG ────────────────────────────────────────────────────────────────────
BOT_TOKEN       = os.environ["BOT_TOKEN"]
OPENROUTER_KEY  = os.environ["OPENROUTER_API_KEY"]
CHANNEL_ID      = os.environ["CHANNEL_ID"]
MODEL           = os.getenv("MODEL", "anthropic/claude-3.5-haiku")
# Добавь свой Telegram user_id сюда (через запятую если несколько): "123456789,987654321"
ADMIN_IDS       = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

SYSTEM_PROMPT_PREFIX = """Ты — умный торговый ассистент по Институциональной торговой стратегии 2025-2026, разработанной @Funambul.

Твоя задача: объяснять стратегию простым языком, отвечать на вопросы по ней, помогать понять сетапы и правила.
Ты НЕ даёшь конкретных торговых советов ("купи сейчас", "шорти X") — только объясняешь стратегию.
Отвечай на русском языке. Если термин непонятен пользователю — дай краткое определение.
Если вопрос выходит за рамки стратегии — вежливо скажи об этом.

═══════════════════════════════════════
ПОЛНОЕ СОДЕРЖАНИЕ СТРАТЕГИИ:
═══════════════════════════════════════
"""


# ─── ЗАГРУЗКА СТРАТЕГИИ ────────────────────────────────────────────────────────

def load_strategy() -> str:
    """
    Загружает стратегию из файла.
    Приоритет: strategy.docx → strategy.txt
    При обновлении стратегии просто замени файл и вызови /reload в боте.
    """
    if os.path.exists("strategy.docx"):
        try:
            from docx import Document
            doc = Document("strategy.docx")
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            logger.info(f"✅ Стратегия загружена из strategy.docx ({len(text)} символов)")
            return text
        except ImportError:
            logger.warning("⚠️ python-docx не установлен, пробуем strategy.txt")
        except Exception as e:
            logger.error(f"Ошибка чтения strategy.docx: {e}")

    if os.path.exists("strategy.txt"):
        try:
            with open("strategy.txt", "r", encoding="utf-8") as f:
                text = f.read()
            logger.info(f"✅ Стратегия загружена из strategy.txt ({len(text)} символов)")
            return text
        except Exception as e:
            logger.error(f"Ошибка чтения strategy.txt: {e}")

    logger.error("❌ Файл стратегии не найден! Положи strategy.docx или strategy.txt рядом с bot.py")
    return "ОШИБКА: Файл стратегии не найден. Обратитесь к администратору."


# Загружаем при старте
strategy_text = load_strategy()


def build_system_prompt(strategy: str) -> str:
    return SYSTEM_PROMPT_PREFIX + strategy


# ─── OPENROUTER ────────────────────────────────────────────────────────────────

async def ask_openrouter(user_message: str, history: list, system_prompt: str) -> str:
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history[-10:])  # последние 10 сообщений для контекста
    messages.append({"role": "user", "content": user_message})

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://t.me/trading_strategy_bot",
            },
            json={
                "model": MODEL,
                "messages": messages,
                "max_tokens": 1024,
                "temperature": 0.7,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


# ─── ПРОВЕРКА ДОСТУПА ──────────────────────────────────────────────────────────

async def check_channel_membership(bot, user_id: int, channel_id: str) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.warning(f"Ошибка проверки членства для {user_id}: {e}")
        return False


# ─── HANDLERS ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    has_access = await check_channel_membership(context.bot, user.id, CHANNEL_ID)

    if has_access:
        await update.message.reply_text(
            f"Привет, {user.first_name}! 👋\n\n"
            "Я помогу тебе разобраться в Институциональной торговой стратегии @Funambul.\n\n"
            "Задавай любые вопросы:\n"
            "• Объяснение сетапов (№1–16)\n"
            "• Правила риск-менеджмента\n"
            "• Как пользоваться калькулятором\n"
            "• Чек-лист перед входом в сделку\n\n"
            "Просто напиши свой вопрос! 📊\n\n"
            "/clear — очистить историю диалога"
        )
    else:
        await update.message.reply_text(
            "👋 Привет!\n\n"
            "Этот бот доступен только для участников закрытого канала.\n\n"
            "Чтобы получить доступ к стратегии и боту — приобрети инфопродукт:\n"
            "👉 @Funambul\n\n"
            "После покупки ты получишь доступ в канал и сможешь пользоваться ботом."
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    has_access = await check_channel_membership(context.bot, user.id, CHANNEL_ID)

    if not has_access:
        await update.message.reply_text(
            "⛔ У тебя нет доступа.\n\n"
            "Приобрети стратегию у @Funambul, чтобы получить доступ в закрытый канал и к этому боту."
        )
        return

    user_text = update.message.text
    if not user_text:
        return

    if "history" not in context.user_data:
        context.user_data["history"] = []

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        system_prompt = build_system_prompt(strategy_text)
        reply = await ask_openrouter(user_text, context.user_data["history"], system_prompt)

        context.user_data["history"].append({"role": "user", "content": user_text})
        context.user_data["history"].append({"role": "assistant", "content": reply})

        # Ограничиваем историю 20 сообщениями
        if len(context.user_data["history"]) > 20:
            context.user_data["history"] = context.user_data["history"][-20:]

        await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"Ошибка OpenRouter: {e}")
        await update.message.reply_text(
            "⚠️ Произошла ошибка при обращении к AI. Попробуй ещё раз через несколько секунд."
        )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сбросить историю диалога."""
    context.user_data["history"] = []
    await update.message.reply_text("🔄 История диалога очищена. Начинаем заново!")


async def reload_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Перезагрузить стратегию из файла без перезапуска бота.
    Только для администраторов (ADMIN_IDS в переменных окружения).
    """
    global strategy_text
    user_id = update.effective_user.id

    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Эта команда только для администраторов.")
        return

    old_len = len(strategy_text)
    strategy_text = load_strategy()
    new_len = len(strategy_text)

    await update.message.reply_text(
        f"✅ Стратегия перезагружена!\n"
        f"Было: {old_len} символов → Стало: {new_len} символов\n\n"
        f"Все новые диалоги теперь используют обновлённую версию."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статус бота — только для администраторов."""
    user_id = update.effective_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        return

    source = "strategy.docx" if os.path.exists("strategy.docx") else \
             "strategy.txt" if os.path.exists("strategy.txt") else "❌ файл не найден"

    await update.message.reply_text(
        f"📊 Статус бота:\n"
        f"Модель: {MODEL}\n"
        f"Файл стратегии: {source}\n"
        f"Размер стратегии: {len(strategy_text)} символов\n"
        f"Канал: {CHANNEL_ID}"
    )


# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("reload", reload_strategy))   # для админа
    app.add_handler(CommandHandler("status", status))            # для админа
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info(f"🤖 Бот запущен! Стратегия: {len(strategy_text)} символов, модель: {MODEL}")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
