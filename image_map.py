"""
Маппинг ключевых слов → изображения из стратегии.
Бот автоматически отправляет нужное изображение когда пользователь спрашивает
о конкретном сетапе или теме.
"""

# Каждый элемент: (список ключевых слов, список файлов изображений, подпись)
IMAGE_MAP = [
    (
        ["сетап 1", "сетап №1", "setup 1", "setup №1", "nas100 amd 8h", "amd 8h fvg", "amd возврат 1ч"],
        ["images/setup1_a.png", "images/setup1_b.png"],
        "Сетап №1: NAS100 — AMD + возврат цены 1ч + тест FVG 8ч"
    ),
    (
        ["сетап 2", "сетап №2", "setup 2", "setup №2", "недельный fvg", "weekly fvg", "0.786 недельн"],
        ["images/setup2.png"],
        "Сетап №2: NAS100 — AMD 1ч + недельный FVG 0.786"
    ),
    (
        ["сетап 3", "сетап №3", "setup 3", "setup №3", "12h fvg bfvgc", "bfvgc", "build fvg candle", "12ч fvg"],
        ["images/setup3_a.png", "images/setup3_b.png"],
        "Сетап №3: NAS100 — 12ч FVG + 4ч bFVGc"
    ),
    (
        ["сетап 4", "сетап №4", "setup 4", "setup №4", "корреляция sp500 nas", "sp500 nas корреляция", "дневной fvg корреляция", "1d fvg nas sp"],
        ["images/setup4_a.png", "images/setup4_b.png"],
        "Сетап №4: SP500 + NAS100 — корреляция дневных FVG"
    ),
    (
        ["сетап 5", "сетап №5", "setup 5", "setup №5", "sp500 vix", "sp500 12h fvg vix", "vix 20 sp"],
        ["images/setup5.png"],
        "Сетап №5: SP500 — ретест 12ч FVG + VIX > 20"
    ),
    (
        ["сетап 6", "сетап №6", "setup 6", "setup №6", "us30 vix", "us30 fvg 8ч", "dow jones vix"],
        ["images/setup6.png"],
        "Сетап №6: US30 — FVG 8ч + VIX > 20"
    ),
    (
        ["сетап 7", "сетап №7", "setup 7", "setup №7", "ger40 sweep", "dax sweep", "dv1x", "ger40 12h fvg"],
        ["images/setup7.png"],
        "Сетап №7: GER40 — 12ч FVG sweep + 1ч FVG"
    ),
    (
        ["сетап 8", "сетап №8", "setup 8", "setup №8", "ger40 90м", "ger40 2h bfvgc", "dax bfvgc", "90min fvg"],
        ["images/setup8_a.png", "images/setup8_b.png"],
        "Сетап №8: GER40 — 12ч FVG + 90м FVG + 2ч bFVGc"
    ),
    (
        ["сетап 9", "сетап №9", "setup 9", "setup №9", "uk100", "ftse", "ftse 100"],
        ["images/setup9.png"],
        "Сетап №9: UK100 — 12ч FVG + 2ч bFVGc"
    ),
    (
        ["сетап 10", "сетап №10", "setup 10", "setup №10", "jpy100", "jpy 100", "японский индекс"],
        ["images/setup10.png"],
        "Сетап №10: JPY100 — дневной FVG + 4ч sweep"
    ),
    (
        ["сетап 11", "сетап №11", "setup 11", "setup №11", "xau vix gvz", "золото vix gvz", "gvz корреляция", "xauusd vix"],
        ["images/setup11.png"],
        "Сетап №11: XAU — 4ч VIX + GVZ корреляция"
    ),
    (
        ["сетап 12", "сетап №12", "setup 12", "setup №12", "xau 12h fvg sweep", "золото 12h sweep", "xau sweep 12"],
        ["images/setup12.png"],
        "Сетап №12: XAU — 12ч FVG sweep + возврат цены 15м"
    ),
    (
        ["сетап 13", "сетап №13", "setup 13", "setup №13", "xag", "серебро", "silver", "xagusd"],
        ["images/setup13.png"],
        "Сетап №13: XAG — дневной FVG + AMD 1ч + Fib 0.5"
    ),
    (
        ["сетап 14", "сетап №14", "setup 14", "setup №14", "eurusd long dxy", "eurusd лонг", "евро лонг dxy"],
        ["images/setup14.png"],
        "Сетап №14: EURUSD — дневной FVG + DXY 4ч (ЛОНГ)"
    ),
    (
        ["сетап 15", "сетап №15", "setup 15", "setup №15", "eurusd short dxy", "eurusd шорт", "евро шорт dxy"],
        ["images/setup15.png"],
        "Сетап №15: EURUSD — дневной FVG + DXY 4ч (ШОРТ)"
    ),
    (
        ["сетап 16", "сетап №16", "setup 16", "setup №16", "usdcad", "usd cad", "канадский доллар"],
        ["images/setup16.png"],
        "Сетап №16: USDCAD — 8ч блок + 4ч подтверждение"
    ),
    (
        ["usdjpy", "usd jpy", "йена доллар", "сетап в разработке usdjpy"],
        ["images/setup_usdjpy.png"],
        "USDJPY — 12ч FVG + 2ч bFVGc (в разработке)"
    ),
    (
        ["масштабированный вход", "2 входа", "3 входа", "scaled entry", "несколько входов", "разбивка входов"],
        ["images/scaled_entry.png"],
        "Система масштабированного входа (Глава 2.4)"
    ),
    (
        ["серия стопов", "losing streak", "проигрышная серия", "максимальная серия убытков", "калькулятор стопов"],
        ["images/losing_streak.png"],
        "Калькулятор серии стопов по винрейту (Глава 2.6)"
    ),
    (
        ["теханализ настройки", "technicals настройка", "настройки индикатора теханализ", "как настроить теханализ"],
        ["images/technicals_settings.png"],
        "Настройки индикатора Technicals (Глава 2.7)"
    ),
    (
        ["глобальный фильтр", "global filter", "теханализ -30", "фильтр индексов", "индикатор теханализ nas"],
        ["images/global_filter.png"],
        "Глобальный фильтр для индексных сетапов (Глава 2.7)"
    ),
    (
        ["формула риска", "формула калькулятора", "s r w d cf", "коэффициент роста kr", "формула позиции"],
        ["images/formula.jpg"],
        "Формула расчёта размера позиции (Глава 2)"
    ),
]


def find_images_for_query(user_text: str) -> list[tuple[str, str]]:
    """
    Ищет подходящие изображения для запроса пользователя.
    Возвращает список (путь_к_файлу, подпись).
    Максимум 2 изображения чтобы не перегружать чат.
    """
    text_lower = user_text.lower()
    results = []

    for keywords, image_files, caption in IMAGE_MAP:
        for kw in keywords:
            if kw in text_lower:
                # Берём первые 2 изображения из списка
                for img_path in image_files[:2]:
                    results.append((img_path, caption))
                break  # одно совпадение на группу достаточно

        if len(results) >= 2:
            break

    return results[:2]
