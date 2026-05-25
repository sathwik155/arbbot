#!/usr/bin/env python3
"""
ArbBot Pro — Interactive Sports Arbitrage Telegram Bot
======================================================
pip install python-telegram-bot==20.7
BOT_TOKEN=your_token python main.py
"""

import os
import random
import logging
from datetime import datetime
from collections import defaultdict
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, ConversationHandler, filters
)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# States
SPORT_SELECT, MARKET_SELECT, COLLECTING_ODDS, GET_STAKE = range(4)

# In-memory stats per user
user_stats = defaultdict(lambda: {
    "calcs": 0, "arbs_found": 0,
    "total_profit": 0.0, "joined": str(datetime.now().date())
})

SPORTS = {
    "Football": {
        "emoji": "⚽",
        "markets": ["1X2 (Home/Draw/Away)", "Both Teams to Score", "Over/Under Goals", "Custom"],
        "outcomes": {
            "1X2 (Home/Draw/Away)": ["Home Win", "Draw", "Away Win"],
            "Both Teams to Score": ["Yes", "No"],
            "Over/Under Goals": ["Over 2.5", "Under 2.5"],
            "Custom": None
        }
    },
    "Tennis": {
        "emoji": "🎾",
        "markets": ["Match Winner", "Custom"],
        "outcomes": {
            "Match Winner": ["Player 1", "Player 2"],
            "Custom": None
        }
    },
    "Cricket": {
        "emoji": "🏏",
        "markets": ["Match Winner", "Over/Under Runs", "Custom"],
        "outcomes": {
            "Match Winner": ["Team A", "Team B", "Draw/No Result"],
            "Over/Under Runs": ["Over", "Under"],
            "Custom": None
        }
    },
    "Basketball": {
        "emoji": "🏀",
        "markets": ["Match Winner", "Over/Under Points", "Custom"],
        "outcomes": {
            "Match Winner": ["Home", "Away"],
            "Over/Under Points": ["Over 210.5", "Under 210.5"],
            "Custom": None
        }
    },
    "Other": {
        "emoji": "🏆",
        "markets": ["2-Way Market", "3-Way Market", "4-Way Market"],
        "outcomes": {
            "2-Way Market": ["Outcome 1", "Outcome 2"],
            "3-Way Market": ["Outcome 1", "Outcome 2", "Outcome 3"],
            "4-Way Market": ["Outcome 1", "Outcome 2", "Outcome 3", "Outcome 4"]
        }
    }
}

BOOKMAKERS = ["Bet365", "1xBet", "Betway", "Parimatch", "10Cric", "Dafabet", "Other"]

TIPS = [
    "Cricket T20 matches have great arb opportunities — odds shift a lot between bookmakers!",
    "Have all bookmaker accounts open in separate tabs before placing arb bets.",
    "Focus on arbs above 1.5% — smaller margins can disappear after withdrawal fees.",
    "The best time to find arbs is 30-60 minutes before a match starts.",
    "Keep your bookmaker balances topped up so you can act instantly when an arb appears.",
    "Always place all bets simultaneously — if one leg fails, you lose the guarantee.",
    "IPL matches often show 2-3% arb margins between Indian and international bookmakers.",
]


def parse_odds(text: str):
    text = text.strip().replace(",", ".")
    try:
        if "/" in text and not text.startswith(("+", "-")):
            n, d = text.split("/", 1)
            return float(n) / float(d) + 1
        val = float(text)
        if text.startswith("+") or val < -1:
            if val > 0:
                return val / 100 + 1
            if val < 0:
                return 100 / abs(val) + 1
        if val > 1:
            return val
        return None
    except (ValueError, ZeroDivisionError):
        return None


def calc_arb(odds_list, stake):
    implied = [1 / o for o in odds_list]
    total = sum(implied)
    payout = stake / total
    return {
        "is_arb": total < 1.0,
        "total": total,
        "profit": payout - stake,
        "profit_pct": (1 / total - 1) * 100,
        "payout": payout,
        "stakes": [stake * i / total for i in implied],
        "margin": (total - 1) * 100
    }


