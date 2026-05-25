import os
import json
import asyncio
import logging
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ══════════════════════════════════════════
#           إعداد المفاتيح
# ══════════════════════════════════════════
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════
#        قاعدة بيانات اللاعبين (ذاكرة مؤقتة)
# ══════════════════════════════════════════
players = {}

# ══════════════════════════════════════════
#        النظام الأساسي للرواية
# ══════════════════════════════════════════
SHADOW_SLAVE_SYSTEM = """
أنت راوي قصة تفاعلية داخل عالم رواية Shadow Slave (عبد الظل).

═══════════════════════════════════
📖 قوانين العالم:
═══════════════════════════════════
- العالم أصابه وباء الكابوس (Nightmare Spell) يجبر البشر على دخول عالم الكوابيس
- من يدخل الكابوس يواجه وحشاً، إما يُقتل أو يُصحى (Awakened)
- المستيقظون يحصلون على قدرات خارقة وأصداء (Echoes) وجوانب (Aspects)
- العالم مقسوم: البشر العاديون والمستيقظون، والأخيرون محل تقدير واحترام

═══════════════════════════════════
⚔️ مراحل القوة بالترتيب:
═══════════════════════════════════
1. Sleeper (نائم) - قبل الصحيان
2. Dreamer (حالم) - أول مرحلة بعد الكابوس
3. Sleepwalker (سائر نائم) - المرحلة الثانية
4. Awakened (مستيقظ) - المرحلة الثالثة
5. Enlightened (منير) - المرحلة الرابعة
6. Great One (العظيم) - أعلى مرحلة

═══════════════════════════════════
💫 نظام القدرات:
═══════════════════════════════════
- كل شخص عند صحيانه يحصل على: صفة (Aspect) + صدى (Echo) فريد
- الـ Echoes هي أرواح وحوش مهزومة تمنح قدرات
- الـ Aspects هي موهبة/قدرة فطرية خاصة بالشخص
- الـ Memories هي أسلحة وأدوات مستخلصة من الكوابيس
- الـ Runes هي رموز قوة تُكتسب في الكوابيس

═══════════════════════════════════
🌍 الشخصيات الرئيسية:
═══════════════════════════════════
- Sunny (صني): البطل الأصلي، الوحيد بلا ظل، Aspect: Shadow (الظل)
- Nephis (نيفيس): المقاتلة الأسطورية، من سلالة النجوم، قوتها النار
- Cassie (كاسي): عمياء لكن تتنبأ بالمستقبل، صديقة Sunny
- Effie: محاربة ضخمة وقوية، رفيقة Sunny
- Kai: المقاتل الرشيق الأنيق بالقوس
- Morgan: الطبيبة الغامضة في الفوج
- Saint (القديس): أحد الـ Great Ones الأقوياء

═══════════════════════════════════
👹 أنواع الوحوش:
═══════════════════════════════════
- Nightmare Creatures: وحوش عالم الكابوس بمراتب مختلفة
- Aberrations: طفرات خطيرة جداً
- Shadows: ظلال قاتلة
- Fiends: شياطين عالم الكابوس
- Calamities: كوارث بشرية أو وحشية تهدد المدن

═══════════════════════════════════
📍 الأماكن المهمة:
═══════════════════════════════════
- Ravenheart Academy: أكاديمية المستيقظين
- The Forgotten Shore: الشاطئ المنسي (حيث بدأت قصة Sunny)
- Dream Realm: عالم الكابوس الداخلي
- The City of Valor: مدينة رئيسية في العالم

═══════════════════════════════════
📜 أسلوب السرد:
═══════════════════════════════════
- اسرد بالعربية الفصحى المشوبة بالعامية أحياناً
- اجعل المشاهد حية وتفصيلية وغامضة
- اذكر دائماً: المكان، الجو، التوتر
- عند المعارك: اجعلها سينمائية ومثيرة
- أعطِ خيارات للاعب في نهاية كل مشهد
- احترم قوانين العالم دائماً ولا تخترع قوى غير موجودة في الرواية
- اذكر الإحصائيات والمستوى عند الترقي

═══════════════════════════════════
🎮 كيف تتعامل مع اللاعب:
═══════════════════════════════════
- اللاعب يمتلك شخصيته الخاصة (مش Sunny)
- ابدأ دائماً بتجربة الكابوس الأولى عند إنشاء الشخصية
- اعطِ الـ Aspect والـ Echo الأولى بناءً على كيفية تصرف اللاعب في الكابوس
- تتبع: المستوى، الـ Echoes، الـ Aspects، الـ Memories، الـ Runes
- اجعل التقدم منطقياً وليس سريعاً جداً
- الموت ممكن! إذا تصرف اللاعب بحماقة، العواقب حقيقية

تذكر: أنت لست مجرد راوٍ، أنت تبني تجربة عميقة داخل عالم Shadow Slave الأصيل.
"""

def get_player(user_id):
    if user_id not in players:
        players[user_id] = {
            "name": None,
            "level": "Sleeper",
            "aspect": None,
            "echoes": [],
            "memories": [],
            "runes": [],
            "history": [],
            "created": False
        }
    return players[user_id]

