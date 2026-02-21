"""
Маппинг сетапов и тем -> изображения из стратегии.

Ключевые принципы:
- Поиск ведётся по тексту ОТВЕТА нейросети (не только по вопросу)
- Точное совпадение через regex: "сетап 1" не срабатывает на "сетап 11"
- Более специфичные паттерны проверяются первыми
"""

import re

# Формат: (regex-паттерн, список файлов, подпись)
# Паттерны отсортированы от специфичных к общим — двузначные номера ПЕРВЫМИ!
IMAGE_RULES = [
    (
        r"сетап\s*(?:№\s*)?16|setup\s*(?:№\s*)?16|usdcad|usd\s*cad|канадский\s*доллар",
        ["images/setup16.png"],
        "Сетап №16: USDCAD — 8ч блок + 4ч подтверждение"
    ),
    (
        r"сетап\s*(?:№\s*)?15|setup\s*(?:№\s*)?15|eurusd\s*шорт|eurusd\s*short|евро\s*шорт",
        ["images/setup15.png"],
        "Сетап №15: EURUSD — дневной FVG + DXY 4ч (ШОРТ)"
    ),
    (
        r"сетап\s*(?:№\s*)?14|setup\s*(?:№\s*)?14|eurusd\s*лонг|eurusd\s*long|евро\s*лонг",
        ["images/setup14.png"],
        "Сетап №14: EURUSD — дневной FVG + DXY 4ч (ЛОНГ)"
    ),
    (
        r"сетап\s*(?:№\s*)?13|setup\s*(?:№\s*)?13|xag\b|серебро|silver|xagusd",
        ["images/setup13.png"],
        "Сетап №13: XAG — дневной FVG + AMD 1ч + Fib 0.5"
    ),
    (
        r"сетап\s*(?:№\s*)?12|setup\s*(?:№\s*)?12|xau.*12h.*sweep|золото.*12h.*sweep|xau.*sweep.*15м",
        ["images/setup12.png"],
        "Сетап №12: XAU — 12ч FVG sweep + возврат цены 15м"
    ),
    (
        r"сетап\s*(?:№\s*)?11|setup\s*(?:№\s*)?11|gvz|xau.*vix|золото.*vix.*gvz|xauusd.*vix",
        ["images/setup11.png"],
        "Сетап №11: XAU — 4ч VIX + GVZ корреляция"
    ),
    (
        r"сетап\s*(?:№\s*)?10|setup\s*(?:№\s*)?10|jpy100|jpy\s*100|японский\s*индекс",
        ["images/setup10.png"],
        "Сетап №10: JPY100 — дневной FVG + 4ч sweep"
    ),
    (
        r"сетап\s*(?:№\s*)?9\b|setup\s*(?:№\s*)?9\b|uk100|ftse",
        ["images/setup9.png"],
        "Сетап №9: UK100 — 12ч FVG + 2ч bFVGc"
    ),
    (
        r"сетап\s*(?:№\s*)?8\b|setup\s*(?:№\s*)?8\b|ger40.*90|90\s*(?:м|min|мин).*fvg|ger40.*2h.*bfvgc",
        ["images/setup8_a.png", "images/setup8_b.png"],
        "Сетап №8: GER40 — 12ч FVG + 90м FVG + 2ч bFVGc"
    ),
    (
        r"сетап\s*(?:№\s*)?7\b|setup\s*(?:№\s*)?7\b|ger40.*sweep|dax.*sweep|dv1x",
        ["images/setup7.png"],
        "Сетап №7: GER40 — 12ч FVG sweep + 1ч FVG"
    ),
    (
        r"сетап\s*(?:№\s*)?6\b|setup\s*(?:№\s*)?6\b|us30.*vix|dow\s*jones.*vix|us30.*8h.*fvg",
        ["images/setup6.png"],
        "Сетап №6: US30 — FVG 8ч + VIX > 20"
    ),
    (
        r"сетап\s*(?:№\s*)?5\b|setup\s*(?:№\s*)?5\b|sp500.*12h.*fvg|sp500.*vix.*20|vix.*sp500",
        ["images/setup5.png"],
        "Сетап №5: SP500 — ретест 12ч FVG + VIX > 20"
    ),
    (
        r"сетап\s*(?:№\s*)?4\b|setup\s*(?:№\s*)?4\b|корреляц.*sp500.*nas|sp500.*nas.*корреляц|1d\s*fvg.*sp500.*nas",
        ["images/setup4_a.png", "images/setup4_b.png"],
        "Сетап №4: SP500 + NAS100 — корреляция дневных FVG"
    ),
    (
        r"сетап\s*(?:№\s*)?3\b|setup\s*(?:№\s*)?3\b|bfvgc|build\s*fvg\s*candle|12h\s*fvg.*bfvg|12ч.*bfvgc",
        ["images/setup3_a.png", "images/setup3_b.png"],
        "Сетап №3: NAS100 — 12ч FVG + 4ч bFVGc"
    ),
    (
        r"сетап\s*(?:№\s*)?2\b|setup\s*(?:№\s*)?2\b|недельный\s*fvg|weekly\s*fvg|1w\s*fvg|0\.786.*недел",
        ["images/setup2.png"],
        "Сетап №2: NAS100 — AMD 1ч + недельный FVG 0.786"
    ),
    (
        r"сетап\s*(?:№\s*)?1\b|setup\s*(?:№\s*)?1\b|amd.*8h\s*fvg|8h\s*fvg.*amd|nas100.*amd.*возврат",
        ["images/setup1_a.png", "images/setup1_b.png"],
        "Сетап №1: NAS100 — AMD + возврат цены 1ч + тест FVG 8ч"
    ),
    # ── РИСК И ТЕОРИЯ ──
    (
        r"масштабир.*вход|scaled\s*entry|два\s*входа|три\s*входа|несколько\s*входов|разбивка\s*входов",
        ["images/scaled_entry.png"],
        "Система масштабированного входа (Глава 2.4)"
    ),
    (
        r"серия\s*стопов|losing\s*streak|проигрышная\s*серия|серия\s*убытков|сколько\s*стопов\s*подряд",
        ["images/losing_streak.png"],
        "Калькулятор серии стопов по винрейту (Глава 2.6)"
    ),
    (
        r"настройк.*теханализ|теханализ.*настройк|как\s*настроить\s*теханализ|technicals.*настройк",
        ["images/technicals_settings.png"],
        "Настройки индикатора Technicals (Глава 2.7)"
    ),
    (
        r"глобальный\s*фильтр|global\s*filter|теханализ.*-30|фильтр\s*индексов|индикатор\s*теханализ",
        ["images/global_filter.png"],
        "Глобальный фильтр для индексных сетапов (Глава 2.7)"
    ),
    (
        r"формула\s*(?:риска|калькулятора|позиции|расчёт)|коэффициент\s*роста\s*kr|kr\s*=",
        ["images/formula.jpg"],
        "Формула расчёта размера позиции (Глава 2)"
    ),
    (
        r"usdjpy|usd\s*jpy|доллар.*йена|йена.*доллар",
        ["images/setup_usdjpy.png"],
        "USDJPY — 12ч FVG + 2ч bFVGc (в разработке)"
    ),
]


def find_images(text: str) -> list:
    """
    Ищет изображения по тексту.
    Возвращает список (путь, подпись), максимум 2 изображения.
    """
    text_lower = text.lower()
    results = []
    seen = set()

    for pattern, image_files, caption in IMAGE_RULES:
        if re.search(pattern, text_lower):
            if caption not in seen:
                for img_path in image_files[:2]:
                    results.append((img_path, caption))
                seen.add(caption)
            if len(results) >= 2:
                break

    return results[:2]
