"""
Полная репликация логики калькулятора риска из Excel.

Формулы взяты напрямую из ячеек:
F=Balance%, G=R, K=W(winrate), L=D(drawdown), M=W/(1+D),
J=RR, N=KR, O=CF, P=T%, Q=P_max, R=risk_adj,
S=efficiency, T=S%(final risk), U=S$, V=entries,
Y=k_buffer, Z=k_cycle, AA=fix_rule, AB=recovery_trades
"""

import math


# Винрейт по номеру сетапа (из формулы K9)
SETUP_WINRATES = {
    1: 0.85, 2: 0.87, 3: 0.68, 4: 0.71,
    5: 0.72, 6: 0.87, 7: 0.70, 8: 0.70,
    9: 0.81, 10: 0.59, 11: 0.77, 12: 0.71,
    13: 0.85, 14: 0.72, 15: 0.71, 16: 0.82,
}

SETUP_NAMES = {
    1:  "NAS100 — AMD + 8H FVG",
    2:  "NAS100 — AMD + Weekly FVG 0.786",
    3:  "NAS100 — 12H FVG + 4H bFVGc",
    4:  "SP500 + NAS100 — корреляция 1D FVG",
    5:  "SP500 — 12H FVG + VIX > 20",
    6:  "US30 — 8H FVG + VIX > 20",
    7:  "GER40 — 12H FVG sweep + 1H FVG",
    8:  "GER40 — 12H FVG + 90м FVG + 2H bFVGc",
    9:  "UK100 — 12H FVG + 2H bFVGc",
    10: "JPY100 — 1D FVG + 4H sweep",
    11: "XAU — VIX + GVZ корреляция",
    12: "XAU — 12H FVG sweep + 15м",
    13: "XAG — 1D FVG + AMD + Fib 0.5",
    14: "EURUSD — 1D FVG + DXY (ЛОНГ)",
    15: "EURUSD — 1D FVG + DXY (ШОРТ)",
    16: "USDCAD — 8H блок + 4H подтверждение",
}

ATR_LABELS = {
    0.5: "🟣 Шок (экстрем. волатильность)",
    0.7: "🔴 Флэт (низкая активность)",
    1.0: "⚪ Норма",
    1.2: "🟢 Импульс (высокая активность)",
}


def calc_F(balance: float, initial: float) -> float:
    """F = Balance%"""
    return balance / initial * 100


def calc_G(F: float, phase: str) -> float:
    """G = R (базовый риск) — формула из G9"""
    if F < 93:      base = 1.25
    elif F > 107:   base = 1.50
    elif F >= 105:  base = 1.75
    elif F >= 102:  base = 2.00
    elif F >= 100:  base = 2.20
    elif F >= 97:   base = 2.00
    elif F >= 95:   base = 1.75
    else:           base = 1.50

    bonus = 2.0 if phase == "1ph" else (1.0 if phase == "2ph" else 0.0)
    return base + bonus


def calc_K(setup: int) -> float:
    """K = W (винрейт сетапа)"""
    return SETUP_WINRATES.get(setup, 0.75)


def calc_L(balance: float, initial: float) -> float:
    """L = D (коэффициент просадки) — формула из L9"""
    if balance > initial:
        return 0.0
    return (1 - balance / initial) * 10


def calc_J(F: float, X: float) -> float:
    """J = RR (риск-ревард) — формула из J9"""
    if F > 107:     base_rr = 1.25
    elif F >= 105:  base_rr = 1.50
    elif F >= 102:  base_rr = 2.00
    elif F >= 100:  base_rr = 1.75
    elif F >= 97:   base_rr = 1.50
    elif F >= 95:   base_rr = 2.20
    elif F >= 93:   base_rr = 2.50
    else:           base_rr = 3.00

    atr_mult = 0.6 if X == 0.5 else (0.8 if X == 0.7 else (1.2 if X == 1.2 else 1.0))
    return base_rr * atr_mult


def calc_Y(F: float) -> float:
    """Y = k-буфер — формула из Y9"""
    if F < 97:      return 1.2
    elif F <= 100.5: return 0.6
    else:           return 1.0


def calc_Z(F: float, W_cycle: int) -> float:
    """Z = k-цикл — формула из Z9"""
    if F < 93:
        return 1.0
    if W_cycle <= 5:
        return 1.2 if F > 102 else 1.0
    if W_cycle <= 10:
        return 1.1 if F < 100 else 0.5
    if W_cycle <= 13:
        if F < 97:   return 1.2
        if F < 100:  return 1.5
        if F > 102:  return 0.1
        return 0.5
    return 1.0 if F < 100 else 0.0


def calc_R(F: float, L: float, Q: float = 10.0) -> float:
    """R = коэффициент риск-адаптации — формула из R9"""
    P = L * 10  # текущая просадка %
    ratio = 1 - (P / Q) if Q > 0 else 1.0
    if F > 96:
        return max(0.0, ratio)
    else:
        return max(0.0, math.sqrt(max(0.0, ratio)))