async def ask_gemini(player_data, user_message):
    """إرسال رسالة لـ Gemini مع تاريخ المحادثة"""
    
    # بناء السياق
    player_info = f"""
معلومات الشخصية الحالية:
- الاسم: {player_data['name'] or 'لم يُحدد بعد'}
- المستوى: {player_data['level']}
- الـ Aspect: {player_data['aspect'] or 'لم يُكتسب بعد'}
- الـ Echoes: {', '.join(player_data['echoes']) if player_data['echoes'] else 'لا يوجد'}
- الـ Memories: {', '.join(player_data['memories']) if player_data['memories'] else 'لا يوجد'}
- الـ Runes: {len(player_data['runes'])} رون
"""

    # تاريخ المحادثة (آخر 10 رسائل فقط لتوفير التوكنز)
    history_text = ""
    for msg in player_data['history'][-10:]:
        role = "اللاعب" if msg['role'] == 'user' else "الراوي"
        history_text += f"\n{role}: {msg['content']}"

    full_prompt = f"""{SHADOW_SLAVE_SYSTEM}

{player_info}

═══ تاريخ المحادثة ═══
{history_text}

═══ رسالة اللاعب الجديدة ═══
اللاعب: {user_message}

الراوي:"""

    try:
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return "⚠️ حدث خطأ في الاتصال. حاول مرة أخرى."

# ══════════════════════════════════════════
#              أوامر البوت
# ══════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    
    keyboard = [
        [InlineKeyboardButton("⚔️ ابدأ المغامرة", callback_data="new_game")],
        [InlineKeyboardButton("📊 إحصائياتي", callback_data="stats")],
        [InlineKeyboardButton("🔄 إعادة البدء", callback_data="reset")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🌑 *مرحباً في عالم Shadow Slave*\n\n"
        "في عالم أصابه وباء الكوابيس...\n"
        "كل إنسان محكوم عليه بمواجهة كابوسه الخاص.\n"
        "إما أن تُقتل... أو أن تُصحى.\n\n"
        "أنت من ستقرر مصيرك. 🔥",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player = get_player(user_id)
    
    if query.data == "new_game":
        if player['created']:
            await query.edit_message_text(
                "⚠️ عندك شخصية موجودة! استخدم /reset إذا بدك تبدأ من جديد."
            )
            return
        
        player['created'] = True
        intro_msg = "ابدأ المغامرة"
        response = await ask_gemini(player, "ابدأ القصة من البداية. اطلب مني اسم شخصيتي ثم أدخلني في كابوسي الأول.")
        player['history'].append({"role": "user", "content": intro_msg})
        player['history'].append({"role": "assistant", "content": response})
        await query.edit_message_text(f"🌑 {response}")
        
    elif query.data == "stats":
        stats_text = f"""
📊 *إحصائيات شخصيتك*

👤 الاسم: {player['name'] or 'غير محدد'}
⚡ المستوى: {player['level']}
💫 الـ Aspect: {player['aspect'] or 'لم يُكتسب'}
👹 الـ Echoes: {', '.join(player['echoes']) if player['echoes'] else 'لا يوجد'}
⚔️ الـ Memories: {', '.join(player['memories']) if player['memories'] else 'لا يوجد'}
🔮 الـ Runes: {len(player['runes'])}
        """
        await query.edit_message_text(stats_text, parse_mode="Markdown")
        
    elif query.data == "reset":
        players[user_id] = {
            "name": None,
            "level": "Sleeper",
            "aspect": None,
            "echoes": [],
            "memories": [],
            "runes": [],
            "history": [],
            "created": False
        }
        await query.edit_message_text(
            "🔄 تم إعادة التعيين!\n\nاستخدم /start لتبدأ مغامرة جديدة."
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    user_text = update.message.text
    
    if not player['created']:
        await update.message.reply_text(
            "استخدم /start أولاً لتبدأ مغامرتك! ⚔️"
        )
        return
    
    # أرسل رسالة انتظار
    waiting_msg = await update.message.reply_text("🌑 الراوي يفكر...")
    
    # احصل على رد Gemini
    response = await ask_gemini(player, user_text)
    
    # احفظ في التاريخ
    player['history'].append({"role": "user", "content": user_text})
    player['history'].append({"role": "assistant", "content": response})
    
    # حذف رسالة الانتظار وإرسال الرد
    await waiting_msg.delete()
    
    # تقسيم الرسالة إذا كانت طويلة
    if len(response) > 4000:
        parts = [response[i:i+4000] for i in range(0, len(response), 4000)]
        for part in parts:
            await update.message.reply_text(part)
    else:
        await update.message.reply_text(response)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    
    stats_text = f"""
📊 *إحصائيات شخصيتك*

👤 الاسم: {player['name'] or 'غير محدد'}
⚡ المستوى: {player['level']}
💫 الـ Aspect: {player['aspect'] or 'لم يُكتسب'}
👹 الـ Echoes: {', '.join(player['echoes']) if player['echoes'] else 'لا يوجد'}
⚔️ الـ Memories: {', '.join(player['memories']) if player['memories'] else 'لا يوجد'}
🔮 الـ Runes: {len(player['runes'])}
    """
    await update.message.reply_text(stats_text, parse_mode="Markdown")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    players[user_id] = {
        "name": None,
        "level": "Sleeper",
        "aspect": None,
        "echoes": [],
        "memories": [],
        "runes": [],
        "history": [],
        "created": False
    }
    await update.message.reply_text(
        "🔄 تم إعادة التعيين!\n\nاستخدم /start لتبدأ مغامرة جديدة."
    )

# ══════════════════════════════════════════
#              تشغيل البوت
# ══════════════════════════════════════════
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🌑 Shadow Slave Bot Started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
