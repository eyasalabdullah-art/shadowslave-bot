import os
import json
import asyncio
import logging
import random
import sqlite3
from contextlib import closing

import google.generativeai as genai

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ═══════════════════════════════════════════════
#                    إعدادات
# ═══════════════════════════════════════════════

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN غير موجود")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY غير موجود")

genai.configure(api_key=GEMINI_API_KEY)

MODEL = genai.GenerativeModel("gemini-1.5-flash")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

DB_NAME = "shadow_slave.db"

# ═══════════════════════════════════════════════
#                  قاعدة البيانات
# ═══════════════════════════════════════════════

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            data TEXT NOT NULL
        )
        """)
        conn.commit()


def default_player():
    return {
        "name": None,
        "created": False,

        "level": "Sleeper",
        "exp": 0,

        "hp": 100,
        "max_hp": 100,

        "stamina": 100,
        "max_stamina": 100,

        "strength": 5,
        "agility": 5,
        "willpower": 5,

        "aspect": None,

        "echoes": [],
        "memories": [],
        "runes": [],

        "summary": "",

        "history": []
    }


def get_player(user_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute(
            "SELECT data FROM players WHERE user_id = ?",
            (user_id,)
        ).fetchone()

        if row:
            return json.loads(row[0])

    player = default_player()
    save_player(user_id, player)
    return player


def save_player(user_id: int, data: dict):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO players (user_id, data)
            VALUES (?, ?)
            """,
            (
                user_id,
                json.dumps(data, ensure_ascii=False)
            )
        )
        conn.commit()

# ═══════════════════════════════════════════════
#                نظام RPG
# ═══════════════════════════════════════════════

LEVELS = [
    "Sleeper",
    "Dreamer",
    "Sleepwalker",
    "Awakened",
    "Enlightened",
    "Great One"
]


def roll_dice():
    return random.randint(1, 20)


def clamp_stats(player):
    player["hp"] = max(0, min(player["hp"], player["max_hp"]))
    player["stamina"] = max(
        0,
        min(player["stamina"], player["max_stamina"])
    )


def apply_updates(player, updates):
    if not updates:
        return

    allowed = {
        "name",
        "aspect",
        "level",
        "hp_change",
        "stamina_change",
        "exp_gain",
        "echoes",
        "memories",
        "runes_added",
        "strength",
        "agility",
        "willpower",
    }

    updates = {
        k: v for k, v in updates.items()
        if k in allowed
    }

    if updates.get("name") and not player["name"]:
        player["name"] = updates["name"]

    if updates.get("aspect") and not player["aspect"]:
        player["aspect"] = updates["aspect"]

    if updates.get("level") in LEVELS:
        current_index = LEVELS.index(player["level"])
        new_index = LEVELS.index(updates["level"])

        # منع القفز غير القانوني
        if new_index <= current_index + 1:
            player["level"] = updates["level"]

    player["hp"] += updates.get("hp_change", 0)
    player["stamina"] += updates.get("stamina_change", 0)

    player["exp"] += updates.get("exp_gain", 0)

    if updates.get("strength"):
        player["strength"] = max(
            player["strength"],
            updates["strength"]
        )

    if updates.get("agility"):
        player["agility"] = max(
            player["agility"],
            updates["agility"]
        )

    if updates.get("willpower"):
        player["willpower"] = max(
            player["willpower"],
            updates["willpower"]
        )

    for echo in updates.get("echoes", []):
        if echo not in player["echoes"]:
            player["echoes"].append(echo)

    for memory in updates.get("memories", []):
        if memory not in player["memories"]:
            player["memories"].append(memory)

    for _ in range(updates.get("runes_added", 0)):
        player["runes"].append("Rune")

    clamp_stats(player)

# ═══════════════════════════════════════════════
#                  نظام Gemini
# ═══════════════════════════════════════════════

SYSTEM_PROMPT = """
أنت راوي RPG داخل عالم Shadow Slave.

مهم جداً:
- أعد JSON صالح فقط
- لا تضف markdown
- لا تضف ```json
- لا تشرح شيئاً خارج JSON

شكل الرد:

{
  "story": "النص القصصي",
  "updates": {
    "name": null,
    "aspect": null,
    "level": null,
    "hp_change": 0,
    "stamina_change": 0,
    "exp_gain": 0,
    "echoes": [],
    "memories": [],
    "runes_added": 0,
    "strength": null,
    "agility": null,
    "willpower": null
  },
  "choices": [
    "خيار 1",
    "خيار 2",
    "خيار 3"
  ]
}

القوانين:
- لا تجعل اللاعب قوي بسرعة
- الموت ممكن
- لا تكسر قوانين عالم Shadow Slave
- الـ Aspect يكتسب مرة واحدة فقط
- لا تمنح Echoes بسهولة
- اجعل السرد مظلم وغامض
"""


async def ask_gemini(player, user_message):

    dice = roll_dice()

    prompt = f"""
{SYSTEM_PROMPT}

═══════════════
حالة اللاعب
═══════════════

{json.dumps(player, ensure_ascii=False)}

═══════════════
Dice Roll
═══════════════

{dice}

═══════════════
رسالة اللاعب
═══════════════

{user_message}
"""

    try:
        response = await asyncio.to_thread(
            MODEL.generate_content,
            prompt
        )

        text = response.text.strip()

        text = text.replace("```json", "")
        text = text.replace("```", "")

        data = json.loads(text)

        return data

    except Exception as e:
        logger.error(e)

        return {
            "story": "⚠️ حدث خطأ أثناء توليد القصة.",
            "updates": {},
            "choices": []
        }

# ═══════════════════════════════════════════════
#                 أدوات مساعدة
# ═══════════════════════════════════════════════

