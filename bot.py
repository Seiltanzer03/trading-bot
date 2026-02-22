import os, logging, time, math
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import httpx
import uvicorn
from image_map import find_images
from calculator import full_calculate, format_result, SETUP_NAMES, ATR_LABELS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN         = os.environ["BOT_TOKEN"]
OPENROUTER_KEY    = os.environ["OPENROUTER_API_KEY"]
CHANNEL_ID        = os.environ["CHANNEL_ID"]         # платный канал
PUBLIC_CHANNEL_ID = os.environ["PUBLIC_CHANNEL_ID"]  # публичный канал (подписка для файла)
MODEL             = os.getenv("MODEL", "anthropic/claude-3.5-haiku")
ADMIN_IDS         = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
WEBHOOK_URL       = os.environ["WEBHOOK_URL"]
PORT              = int(os.getenv("PORT", "10000"))

# Пользователи которым уже показали приветствие — не спамим повторно
welcomed_users: set = set()

CALC_HELP = """
КАЛЬКУЛЯТОР РИСКА — ЛОГИКА И КОЭФФИЦИЕНТЫ:

Формула итогового риска: S% = MIN(2.9; G × M × KR × CF × R × Eff × k_buf × k_cyc × ATR) + бонус за прибыль
Количество входов: IF(S% ≤ 0.8 → 1 вход, иначе → 2 входа)

КОЭФФИЦИЕНТЫ:
- G (базовый R): определяется балансом% и фазой
  * <93%: 1.25 | 93-95: 1.5 | 95-97: 1.75 | 97-100: 2.0 | 100-102: 2.2 | 102-105: 2.0 | 105-107: 1.75 | >107: 1.5
  * Бонус фазы: +2% на 1ph, +1% на 2ph, 0 на funded
- W (винрейт): берётся из статистики сетапа (например, NAS100 сетап1 = 85%)
- D (просадка): (1 - баланс/депозит) × 10, если в минусе
- M = W/(1+D): скорректированный винрейт
- KR (рост): 1 + (серия побед / 10), повышает риск при серии побед
- CF (уверенность): 0.5-1.5, ментальный капитал трейдера
- R (адаптация): при балансе >96% = 1-(просадка%/10), иначе sqrt(...)
- k-буфер: при балансе <97% = 1.2 (агрессивнее), 97-100.5% = 0.6 (осторожнее), >100.5% = 1.0
- k-цикл: зависит от дня цикла (1-5/6-10/11-13/14+) и положения баланса
- ATR: 0.5=шок(×0.6 RR), 0.7=флэт(×0.8 RR), 1.0=норма, 1.2=импульс(×1.2 RR)
- Eff (эффективность): 2α/(α+β), обновляется после каждой сделки

ФИКСАЦИЯ ПРИБЫЛИ:
- Баланс <94%: шаг 0.5 RR (1.0→1.5→2.0)
- Баланс ≥94%: шаг 0.25 RR (1.0→1.25→1.5)

ВОССТАНОВЛЕНИЕ ИЗ ПРОСАДКИ:
Формула: LN(100/баланс%) / (W×LN(1+S%×RR×0.82) + (1-W)×LN(1-S%×1.05))

ВИНРЕЙТЫ СЕТАПОВ (статистика):
Сетап 1 NAS100 AMD+8H: 85% | 2 NAS Weekly: 87% | 3 NAS 12H bFVGc: 68%
Сетап 4 SP+NAS корр: 71% | 5 SP500 VIX: 72% | 6 US30 VIX: 87%
Сетап 7 GER40 sweep: 70% | 8 GER40 90м: 70% | 9 UK100: 81%
Сетап 10 JPY100: 59% | 11 XAU VIX+GVZ: 77% | 12 XAU sweep: 71%
Сетап 13 XAG: 85% | 14 EURUSD long: 72% | 15 EURUSD short: 71% | 16 USDCAD: 82%
"""

