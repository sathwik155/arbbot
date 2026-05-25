#!/usr/bin/env python3
"""
Sports Arbitrage Calculator — Telegram Bot
==========================================
Setup:
  pip install python-telegram-bot==20.7

Run:
  BOT_TOKEN=your_token_here python arb_bot.py

Get a token: message @BotFather on Telegram → /newbot
"""

import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, ConversationHandler, filters
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Conversation states ────────────────────────────────────────────────────────
NUM_OUTCOMES, COLLECTING_ODDS, STAKE = range(3)

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_decimal(text: str) -> float | None:
    """Accept decimal, American (+150 / -120), or fractional (11/10) odds."""
    text = text.strip().replace(",", ".")
    try:
        # Fractional  e.g.  11/10
        if "/" in text:
            n, d = text.split("/", 1)
            return float(n) / float(d) + 1
        # American  e.g.  +150  or  -120
        if text.startswith("+") or (text.startswith("-") and not text[1:].replace(".", "").isdigit() is False):
            val = float(text)
            if val > 0:
                return val / 100 + 1
            elif val < 0:
                return 100 / abs(val) + 1
        # Decimal
        val = float(text)
        if val > 1:
            return val
        return None
    except (ValueError, ZeroDivisionError):
        return None


def calculate_arb(decimal_odds: list[float], stake: float) -> dict:
    implied = [1 / o for o in decimal_odds]
    arb_sum = sum(implied)
    is_arb = arb_sum < 1.0
    payout = stake / arb_sum
    profit = payout - stake
    profit_pct = (1 / arb_sum - 1) * 100
    stakes = [(stake * imp / arb_sum) for imp in implied]
    return {
        "is_arb": is_arb,
        "arb_sum": arb_sum,
        "profit": profit,
        "profit_pct": profit_pct,
        "payout": payout,
        "stakes": stakes,
        "margin_pct": (arb_sum - 1) * 100,
    }


def fmt_result(outcomes: list[dict], stake: float) -> str:
    decimal_odds = [o["odds"] for o in outcomes]
    r = calculate_arb(decimal_odds, stake)

    lines = []
    if r["is_arb"]:
        lines.append("✅ *Arbitrage opportunity found!*\n")
        lines.append(f"💰 Guaranteed profit: ₹{r['profit']:,.2f}")
        lines.append(f"📈 Profit %: {r['profit_pct']:.2f}%")
        lines.append(f"💵 Total payout: ₹{r['payout']:,.2f}")
        lines.append(f"📊 Implied total: {r['arb_sum']*100:.2f}%\n")
        lines.append("*Stake breakdown:*")
        for i, (o, s) in enumerate(zip(outcomes, r["stakes"]), 1):
            lines.append(
                f"  {i}. {o['name']} @ {o['odds']:.2f} → stake ₹{s:,.2f} → returns ₹{r['payout']:,.2f}"
            )
        lines.append("\n_Bet each stake above. You profit regardless of result._")
    else:
        lines.append("❌ *No arbitrage — bookmaker has the edge*\n")
        lines.append(f"📊 Implied total: {r['arb_sum']*100:.2f}% (needs to be <100%)")
        lines.append(f"📉 Bookmaker margin: {r['margin_pct']:.2f}%")
        lines.append(f"💸 Expected loss on ₹{stake:,.0f}: ₹{abs(r['profit']):,.2f}\n")
        lines.append("*Optimal stake split anyway:*")
        for i, (o, s) in enumerate(zip(outcomes, r["stakes"]), 1):
            lines.append(f"  {i}. {o['name']} @ {o['odds']:.2f} → ₹{s:,.2f}")
        lines.append(
            "\n_Try finding better odds on one or more outcomes to flip this into an arb._"
        )

    return "\n".join(lines)


# ── Command handlers ───────────────────────────────────────────────────────────

WELCOME = """
👋 *Welcome to ArbBot!*

I calculate sports arbitrage — guaranteed profit by backing all outcomes across different bookmakers.

*Commands:*
/arb — Start a new arbitrage calculation
/quick — Quick 2-way or 3-way arb check
/help — How arbitrage betting works
/example — See a worked example
"""