def progress_bar(current, total):
    filled = int((current / total) * 8)
    return "▓" * filled + "░" * (8 - filled)


def odds_quality(dec):
    if dec >= 3.0: return "🟢"
    if dec >= 2.0: return "🟡"
    if dec >= 1.5: return "🟠"
    return "🔴"


def main_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🧮 New Calculation"), KeyboardButton("⚡ Quick Check")],
        [KeyboardButton("📊 My Stats"), KeyboardButton("📚 Learn Arb")],
        [KeyboardButton("💡 Daily Tip"), KeyboardButton("ℹ️ Help")]
    ], resize_keyboard=True)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "there"
    await update.message.reply_text(
        f"👋 *Welcome, {name}!*\n\n"
        "I'm *ArbBot Pro* — your sports arbitrage calculator.\n\n"
        "I find *guaranteed profit* by calculating optimal stakes across bookmakers.\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🎯 *What I can do:*\n"
        "• Guided calculations for Football, Cricket, Tennis & more\n"
        "• Show exact stake amounts per bookmaker\n"
        "• Accept Decimal, American & Fractional odds\n"
        "• Track your arb history & profit\n\n"
        "👇 *Tap a button to get started!*",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


async def new_calc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    keyboard = [
        [InlineKeyboardButton(
            f"{v['emoji']} {k}",
            callback_data=f"sport:{k}"
        )] for k, v in SPORTS.items()
    ]
    await update.message.reply_text(
        "🏆 *Step 1 of 3 — Select Sport*\n\n"
        "Which sport are you betting on?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SPORT_SELECT


async def sport_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sport = query.data.replace("sport:", "")
    ctx.user_data["sport"] = sport
    emoji = SPORTS[sport]["emoji"]
    markets = SPORTS[sport]["markets"]
    keyboard = [
        [InlineKeyboardButton(m, callback_data=f"market:{m}")] for m in markets
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back:sport")])
    await query.edit_message_text(
        f"{emoji} *{sport} — Step 2 of 3*\n\n"
        "📋 What type of market is this?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return MARKET_SELECT


async def market_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "back:sport":
        keyboard = [
            [InlineKeyboardButton(f"{v['emoji']} {k}", callback_data=f"sport:{k}")]
            for k, v in SPORTS.items()
        ]
        await query.edit_message_text(
            "🏆 *Step 1 of 3 — Select Sport*\n\nWhich sport?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SPORT_SELECT

    market = query.data.replace("market:", "")
    sport = ctx.user_data["sport"]
    ctx.user_data["market"] = market
    preset = SPORTS[sport]["outcomes"].get(market)

    if preset and market != "Custom":
        ctx.user_data["outcomes"] = [
            {"name": o, "odds": None, "bookmaker": None} for o in preset
        ]
        ctx.user_data["total"] = len(preset)
        ctx.user_data["current"] = 0
        ctx.user_data["step"] = "bookmaker"
        await query.edit_message_text(
            f"✅ *{sport} — {market}*\n\n"
            f"Now let's collect odds for each outcome.\n"
            f"I'll ask you one by one 👇",
            parse_mode="Markdown"
        )
        await ask_next_msg(query.message, ctx)
        return COLLECTING_ODDS
    else:
        keyboard = [
            [InlineKeyboardButton("2 outcomes", callback_data="custom:2"),
             InlineKeyboardButton("3 outcomes", callback_data="custom:3")],
            [InlineKeyboardButton("4 outcomes", callback_data="custom:4")]
        ]
        await query.edit_message_text(
            f"✅ *{sport} — Custom Market*\n\n🔢 How many outcomes?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return MARKET_SELECT


async def custom_outcomes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    n = int(query.data.replace("custom:", ""))
    ctx.user_data["outcomes"] = [
        {"name": f"Outcome {i+1}", "odds": None, "bookmaker": None} for i in range(n)
    ]
    ctx.user_data["total"] = n
    ctx.user_data["current"] = 0
    ctx.user_data["step"] = "name"
    await query.edit_message_text(
        f"✅ {n} outcomes selected.\n\nLet's name each outcome 👇",
        parse_mode="Markdown"
    )
    await ask_next_msg(query.message, ctx)
    return COLLECTING_ODDS


async def ask_next_msg(message, ctx):
    current = ctx.user_data["current"]
    total = ctx.user_data["total"]
    outcomes = ctx.user_data["outcomes"]
    step = ctx.user_data.get("step", "bookmaker")
    o = outcomes[current]
    bar = progress_bar(current, total)

    if step == "name":
        await message.reply_text(
            f"✏️ *Outcome {current+1} of {total}*\n"
            f"Progress: {bar}\n\n"
            f"Enter a name for this outcome:\n"
            f"_e.g. Team A, Draw, Over 2.5_",
            parse_mode="Markdown"
        )

    elif step == "bookmaker":
        keyboard = [
            [InlineKeyboardButton(b, callback_data=f"bm:{b}")] for b in BOOKMAKERS
        ]
        await message.reply_text(
            f"🏦 *Outcome {current+1} of {total}: {o['name']}*\n"
            f"Progress: {bar}\n\n"
            f"Which bookmaker has the best odds for this?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif step == "odds":
        await message.reply_text(
            f"📊 *Enter Odds — {o['name']}*\n"
            f"🏦 Bookmaker: *{o['bookmaker']}*\n"
            f"Progress: {bar}\n\n"
            f"Type the odds:\n"
            f"• Decimal: `2.10`\n"
            f"• American: `+110` or `-120`\n"
            f"• Fractional: `11/10`",
            parse_mode="Markdown"
        )


async def bookmaker_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bm = query.data.replace("bm:", "")
    current = ctx.user_data["current"]
    ctx.user_data["outcomes"][current]["bookmaker"] = bm
    ctx.user_data["step"] = "odds"
    await query.edit_message_reply_markup(None)
    await ask_next_msg(query.message, ctx)
    return COLLECTING_ODDS


async def collect_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    current = ctx.user_data["current"]
    total = ctx.user_data["total"]
    step = ctx.user_data.get("step", "bookmaker")
    outcomes = ctx.user_data["outcomes"]

    if step == "name":
        outcomes[current]["name"] = text
        ctx.user_data["step"] = "bookmaker"
        await ask_next_msg(update.message, ctx)
        return COLLECTING_ODDS

    elif step == "odds":
        dec = parse_odds(text)
        if not dec or dec <= 1.0:
            await update.message.reply_text(
                "⚠️ *Invalid odds!*\n\n"
                "Examples of valid odds:\n"
                "• Decimal: `2.10`\n"
                "• American: `+110` or `-120`\n"
                "• Fractional: `11/10`\n\n"
                "Please try again:",
                parse_mode="Markdown"
            )
            return COLLECTING_ODDS

        outcomes[current]["odds"] = dec
        outcomes[current]["raw"] = text
        q = odds_quality(dec)

        await update.message.reply_text(
            f"✅ *Saved!* {q}\n"
            f"_{outcomes[current]['name']}_ @ *{dec:.2f}* via {outcomes[current]['bookmaker']}",
            parse_mode="Markdown"
        )

        ctx.user_data["current"] = current + 1

        if current + 1 < total:
            ctx.user_data["step"] = "bookmaker"
            await ask_next_msg(update.message, ctx)
            return COLLECTING_ODDS
        else:
            return await show_stake_prompt(update.message, ctx)

    return COLLECTING_ODDS


async def show_stake_prompt(message, ctx):
    outcomes = ctx.user_data["outcomes"]
    lines = ["📋 *All odds collected:*\n"]
    for i, o in enumerate(outcomes, 1):
        q = odds_quality(o["odds"])
        lines.append(f"{i}. *{o['name']}* {q} @ {o['odds']:.2f} — {o['bookmaker']}")

    implied = sum(1 / o["odds"] for o in outcomes)
    if implied < 1.0:
        lines.append(f"\n🟢 *Potential arb! ({implied*100:.2f}%)*")
    else:
        lines.append(f"\n🔴 Implied total: {implied*100:.2f}% (need <100%)")

    lines.append("\n💵 *How much do you want to stake?*\n_Or type a custom amount_")

    keyboard = [
        [InlineKeyboardButton("₹1,000", callback_data="stake:1000"),
         InlineKeyboardButton("₹5,000", callback_data="stake:5000"),
         InlineKeyboardButton("₹10,000", callback_data="stake:10000")],
        [InlineKeyboardButton("₹25,000", callback_data="stake:25000"),
         InlineKeyboardButton("₹50,000", callback_data="stake:50000"),
         InlineKeyboardButton("₹1,00,000", callback_data="stake:100000")]
    ]
    await message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return GET_STAKE


async def stake_button_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    stake = float(query.data.replace("stake:", ""))
    await query.edit_message_reply_markup(None)
    await show_result(query.message, ctx, stake, update.effective_user.id)
    return ConversationHandler.END


async def stake_text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace("₹", "").replace(",", "")
    try:
        stake = float(text)
        if stake <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "⚠️ Please enter a valid amount, e.g. `10000`",
            parse_mode="Markdown"
        )
        return GET_STAKE
    await show_result(update.message, ctx, stake, update.effective_user.id)
    return ConversationHandler.END


async def show_result(message, ctx, stake, user_id):
    outcomes = ctx.user_data["outcomes"]
    sport = ctx.user_data.get("sport", "")
    market = ctx.user_data.get("market", "")
    odds_list = [o["odds"] for o in outcomes]
    r = calc_arb(odds_list, stake)

    user_stats[user_id]["calcs"] += 1
    if r["is_arb"]:
        user_stats[user_id]["arbs_found"] += 1
        user_stats[user_id]["total_profit"] += r["profit"]

    lines = []
    if r["is_arb"]:
        lines.append("🎉 *ARB OPPORTUNITY FOUND!*")
        lines.append("━━━━━━━━━━━━━━━━\n")
        lines.append(f"🏆 {sport} — {market}")
        lines.append(f"💰 Guaranteed Profit: *₹{r['profit']:,.2f}*")
        lines.append(f"📈 Profit Rate: *{r['profit_pct']:.2f}%*")
        lines.append(f"💵 Total Payout: ₹{r['payout']:,.2f}")
        lines.append(f"📊 Implied Total: {r['total']*100:.2f}%")
        lines.append("\n━━━━━━━━━━━━━━━━")
        lines.append("📌 *Your Betting Plan:*\n")
        for i, (o, s) in enumerate(zip(outcomes, r["stakes"]), 1):
            lines.append(f"*Bet {i}: {o['name']}*")
            lines.append(f"  🏦 Bookmaker: {o['bookmaker']}")
            lines.append(f"  📊 Odds: {o['odds']:.2f}")
            lines.append(f"  💵 Stake: *₹{s:,.2f}*")
            lines.append(f"  💰 Return: ₹{r['payout']:,.2f}\n")
        lines.append("━━━━━━━━━━━━━━━━")
        lines.append("⚡ *Place all bets at the same time!*")
        lines.append("_Odds can change — act quickly._")
    else:
        lines.append("❌ *No Arbitrage Found*")
        lines.append("━━━━━━━━━━━━━━━━\n")
        lines.append(f"🏆 {sport} — {market}")
        lines.append(f"📊 Implied Total: *{r['total']*100:.2f}%* (need <100%)")
        lines.append(f"📉 Bookmaker Edge: {r['margin']:.2f}%")
        lines.append(f"💸 Expected loss: ₹{abs(r['profit']):,.2f}\n")
        lines.append("━━━━━━━━━━━━━━━━")
        lines.append("📌 *Current Odds:*\n")
        for o in outcomes:
            q = odds_quality(o["odds"])
            lines.append(f"{q} *{o['name']}* @ {o['odds']:.2f} — {o['bookmaker']}")
        lines.append("\n💡 *Tip:* Try finding better odds on one outcome at another bookmaker to flip this into an arb!")

    keyboard = [
        [InlineKeyboardButton("🔄 New Calculation", callback_data="after:new"),
         InlineKeyboardButton("🔁 Same Market", callback_data="after:same")],
        [InlineKeyboardButton("📊 My Stats", callback_data="after:stats"),
         InlineKeyboardButton("💡 Get Tip", callback_data="after:tip")]
    ]
    await message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def after_result_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.replace("after:", "")
    await query.edit_message_reply_markup(None)

    if action == "new":
        ctx.user_data.clear()
        keyboard = [
            [InlineKeyboardButton(f"{v['emoji']} {k}", callback_data=f"sport:{k}")]
            for k, v in SPORTS.items()
        ]
        await query.message.reply_text(
            "🏆 *Select Sport*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SPORT_SELECT

    elif action == "same":
        sport = ctx.user_data.get("sport", "")
        market = ctx.user_data.get("market", "")
        preset = SPORTS.get(sport, {}).get("outcomes", {}).get(market)
        if preset:
            ctx.user_data["outcomes"] = [
                {"name": o, "odds": None, "bookmaker": None} for o in preset
            ]
            ctx.user_data["total"] = len(preset)
            ctx.user_data["current"] = 0
            ctx.user_data["step"] = "bookmaker"
            await query.message.reply_text(
                f"🔁 *Same market — {sport} {market}*\n\nEnter fresh odds:",
                parse_mode="Markdown"
            )
            await ask_next_msg(query.message, ctx)
            return COLLECTING_ODDS

    elif action == "stats":
        await _show_stats(query.message, update.effective_user.id)

    elif action == "tip":
        await query.message.reply_text(
            f"💡 *Pro Tip:*\n\n{random.choice(TIPS)}",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )


async def _show_stats(message, user_id):
    s = user_stats[user_id]
    rate = (s["arbs_found"] / s["calcs"] * 100) if s["calcs"] > 0 else 0
    bar = progress_bar(int(rate), 100) if s["calcs"] > 0 else "░░░░░░░░"
    await message.reply_text(
        "📊 *Your ArbBot Stats*\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"🧮 Calculations: *{s['calcs']}*\n"
        f"✅ Arbs Found: *{s['arbs_found']}*\n"
        f"🎯 Success Rate: {bar} *{rate:.1f}%*\n"
        f"💰 Total Profit: *₹{s['total_profit']:,.2f}*\n"
        f"📅 Using bot since: {s['joined']}\n\n"
        "_Keep scanning bookmakers for more arbs!_",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _show_stats(update.message, update.effective_user.id)


async def quick_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if len(args) < 3:
        await update.message.reply_text(
            "⚡ *Quick Arb Check*\n\n"
            "Usage: `/quick <odds1> <odds2> [odds3] <stake>`\n\n"
            "*Examples:*\n"
            "`/quick 2.10 2.05 10000`\n"
            "`/quick 2.10 3.40 3.20 10000`\n"
            "`/quick +110 -105 5000`",
            parse_mode="Markdown"
        )
        return
    try:
        stake = float(args[-1].replace("₹", "").replace(",", ""))
        odds_raw = args[:-1]
    except ValueError:
        await update.message.reply_text("⚠️ Last value must be the stake amount.")
        return

    outcomes = []
    for i, raw in enumerate(odds_raw, 1):
        dec = parse_odds(raw)
        if not dec or dec <= 1.0:
            await update.message.reply_text(f"⚠️ Invalid odds: `{raw}`", parse_mode="Markdown")
            return
        outcomes.append({"name": f"Outcome {i}", "odds": dec, "bookmaker": "—", "raw": raw})

    ctx.user_data["outcomes"] = outcomes
    ctx.user_data["sport"] = "Quick Check"
    ctx.user_data["market"] = " vs ".join(o["raw"] for o in outcomes)
    await show_result(update.message, ctx, stake, update.effective_user.id)


async def learn_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📖 What is Arb Betting?", callback_data="learn:what")],
        [InlineKeyboardButton("🔢 Understanding Odds", callback_data="learn:odds")],
        [InlineKeyboardButton("📋 Step-by-Step Guide", callback_data="learn:guide")],
        [InlineKeyboardButton("⚠️ Risks & Pro Tips", callback_data="learn:risks")],
        [InlineKeyboardButton("🏦 Best Bookmakers India", callback_data="learn:books")],
    ]
    await update.message.reply_text(
        "📚 *Learn Arbitrage Betting*\n\nChoose a topic:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


LEARN_CONTENT = {
    "what": (
        "📖 *What is Arbitrage Betting?*\n\n"
        "Arb betting means placing bets on *all possible outcomes* across different bookmakers "
        "to guarantee profit regardless of the result.\n\n"
        "*How it works:*\n"
        "Each bookmaker sets slightly different odds. When the combined implied probabilities "
        "add up to less than 100%, a profit window exists.\n\n"
        "*Example — Tennis Match:*\n"
        "• Bet365: Player A wins @ 2.10 → 47.6%\n"
        "• 1xBet: Player B wins @ 2.20 → 45.5%\n"
        "• Total: *93.1%* ← less than 100%!\n\n"
        "Stake ₹10,000 → get back *₹10,742* guaranteed 💰"
    ),
    "odds": (
        "🔢 *Understanding Odds*\n\n"
        "*Decimal (most common):*\n"
        "• 2.00 = doubles your money\n"
        "• 1.50 = get ₹150 for ₹100 stake\n"
        "• Implied prob = 1 ÷ odds\n\n"
        "*American:*\n"
        "• +200 = win ₹200 on ₹100 stake\n"
        "• -150 = stake ₹150 to win ₹100\n\n"
        "*Fractional (UK):*\n"
        "• 2/1 = win ₹2 per ₹1 staked\n"
        "• 1/2 = win ₹1 per ₹2 staked\n\n"
        "_ArbBot accepts all three formats!_"
    ),
    "guide": (
        "📋 *Step-by-Step Arb Guide*\n\n"
        "*Step 1:* Create accounts on 3-5 bookmakers\n\n"
        "*Step 2:* Find a match you want to bet on\n\n"
        "*Step 3:* Note the best odds for each outcome from different bookmakers\n\n"
        "*Step 4:* Enter into ArbBot using /arb\n\n"
        "*Step 5:* If arb found, place all bets simultaneously\n\n"
        "*Step 6:* Collect guaranteed profit! 🎉\n\n"
        "⚡ *Critical: Place all bets at the same time!*"
    ),
    "risks": (
        "⚠️ *Risks & Pro Tips*\n\n"
        "*Risks:*\n"
        "• Odds change fast — act immediately\n"
        "• Bookmakers may limit accounts if they detect arbing\n"
        "• Insufficient balance can cause missed bets\n\n"
        "*Pro Tips:*\n"
        "✅ Round stakes to nearest ₹10 to look natural\n"
        "✅ Use 3-4 different bookmakers\n"
        "✅ Start small (₹1,000-2,000) to learn\n"
        "✅ Only chase arbs above 1% profit\n"
        "✅ Best arbs appear 30-60 min before kickoff\n"
        "✅ Cricket & Football = most arbs in India"
    ),
    "books": (
        "🏦 *Best Bookmakers for India*\n\n"
        "*Top picks for arb betting:*\n\n"
        "🥇 *Bet365* — best odds, fast payouts\n"
        "🥈 *1xBet* — huge market coverage\n"
        "🥉 *Betway* — reliable, India-focused\n"
        "4️⃣ *Parimatch* — good cricket odds\n"
        "5️⃣ *10Cric* — India-specific platform\n"
        "6️⃣ *Dafabet* — popular in Asia\n\n"
        "💡 *Tip:* Register on at least 3 to have enough options for arbs!\n\n"
        "_Always check local regulations before betting._"
    )
}


async def learn_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    topic = query.data.replace("learn:", "")

    if topic == "back":
        keyboard = [
            [InlineKeyboardButton("📖 What is Arb Betting?", callback_data="learn:what")],
            [InlineKeyboardButton("🔢 Understanding Odds", callback_data="learn:odds")],
            [InlineKeyboardButton("📋 Step-by-Step Guide", callback_data="learn:guide")],
            [InlineKeyboardButton("⚠️ Risks & Pro Tips", callback_data="learn:risks")],
            [InlineKeyboardButton("🏦 Best Bookmakers India", callback_data="learn:books")],
        ]
        await query.edit_message_text(
            "📚 *Learn Arbitrage Betting*\n\nChoose a topic:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    content = LEARN_CONTENT.get(topic, "Coming soon!")
    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="learn:back")]]
    await query.edit_message_text(
        content,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def tips_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"💡 *Pro Tip:*\n\n{random.choice(TIPS)}",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ *ArbBot Pro — Help*\n\n"
        "*Commands:*\n"
        "/arb — Guided arb calculator\n"
        "/quick — One-line quick check\n"
        "/stats — Your stats & history\n"
        "/learn — Learn arb betting\n"
        "/tips — Daily pro tip\n"
        "/cancel — Cancel calculation\n\n"
        "*Quick Check:*\n"
        "`/quick 2.10 3.40 3.20 10000`\n\n"
        "*Odds formats:*\n"
        "Decimal `2.10` | American `+110` | Fractional `11/10`\n\n"
        "_Use the menu buttons for the easiest experience!_",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "❌ Cancelled.\n\nTap *🧮 New Calculation* to start again.",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )
    return ConversationHandler.END


async def menu_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🧮 New Calculation":
        return await new_calc(update, ctx)
    elif text == "⚡ Quick Check":
        await update.message.reply_text(
            "⚡ *Quick Check*\n\n"
            "Send: `/quick <odds1> <odds2> <stake>`\n\n"
            "Example: `/quick 2.10 2.05 10000`",
            parse_mode="Markdown"
        )
    elif text == "📊 My Stats":
        await stats_cmd(update, ctx)
    elif text == "📚 Learn Arb":
        await learn_cmd(update, ctx)
    elif text == "💡 Daily Tip":
        await tips_cmd(update, ctx)
    elif text == "ℹ️ Help":
        await help_cmd(update, ctx)
    else:
        await update.message.reply_text(
            "👇 Use the buttons below or type /arb",
            reply_markup=main_menu()
        )


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("Set BOT_TOKEN environment variable.")

    app = Application.builder().token(token).build()

    arb_conv = ConversationHandler(
        entry_points=[
            CommandHandler("arb", new_calc),
            MessageHandler(filters.Regex("^🧮 New Calculation$"), new_calc)
        ],
        states={
            SPORT_SELECT: [
                CallbackQueryHandler(sport_selected, pattern=r"^sport:"),
            ],
            MARKET_SELECT: [
                CallbackQueryHandler(market_selected, pattern=r"^(market:|back:sport)"),
                CallbackQueryHandler(custom_outcomes, pattern=r"^custom:"),
            ],
            COLLECTING_ODDS: [
                CallbackQueryHandler(bookmaker_cb, pattern=r"^bm:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_input),
            ],
            GET_STAKE: [
                CallbackQueryHandler(stake_button_cb, pattern=r"^stake:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, stake_text_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("learn", learn_cmd))
    app.add_handler(CommandHandler("tips", tips_cmd))
    app.add_handler(CommandHandler("quick", quick_cmd))
    app.add_handler(arb_conv)
    app.add_handler(CallbackQueryHandler(after_result_cb, pattern=r"^after:"))
    app.add_handler(CallbackQueryHandler(learn_cb, pattern=r"^learn:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_text))

    logger.info("ArbBot Pro is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