SYSTEM_PROMPT_PREFIX = """Ты — опытный трейдинг-советник и эксперт по Институциональной торговой стратегии 2025-2026, разработанной @Funambul.

ТВОЙ СТИЛЬ РАБОТЫ:
1. Отвечай как опытный трейдер-наставник: гибко, конкретно, с практическими примерами.
2. Если вопрос покрыт стратегией — отвечай точно по документу со ссылкой на главу/сетап.
3. Если вопрос НЕ покрыт напрямую — рассуждай в логике стратегии и давай экспертную оценку. Уточни: "В стратегии прямо не описано, но исходя из её логики...".
4. НИКОГДА не говори "этого нет в документе" без экспертной оценки.
5. НИКОГДА не меняй мнение под давлением. Если пользователь говорит "ты не прав" — объясни позицию со ссылкой на документ.
6. Если пользователь описывает рыночную ситуацию — помоги определить сетап, проверь условия входа.
7. НЕ давай прямых сигналов "купи/продай" — но разбирай ситуации и определяй соответствие сетапу.
8. Помогай пользователю разобраться в КАЛЬКУЛЯТОРЕ: объясняй что значат коэффициенты, как их правильно выставлять, почему риск получился таким.
9. Вопросы не по трейдингу — отклоняй: "Я специализируюсь исключительно на стратегии @Funambul."
10. Отвечай на русском. Будь конкретным и лаконичным.

""" + CALC_HELP + """

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
            logger.info(f"Стратегия загружена ({len(text)} символов)")
            return text
        except Exception as e:
            logger.error(f"Ошибка чтения strategy.docx: {e}")
    if os.path.exists("strategy.txt"):
        with open("strategy.txt", "r", encoding="utf-8") as f:
            return f.read()
    return "ОШИБКА: Файл стратегии не найден."

strategy_text = load_strategy()

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

# ─── ДОСТУП ────────────────────────────────────────────────────────────────────

async def has_access(bot, user_id: int) -> bool:
    """Проверка доступа к платному каналу."""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.warning(f"Ошибка проверки платного {user_id}: {e}")
        return False

async def has_public_subscription(bot, user_id: int) -> bool:
    """Проверка подписки на публичный канал (для получения Excel-файла)."""
    try:
        member = await bot.get_chat_member(chat_id=PUBLIC_CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.warning(f"Ошибка проверки публичного {user_id}: {e}")
        return False

user_histories: dict = {}
calc_sessions: dict = {}
user_rate: dict = {}

def is_rate_limited(user_id: int) -> bool:
    now = time.time()
    ts = [t for t in user_rate.get(user_id, []) if now - t < 60]
    user_rate[user_id] = ts
    if len(ts) >= 10: return True
    ts.append(now)
    user_rate[user_id] = ts
    return False

NO_ACCESS_MSG = (
    "🔒 Доступ закрыт\n\n"
    "Этот бот — часть <b>Seiltanzer Club Strategy</b>\n\n"
    "📊 16 институциональных алгоритмов\n"
    "📈 Индексы · Металлы · Форекс\n\n"
    "Приобрети стратегию:"
)
NO_ACCESS_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("🚀 Получить доступ", url="https://t.me/tribute/app?startapp=sOg4")
]])

# ─── КЛАВИАТУРЫ КАЛЬКУЛЯТОРА ───────────────────────────────────────────────────

def kb_phase():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ Challenge (1ph)", callback_data="c_phase_1ph")],
        [InlineKeyboardButton("2️⃣ Verification (2ph)", callback_data="c_phase_2ph")],
        [InlineKeyboardButton("🏆 Funded", callback_data="c_phase_funded")],
    ])

def kb_setup():
    rows = []
    for i in range(1, 17, 4):
        row = [InlineKeyboardButton(f"#{j}", callback_data=f"c_setup_{j}") for j in range(i, min(i+4, 17))]
        rows.append(row)
    return InlineKeyboardMarkup(rows)

def kb_atr():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Импульс (1.2)", callback_data="c_atr_1.2")],
        [InlineKeyboardButton("⚪ Норма (1.0)", callback_data="c_atr_1.0")],
        [InlineKeyboardButton("🔴 Флэт (0.7)", callback_data="c_atr_0.7")],
        [InlineKeyboardButton("🟣 Шок (0.5)", callback_data="c_atr_0.5")],
    ])

def kb_cf():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 Уверен (1.5)", callback_data="c_cf_1.5"),
         InlineKeyboardButton("✅ Норма (1.0)", callback_data="c_cf_1.0")],
        [InlineKeyboardButton("😐 Нейтрально (0.7)", callback_data="c_cf_0.7"),
         InlineKeyboardButton("😟 Сомневаюсь (0.5)", callback_data="c_cf_0.5")],
    ])

# ─── HANDLERS ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_member = await has_access(context.bot, user.id)
    first_time = user.id not in welcomed_users

    if is_member:
        # Стандартное приветствие
        await update.message.reply_text(
            f"Привет, {user.first_name}! 👋\n\n"
            "Я эксперт по Институциональной торговой стратегии @Funambul.\n\n"
            "Задавай вопросы по стратегии — объясню любой сетап, помогу с входом, разберу ситуацию на рынке.\n\n"
            "📎 /calculator — скачать Excel-файл с продвинутым риск-менеджментом\n"
            "📐 /calc — калькулятор прямо в боте\n"
            "🔄 /clear — очистить историю"
        )
    else:
        # Для новых пользователей — приветствие с подарком (только один раз)
        if first_time:
            welcomed_users.add(user.id)
            await update.message.reply_text(
                f"Привет, {user.first_name}! 👋\n\n"
                "🎁 *Держи подарок — Excel-файл с продвинутым риск-менеджментом*\n\n"
                "Внутри формула которая учитывает всё одновременно:\n"
                "— положение твоего счёта\n"
                "— реальный винрейт по сетапу\n"
                "— ментальное состояние\n"
                "— динамику последних сделок\n\n"
                "Чтобы получить файл — *подпишись на канал* и нажми /calculator\n\n"
                "Это бесплатно. Просто подпишись 👇",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📢 Подписаться на канал", url="https://t.me/SeiltanzerFX")
                ], [
                    InlineKeyboardButton("✅ Я подписался → получить файл", callback_data="get_calculator")
                ]])
            )
        else:
            # Повторный /start без подписки — короткое напоминание
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
        "Шаг 1/6: Введи текущий баланс \\(в $\\)\n_например: 48500_",
        parse_mode="MarkdownV2"
    )


async def handle_calc_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    uid = update.effective_user.id
    if uid not in calc_sessions:
        return False
    session = calc_sessions[uid]
    text = update.message.text.strip().replace(",", ".")
    step = session["step"]

    if step == "balance":
        try:
            val = float(text)
            if val <= 0: raise ValueError
            session["balance"] = val
            session["step"] = "initial"
            await update.message.reply_text(
                f"✅ Баланс: ${val:,.0f}\n\nШаг 2/6: Введи начальный депозит\n_например: 50000_",
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("⚠️ Введи число, например: 48500")
        return True

    elif step == "initial":
        try:
            val = float(text)
            if val <= 0: raise ValueError
            session["initial"] = val
            session["step"] = "phase"
            await update.message.reply_text(
                f"✅ Депозит: ${val:,.0f}\n\nШаг 3/6: Выбери фазу:",
                reply_markup=kb_phase()
            )
        except ValueError:
            await update.message.reply_text("⚠️ Введи число, например: 50000")
        return True

    elif step == "cycle":
        try:
            val = int(float(text))
            if val < 1: raise ValueError
            session["cycle_day"] = val
            session["step"] = "prev_profit"
            await update.message.reply_text(
                f"✅ День цикла: {val}\n\n"
                "Шаг 6/6: Прибыль от предыдущей сделки \\(в $\\)\n"
                "_Если не было — введи 0_",
                parse_mode="MarkdownV2"
            )
        except ValueError:
            await update.message.reply_text("⚠️ Введи число от 1 и выше")
        return True

    elif step == "prev_profit":
        try:
            val = float(text)
            session["prev_profit"] = max(0, val)
            session["step"] = None

            r = full_calculate(
                balance=session["balance"],
                initial=session["initial"],
                phase=session["phase"],
                setup=session["setup"],
                atr=session["atr"],
                cycle_day=session["cycle_day"],
                cf=session["cf"],
                prev_profit=session["prev_profit"],
            )
            del calc_sessions[uid]

            # Форматируем баланс правильно
            text_out = format_result(r).replace(
                f"${r['U']/r['T']*100*r['T']/r['T']:.0f}",
                f"${session['balance']:,.0f}"
            )
            await update.message.reply_text(text_out, parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("⚠️ Введи число (или 0)")
        return True

    return False


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    if not data.startswith("c_"):
        return
    if uid not in calc_sessions:
        return

    session = calc_sessions[uid]

    if data.startswith("c_phase_"):
        phase = data.replace("c_phase_", "")
        session["phase"] = phase
        session["step"] = "setup"
        phase_names = {"1ph": "Challenge", "2ph": "Verification", "funded": "Funded"}
        await query.message.reply_text(
            f"✅ Фаза: {phase_names[phase]}\n\nШаг 4/6: Выбери номер сетапа:",
            reply_markup=kb_setup()
        )

    elif data.startswith("c_setup_"):
        setup = int(data.replace("c_setup_", ""))
        session["setup"] = setup
        session["step"] = "atr"
        await query.message.reply_text(
            f"✅ Сетап №{setup}: {SETUP_NAMES[setup]}\n\nШаг 5/6: ATR-фаза рынка прямо сейчас?",
            reply_markup=kb_atr()
        )

    elif data.startswith("c_atr_"):
        atr = float(data.replace("c_atr_", ""))
        session["atr"] = atr
        session["step"] = "cf"
        await query.message.reply_text(
            f"✅ ATR: {ATR_LABELS[atr]}\n\nДополнительно: Твой текущий уровень уверенности?",
            reply_markup=kb_cf()
        )

    elif data.startswith("c_cf_"):
        cf = float(data.replace("c_cf_", ""))
        session["cf"] = cf
        session["step"] = "cycle"
        await query.message.reply_text(
            f"✅ CF: {cf}\n\nШаг 6/6: День цикла (1-13+)\n_Сколько дней прошло с начала текущего цикла? Обычно 1-13_",
            parse_mode="Markdown"
        )

    elif data == "get_calculator":
        # Проверяем подписку и отправляем файл
        if not await has_public_subscription(query.bot, uid):
            await query.answer("Сначала подпишись на канал!", show_alert=True)
            return
        calc_path = "calc_risk.xlsx"
        if not os.path.exists(calc_path):
            await query.message.reply_text("⚠️ Файл не найден. Обратись к администратору.")
            return
        await query.answer()
        with open(calc_path, "rb") as f:
            await query.message.reply_document(
                document=f,
                filename="Seiltanzer_Risk_Management.xlsx",
                caption=(
                    "📊 *Excel-файл с продвинутым риск-менеджментом*\n\n"
                    "Вводи свои данные — получай точный размер позиции "
                    "с учётом баланса, просадки, ATR и ментального состояния.\n\n"
                    "Команда /calc — тот же расчёт прямо в боте."
                ),
                parse_mode="Markdown"
            )
        import asyncio
        await asyncio.sleep(1)
        await query.message.reply_text(PROMO_TEXT, parse_mode="Markdown", reply_markup=PROMO_KB)


async def send_relevant_images(update: Update, combined_text: str):
    images = find_images(combined_text)
    sent = set()
    for img_path, caption in images:
        if img_path in sent: continue
        sent.add(img_path)
        if os.path.exists(img_path):
            try:
                with open(img_path, "rb") as f:
                    await update.message.reply_photo(photo=f, caption=f"📊 {caption}")
            except Exception as e:
                logger.warning(f"Не удалось отправить {img_path}: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not await has_access(context.bot, user.id):
        await update.message.reply_text(NO_ACCESS_MSG, parse_mode="HTML", reply_markup=NO_ACCESS_KB)
        return

    user_text = update.message.text
    if not user_text: return

    if await handle_calc_session(update, context):
        return

    # Триггер на запрос калькулятора / файла
    text_lower = user_text.lower()
    if any(kw in text_lower for kw in CALCULATOR_KEYWORDS):
        await send_calculator(update, context)
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
        await send_relevant_images(update, user_text + " " + reply)

    except Exception as e:
        logger.error(f"OpenRouter error: {e}")
        await update.message.reply_text("⚠️ Ошибка AI. Попробуй снова.")


PROMO_TEXT = (
    "📊 *Это лишь часть системы.*\n\n"
    "В полной стратегии @Funambul:\n\n"
    "📐 *16 институциональных алгоритмов* — индексы, металлы, форекс\n"
    "🧠 *Логика входов* через FVG, ликвидность, AMD и корреляции\n"
    "⚙️ *Риск-менеджмент* адаптированный под проп-фирмы и свой капитал\n"
    "🤖 *AI-бот 24/7* — отвечает на любые вопросы по стратегии\n"
    "📡 *Закрытый канал* с разборами сделок в реальном времени\n\n"
    "👇 Узнать подробнее:"
)

PROMO_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("🚀 Получить полную стратегию", url="https://t.me/tribute/app?startapp=sOg4")
]])

CALCULATOR_KEYWORDS = [
    "калькулятор", "excel", "таблиц", "xlsx", "скачать файл",
    "дай файл", "отправь файл", "хочу файл", "получить файл",
    "лид магнит", "бесплатно", "подарок", "скачать калькулятор"
]

async def send_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет Excel-файл с риск-менеджментом. Требует подписку на публичный канал."""
    uid = update.effective_user.id
    if not await has_public_subscription(context.bot, uid):
        await update.message.reply_text(
            "📢 Чтобы получить *Excel-файл с продвинутым риск-менеджментом* — подпишись на канал:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📢 Подписаться", url="https://t.me/SeiltanzerFX)
            ], [
                InlineKeyboardButton("✅ Я подписался → получить файл", callback_data="get_calculator")
            ]])
        )
        return

    calc_path = "calc_risk.xlsx"
    if not os.path.exists(calc_path):
        await update.message.reply_text("⚠️ Файл калькулятора не найден. Обратись к администратору.")
        return

    await update.message.reply_text("📎 Отправляю калькулятор риска...")
    with open(calc_path, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename="Seiltanzer_Risk_Calculator.xlsx",
            caption=(
                "📊 *Калькулятор риска по стратегии @Funambul*\n\n"
                "Вводи свои данные и получай точный размер позиции "
                "с учётом баланса, просадки, ATR и ментального состояния.\n\n"
                "Инструкция: команда /calc прямо в боте."
            ),
            parse_mode="Markdown"
        )

    # Пауза и реклама
    import asyncio
    await asyncio.sleep(1)
    await update.message.reply_text(PROMO_TEXT, parse_mode="Markdown", reply_markup=PROMO_KB)


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
    if ADMIN_IDS and update.effective_user.id not in ADMIN_IDS: return
    src = "strategy.docx" if os.path.exists("strategy.docx") else "strategy.txt" if os.path.exists("strategy.txt") else "❌"
    await update.message.reply_text(f"📊 {src}\nМодель: {MODEL}\nСимволов: {len(strategy_text)}")

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
    application.add_handler(CommandHandler("calculator", send_calculator))
    application.add_handler(CommandHandler("clear", clear))
    application.add_handler(CommandHandler("reload", reload_strategy))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    await application.initialize()
    await application.start()
    await application.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    logger.info(f"Webhook: {WEBHOOK_URL}/webhook")

    # Keep-alive: пингуем себя каждые 10 минут чтобы не засыпать на Render
    import asyncio
    async def keep_alive():
        while True:
            await asyncio.sleep(600)  # 10 минут
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.get(f"{WEBHOOK_URL}/")
                logger.info("Keep-alive ping sent")
            except Exception as e:
                logger.warning(f"Keep-alive failed: {e}")

    asyncio.create_task(keep_alive())

@app.on_event("shutdown")
async def shutdown():
    await application.stop()
    await application.shutdown()

if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=PORT)