HELP_TEXT = """
📚 *How Arbitrage Betting Works*

Arbitrage (or "arb") betting exploits odds differences between bookmakers to guarantee a profit regardless of the match result.

*Example:*
• Bookmaker A: Team A wins @ 2.10
• Bookmaker B: Team B wins @ 2.05

Implied probabilities: 1/2.10 + 1/2.05 = 47.6% + 48.8% = *96.4%*

Since 96.4% < 100%, there's a 3.6% guaranteed profit margin.

*Key rules:*
1. The sum of implied probabilities must be < 100%
2. Place all bets simultaneously (odds change fast)
3. Bet with different bookmakers for each outcome
4. Use /arb to calculate your exact stakes

*Odds formats accepted:*
• Decimal: `2.10`
• American: `+110` or `-120`
• Fractional: `11/10`
"""

EXAMPLE_TEXT = """
📋 *Worked Example — Football Match*

*Outcome 1:* Team A wins
  Bookmaker: Bet365 @ 2.10

*Outcome 2:* Draw
  Bookmaker: 1xBet @ 3.50

*Outcome 3:* Team B wins
  Bookmaker: Betway @ 3.80

*Implied probabilities:*
  1/2.10 + 1/3.50 + 1/3.80
= 47.6% + 28.6% + 26.3%
= *102.5% ← no arb here*

Now swap Team B odds to 4.20:
  1/2.10 + 1/3.50 + 1/4.20
= 47.6% + 28.6% + 23.8%
= *100.0% ← break even*

At 4.30+:
  1/2.10 + 1/3.50 + 1/4.30
= 47.6% + 28.6% + 23.3%
= *99.4% ← 0.6% profit!*

Use /arb to try your own odds.
"""


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME, parse_mode="Markdown")


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def example_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(EXAMPLE_TEXT, parse_mode="Markdown")


# ── /arb conversation ──────────────────────────────────────────────────────────