def split_message(text, limit=4000):
    parts = []

    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit)

        if split_at == -1:
            split_at = limit

        parts.append(text[:split_at])
        text = text[split_at:]

    parts.append(text)

    return parts


def build_stats(player):

    return f"""
📊 إحصائيات الشخصية

👤 الاسم: {player['name'] or 'غير معروف'}

⚔️ المستوى: {player['level']}
✨ Aspect: {player['aspect'] or 'لم يُكتسب'}

❤️ HP: {player['hp']} / {player['max_hp']}
⚡ Stamina: {player['stamina']} / {player['max_stamina']}

💪 Strength: {player['strength']}
🏃 Agility: {player['agility']}
🧠 Willpower: {player['willpower']}

👹 Echoes: {len(player['echoes'])}
⚔️ Memories: {len(player['memories'])}
🔮 Runes: {len(player['runes'])}

📈 EXP: {player['exp']}
"""


def build_choices_keyboard(choices):

    keyboard = []

    for i, choice in enumerate(choices):
        keyboard.append([
            InlineKeyboardButton(
                choice,
                callback_data=f"choice|{choice}"
            )
        ])

    return InlineKeyboardMarkup(keyboard)

# ═══════════════════════════════════════════════
#                 Telegram
# ═══════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [
            InlineKeyboardButton(
                "⚔️ ابدأ المغامرة",
                callback_data="new_game"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 الإحصائيات",
                callback_data="stats"
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 إعادة البدء",
                callback_data="reset"
            )
        ]
    ]

    await update.message.reply_text(
        "🌑 مرحباً بك في عالم Shadow Slave\n\n"
        "إما أن تموت...\n"
        "أو تستيقظ.\n\n"
        "مصيرك يبدأ الآن.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    player = get_player(user_id)

    await update.message.reply_text(
        build_stats(player)
    )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    save_player(user_id, default_player())

    await update.message.reply_text(
        "🔄 تم حذف شخصيتك بالكامل."
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    player = get_player(user_id)

    data = query.data

    # ═══════════════════════════
    # New Game
    # ═══════════════════════════

    if data == "new_game":

        if player["created"]:
            await query.message.reply_text(
                "⚠️ لديك شخصية بالفعل."
            )
            return

        player["created"] = True

        save_player(user_id, player)

        waiting = await query.message.reply_text(
            "🌑 الراوي يستيقظ..."
        )

        ai = await ask_gemini(
            player,
            "ابدأ القصة. اطلب اسم الشخصية أولاً."
        )

        story = ai["story"]

        choices = ai.get("choices", [])

        player["history"].append({
            "role": "assistant",
            "content": story
        })

        save_player(user_id, player)

        await waiting.delete()

        keyboard = build_choices_keyboard(choices)

        await query.message.reply_text(
            story,
            reply_markup=keyboard if choices else None
        )

    # ═══════════════════════════
    # Stats
    # ═══════════════════════════

    elif data == "stats":

        await query.message.reply_text(
            build_stats(player)
        )

    # ═══════════════════════════
    # Reset
    # ═══════════════════════════

    elif data == "reset":

        save_player(user_id, default_player())

        await query.message.reply_text(
            "🔄 تم إعادة تعيين الشخصية."
        )

    # ═══════════════════════════
    # Choices
    # ═══════════════════════════

    elif data.startswith("choice|"):

        choice = data.split("|", 1)[1]

        waiting = await query.message.reply_text(
            "🌑 الراوي ينسج مصيرك..."
        )

        ai = await ask_gemini(player, choice)

        story = ai.get("story", "")

        updates = ai.get("updates", {})

        choices = ai.get("choices", [])

        apply_updates(player, updates)

        player["history"].append({
            "role": "user",
            "content": choice
        })

        player["history"].append({
            "role": "assistant",
            "content": story
        })

        # اختصار التاريخ
        player["history"] = player["history"][-20:]

        save_player(user_id, player)

        await waiting.delete()

        full_text = (
            f"{story}\n\n"
            f"{build_stats(player)}"
        )

        parts = split_message(full_text)

        keyboard = build_choices_keyboard(choices)

        for i, part in enumerate(parts):

            if i == len(parts) - 1:
                await query.message.reply_text(
                    part,
                    reply_markup=keyboard if choices else None
                )
            else:
                await query.message.reply_text(part)


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    player = get_player(user_id)

    if not player["created"]:

        await update.message.reply_text(
            "⚠️ استخدم /start أولاً."
        )

        return

    user_text = update.message.text

    waiting = await update.message.reply_text(
        "🌑 الراوي يفكر..."
    )

    ai = await ask_gemini(player, user_text)

    story = ai.get("story", "")

    updates = ai.get("updates", {})

    choices = ai.get("choices", [])

    apply_updates(player, updates)

    player["history"].append({
        "role": "user",
        "content": user_text
    })

    player["history"].append({
        "role": "assistant",
        "content": story
    })

    player["history"] = player["history"][-20:]

    save_player(user_id, player)

    await waiting.delete()

    full_text = (
        f"{story}\n\n"
        f"{build_stats(player)}"
    )

    parts = split_message(full_text)

    keyboard = build_choices_keyboard(choices)

    for i, part in enumerate(parts):

        if i == len(parts) - 1:
            await update.message.reply_text(
                part,
                reply_markup=keyboard if choices else None
            )
        else:
            await update.message.reply_text(part)

# ═══════════════════════════════════════════════
#                     Main
# ═══════════════════════════════════════════════

def main():

    init_db()

    app = Application.builder().token(
        TELEGRAM_TOKEN
    ).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("reset", reset_command))

    app.add_handler(
        CallbackQueryHandler(button_handler)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    logger.info("🌑 Shadow Slave RPG Bot Started")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
