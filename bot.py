import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes
)
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
GENRE, SETTING, PROTAGONIST = range(3)

GENRES = {
    'avventura': '⚔️ Avventura',
    'mistero':   '🔍 Mistero',
    'commedia':  '😄 Commedia',
    'fantasy':   '🧙 Fantasy',
}

SETTINGS = {
    'città':    '🏙️ Città',
    'natura':   '🌲 Natura',
    'scuola':   '🏫 Scuola',
    'spazio':   '🚀 Spazio',
}

PROTAGONISTS = {
    'uomo':    '👨 Un uomo',
    'donna':   '👩 Una donna',
    'animale': '🐱 Un animale',
    'robot':   '🤖 Un robot',
}


def make_keyboard(options: dict, prefix: str) -> InlineKeyboardMarkup:
    items = list(options.items())
    rows = [
        [InlineKeyboardButton(label, callback_data=f"{prefix}{key}") for key, label in items[i:i+2]]
        for i in range(0, len(items), 2)
    ]
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Ciao! I'm your vocabulary story bot.\n\n"
        "Send /generate to turn your latest lesson into a story.\n"
        "Send /cancel at any time to stop."
    )


async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from google_docs import get_latest_lesson

    msg = await update.message.reply_text("📖 Reading your Google Doc...")

    try:
        lesson = get_latest_lesson(os.getenv('GOOGLE_DOC_ID'))
        context.user_data['lesson'] = lesson

        preview = '\n'.join(f"• {p}" for p in lesson['phrases'][:6])
        if len(lesson['phrases']) > 6:
            preview += f"\n  _(+{len(lesson['phrases']) - 6} more)_"

        await msg.edit_text(
            f"✅ *{lesson['title']}*\n\n{preview}\n\n*Choose a genre:*",
            parse_mode='Markdown',
            reply_markup=make_keyboard(GENRES, 'genre_')
        )
        return GENRE

    except Exception as e:
        logger.error(f"Error reading doc: {e}", exc_info=True)
        await msg.edit_text(
            f"❌ Couldn't read the doc.\n\n`{e}`\n\n"
            "Check your GOOGLE_DOC_ID and GOOGLE_CREDENTIALS.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END


async def genre_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    key = query.data.replace('genre_', '')
    context.user_data['genre'] = key

    await query.edit_message_text(
        f"{GENRES[key]} ✓\n\n*Choose a setting:*",
        parse_mode='Markdown',
        reply_markup=make_keyboard(SETTINGS, 'setting_')
    )
    return SETTING


async def setting_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    key = query.data.replace('setting_', '')
    context.user_data['setting'] = key

    await query.edit_message_text(
        f"{GENRES[context.user_data['genre']]} ✓\n"
        f"{SETTINGS[key]} ✓\n\n"
        f"*Who's the protagonist?*",
        parse_mode='Markdown',
        reply_markup=make_keyboard(PROTAGONISTS, 'prot_')
    )
    return PROTAGONIST


async def protagonist_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    key = query.data.replace('prot_', '')
    context.user_data['protagonist'] = key

    genre_label     = GENRES[context.user_data['genre']]
    setting_label   = SETTINGS[context.user_data['setting']]
    prot_label      = PROTAGONISTS[key]

    await query.edit_message_text(
        f"{genre_label} ✓\n{setting_label} ✓\n{prot_label} ✓\n\n"
        f"⏳ Writing the story...",
        parse_mode='Markdown'
    )

    lesson = context.user_data['lesson']

    try:
        from story_generator import generate_story_and_exercises, generate_cover_image
        from google_docs import append_story_to_doc

        # 1. Generate story + exercises
        result = generate_story_and_exercises(
            phrases=lesson['phrases'],
            genre=context.user_data['genre'],
            setting=context.user_data['setting'],
            protagonist=context.user_data['protagonist'],
        )

        # 2. Generate cover image
        await query.edit_message_text("🎨 Generating cover image...")
        image_url = generate_cover_image(
            image_prompt=result.get('image_prompt', f"A {context.user_data['genre']} scene in Italy"),
            genre=context.user_data['genre'],
            setting=context.user_data['setting'],
        )

        # 3. Write to Google Doc
        await query.edit_message_text("📝 Saving to your Google Doc...")
        doc_id = os.getenv('GOOGLE_DOC_ID')
        append_story_to_doc(
            doc_id=doc_id,
            lesson_title=lesson['title'],
            story=result['story'],
            translation=result.get('translation', ''),
            exercises=result.get('exercises', []),
            image_url=image_url,
        )

        # 4. Send cover image to Telegram
        story_preview = result['story'][:220].rsplit(' ', 1)[0] + '…'
        await query.message.reply_photo(
            photo=image_url,
            caption=f"📖 *{lesson['title']}*\n\n_{story_preview}_",
            parse_mode='Markdown'
        )

        # 5. Final confirmation with doc link
        doc_link = f"https://docs.google.com/document/d/{doc_id}"
        await query.edit_message_text(
            f"✅ *Done!* Story saved to your doc.\n\n[📄 Open Google Doc]({doc_link})",
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Generation error: {e}", exc_info=True)
        await query.edit_message_text(f"❌ Something went wrong:\n\n`{e}`", parse_mode='Markdown')

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END


def main():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set.")

    app = Application.builder().token(token).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler('generate', generate)],
        states={
            GENRE:       [CallbackQueryHandler(genre_chosen,       pattern='^genre_')],
            SETTING:     [CallbackQueryHandler(setting_chosen,     pattern='^setting_')],
            PROTAGONIST: [CallbackQueryHandler(protagonist_chosen, pattern='^prot_')],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False,
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(conv)

    logger.info("🤖 Bot started — polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