async def arb_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("2 outcomes (tennis, basketball)", callback_data="n:2")],
        [InlineKeyboardButton("3 outcomes (football)", callback_data="n:3")],
        [InlineKeyboardButton("4 outcomes (custom)", callback_data="n:4")],
    ]
    await update.message.reply_text(
        "⚽ *New Arbitrage Calculation*\n\nHow many outcomes does this market have?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return NUM_OUTCOMES


async def num_outcomes_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    n = int(query.data.split(":")[1])
    ctx.user_data["num_outcomes"] = n
    ctx.user_data["outcomes"] = []
    ctx.user_data["current"] = 1

    await query.edit_message_text(
        f"✅ {n} outcomes selected.\n\n"
        f"*Outcome 1 of {n}*\nEnter the name (e.g. `Team A`, `Draw`, `Over 2.5`):",
        parse_mode="Markdown",
    )
    ctx.user_data["step"] = "name"
    return COLLECTING_ODDS


async def collect_odds(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    n = ctx.user_data["num_outcomes"]
    current = ctx.user_data["current"]
    step = ctx.user_data.get("step", "name")
    outcomes = ctx.user_data["outcomes"]

    if step == "name":
        ctx.user_data["current_name"] = text
        ctx.user_data["step"] = "odds"
        await update.message.reply_text(
            f"📊 *Outcome {current}: {text}*\n\n"
            f"Enter the odds (decimal `2.10`, American `+110`, or fractional `11/10`):",
            parse_mode="Markdown",
        )
        return COLLECTING_ODDS

    elif step == "odds":
        dec = parse_decimal(text)
        if dec is None or dec <= 1.0:
            await update.message.reply_text(
                "⚠️ Invalid odds. Please enter a valid decimal (>1.00), American (+110/-120), or fractional (11/10):"
            )
            return COLLECTING_ODDS

        outcomes.append({"name": ctx.user_data["current_name"], "odds": dec, "raw": text})
        ctx.user_data["outcomes"] = outcomes

        if current < n:
            ctx.user_data["current"] = current + 1
            ctx.user_data["step"] = "name"
            await update.message.reply_text(
                f"✅ Recorded.\n\n*Outcome {current + 1} of {n}*\nEnter the name:",
                parse_mode="Markdown",
            )
            return COLLECTING_ODDS
        else:
            # All outcomes collected — ask for stake
            ctx.user_data["step"] = "stake"
            summary = "\n".join(
                f"  {i+1}. {o['name']} @ {o['odds']:.2f}" for i, o in enumerate(outcomes)
            )
            await update.message.reply_text(
                f"✅ All outcomes collected:\n{summary}\n\n"
                f"💵 Enter your total stake in ₹ (e.g. `10000`):",
                parse_mode="Markdown",
            )
            return STAKE

    return COLLECTING_ODDS


async def get_stake(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace("₹", "").replace(",", "")
    try:
        stake = float(text)
        if stake <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Please enter a valid positive number for the stake:")
        return STAKE

    outcomes = ctx.user_data["outcomes"]
    result = fmt_result(outcomes, stake)

    keyboard = [
        [InlineKeyboardButton("🔄 New calculation", callback_data="restart")],
        [InlineKeyboardButton("📊 Change stake", callback_data="change_stake")],
    ]
    await update.message.reply_text(
        result,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    ctx.user_data["stake"] = stake
    return ConversationHandler.END


async def post_result_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "restart":
        await query.edit_message_reply_markup(None)
        await arb_start_from_callback(update, ctx)
    elif query.data == "change_stake":
        await query.edit_message_reply_markup(None)
        await query.message.reply_text("💵 Enter new total stake in ₹:")
        return STAKE


async def arb_start_from_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("2 outcomes", callback_data="n:2")],
        [InlineKeyboardButton("3 outcomes", callback_data="n:3")],
        [InlineKeyboardButton("4 outcomes", callback_data="n:4")],
    ]
    await update.callback_query.message.reply_text(
        "⚽ *New Arbitrage Calculation*\n\nHow many outcomes?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return NUM_OUTCOMES


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Calculation cancelled. Use /arb to start again.")
    return ConversationHandler.END


# ── /quick inline command ─────────────────────────────────────────────────────
# Usage: /quick 2.10 3.40 3.20 10000
#   or   /quick 2.10 2.05 5000

async def quick_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if len(args) < 3:
        await update.message.reply_text(
            "📌 *Quick arb check*\n\n"
            "Usage: `/quick <odds1> <odds2> [odds3 ...] <stake>`\n\n"
            "Example (2-way): `/quick 2.10 2.05 10000`\n"
            "Example (3-way): `/quick 2.10 3.40 3.20 10000`",
            parse_mode="Markdown",
        )
        return

    try:
        stake = float(args[-1].replace("₹", "").replace(",", ""))
        odds_raw = args[:-1]
    except ValueError:
        await update.message.reply_text("⚠️ Last argument must be the stake amount.")
        return

    outcomes = []
    for i, raw in enumerate(odds_raw, 1):
        dec = parse_decimal(raw)
        if dec is None or dec <= 1.0:
            await update.message.reply_text(f"⚠️ Invalid odds: `{raw}`", parse_mode="Markdown")
            return
        outcomes.append({"name": f"Outcome {i}", "odds": dec, "raw": raw})

    result = fmt_result(outcomes, stake)
    await update.message.reply_text(result, parse_mode="Markdown")


# ── Unknown messages ───────────────────────────────────────────────────────────

async def unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 I didn't understand that. Use /arb to start a calculation or /help for instructions."
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    token = 8407802983:AAEdZVXE9RFFe7QSgvve91UQNIlO3edYJJI
    if not token:
        raise RuntimeError("Set the BOT_TOKEN environment variable before running.")

    app = Application.builder().token(token).build()

    arb_conv = ConversationHandler(
        entry_points=[CommandHandler("arb", arb_start)],
        states={
            NUM_OUTCOMES: [CallbackQueryHandler(num_outcomes_cb, pattern=r"^n:\d$")],
            COLLECTING_ODDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_odds)],
            STAKE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stake)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("example", example_cmd))
    app.add_handler(CommandHandler("quick", quick_cmd))
    app.add_handler(arb_conv)
    app.add_handler(CallbackQueryHandler(post_result_cb, pattern=r"^(restart|change_stake)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))

    logger.info("ArbBot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