def calc_T(G, M, N, O, R, S, Y, Z, X, balance, prev_profit=0.0) -> float:
    """T = S% (итоговый риск) — формула из T9"""
    base = G * M * N * O * R * S * Y * Z * X
    bonus = (prev_profit * 0.4 / balance * 100) if prev_profit > 0 else 0.0
    return min(2.9, base + bonus)


def calc_recovery_trades(F: float, K: float, T: float, J: float) -> str:
    """AB = сделок до выхода из просадки — формула из AB9"""
    if F >= 100:
        return "DONE ✅"
    prefix = "RECOVERY: " if F < 98 else ""
    try:
        win_part = K * math.log(1 + (T / 100 * J * 0.82))
        loss_part = (1 - K) * math.log(max(0.00001, 1 - (T / 100 * 1.05)))
        denom = max(0.00001, win_part + loss_part)
        trades = math.ceil(math.log(100 / F) / denom * 10) / 10
        return f"{prefix}{trades:.1f}"
    except Exception:
        return f"{prefix}N/A"


def full_calculate(
    balance: float,
    initial: float,
    phase: str,
    setup: int,
    atr: float = 1.0,
    cycle_day: int = 1,
    cf: float = 1.0,
    kr: float = 1.0,
    efficiency: float = 1.0,
    prev_profit: float = 0.0,
) -> dict:
    """
    Полный расчёт по всем формулам калькулятора.
    """
    F = calc_F(balance, initial)
    G = calc_G(F, phase)
    K = calc_K(setup)
    L = calc_L(balance, initial)
    M = K / (1 + L)
    J = calc_J(F, atr)
    Y = calc_Y(F)
    Z = calc_Z(F, cycle_day)
    R = calc_R(F, L)
    S = efficiency       # 2α/(α+β)
    N = kr               # KR коэффициент роста
    O = cf               # CF уверенность
    X = atr              # ATR фактор
    T = calc_T(G, M, N, O, R, S, Y, Z, X, balance, prev_profit)
    U = initial * T / 100
    V = 1 if T <= 0.8 else 2
    fix_rule = "Шаг 0.5 RR (1.0→1.5→2.0)" if F < 94 else "Шаг 0.25 RR (1.0→1.25→1.5)"
    recovery = calc_recovery_trades(F, K, T, J)
    recovery_mode = F < 100

    # Распределение входов
    if V == 1:
        distribution = f"Один вход: ${U:.2f}"
    else:
        part = U / 3
        distribution = f"Вход №1: ${part:.2f}\nВход №2: ${part:.2f}\nРезерв:  ${part:.2f} (не используется)"

    return {
        "F": round(F, 2),
        "G": round(G, 3),
        "K": round(K, 3),
        "L": round(L, 3),
        "M": round(M, 4),
        "J": round(J, 2),
        "Y": round(Y, 2),
        "Z": round(Z, 2),
        "R": round(R, 4),
        "T": round(T, 4),
        "U": round(U, 2),
        "V": V,
        "setup": setup,
        "setup_name": SETUP_NAMES.get(setup, ""),
        "phase": phase,
        "atr": atr,
        "atr_label": ATR_LABELS.get(atr, ""),
        "cycle_day": cycle_day,
        "fix_rule": fix_rule,
        "recovery": recovery,
        "recovery_mode": recovery_mode,
        "distribution": distribution,
    }


def format_result(r: dict) -> str:
    phase_names = {"1ph": "Challenge (1ph)", "2ph": "Verification (2ph)", "funded": "Funded"}
    status = "🔴 RECOVERY" if r["recovery_mode"] else "🟢 Норма"

    return (
        f"📊 *Расчёт риска по стратегии*\n"
        f"{'─'*30}\n"
        f"💰 Баланс: ${r['U']/r['T']*100*r['T']/r['T']:.0f} → {r['F']}% от депозита\n"
        f"📋 Фаза: {phase_names.get(r['phase'], r['phase'])} | {status}\n"
        f"🎯 Сетап №{r['setup']}: {r['setup_name']}\n"
        f"📡 ATR: {r['atr_label']}\n"
        f"{'─'*30}\n"
        f"⚙️ *Коэффициенты:*\n"
        f"  R (база): {r['G']:.2f}% | W (винрейт): {r['K']:.0%}\n"
        f"  k-буфер: {r['Y']} | k-цикл: {r['Z']} | RR цель: {r['J']}\n"
        f"{'─'*30}\n"
        f"✅ *Итоговый риск: {r['T']:.2f}% = ${r['U']:.2f}*\n"
        f"🚪 Входов: *{r['V']}*\n"
        f"{'─'*30}\n"
        f"📐 *Распределение:*\n{r['distribution']}\n"
        f"{'─'*30}\n"
        f"📌 Фиксация прибыли: {r['fix_rule']}\n"
        f"🔄 До выхода из просадки: {r['recovery']}"
    )
