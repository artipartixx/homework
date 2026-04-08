import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, MessageHandler, filters
)
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States for /generate (teacher's own doc)
GENRE, SETTING, PROTAGONIST = range(3)

# States for /make (student delivery)
PICK_STUDENT, MAKE_GENRE, MAKE_SETTING, MAKE_PROTAGONIST = range(4, 8)

GENRES = {
    'avventura': 'Avventura',
    'mistero':   'Mistero',
    'commedia':  'Commedia',
    'fantasy':   'Fantasy',
}

SETTINGS = {
    'citta':   'Citta',
    'natura':  'Natura',
    'scuola':  'Scuola',
    'spazio':  'Spazio',
}

PROTAGONISTS = {
    'uomo':    'Un uomo',
    'donna':   'Una donna',
    'animale': 'Un animale',
    'robot':   'Un robot',
}


def make_keyboard(options: dict, prefix: str) -> InlineKeyboardMarkup:
    items = list(options.items())
    rows = [
        [InlineKeyboardButton(label, callback_data=f"{prefix}{key}") for key, label in items[i:i+2]]
        for i in range(0, len(items), 2)
    ]
    return InlineKeyboardMarkup(rows)


# ──────────────────────────────────────────────
# /start
# ──────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Ciao! I'm your vocabulary story bot.\n\n"
        f"Your chat ID is: `{chat_id}`\n"
        f"(Give this to your teacher to add you to the student list)\n\n"
        f"Commands:\n"
        f"/generate - create a story for your own doc\n"
        f"/make - create and send a story to a student",
        parse_mode='Markdown'
    )


# ──────────────────────────────────────────────
# /generate  (teacher's own doc, unchanged flow)
# ──────────────────────────────────────────────

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from google_docs import get_latest_lesson

    msg = await update.message.reply_text("Reading your Google Doc...")

    try:
        lesson = get_latest_lesson(os.getenv('GOOGLE_DOC_ID'))
        context.user_data['lesson'] = lesson
        context.user_data['student'] = None  # no student profile

        preview = '\n'.join(f"- {p}" for p in lesson['phrases'][:6])
        if len(lesson['phrases']) > 6:
            preview += f"\n  (+{len(lesson['phrases']) - 6} more)"

        await msg.edit_text(
            f"*{lesson['title']}*\n\n{preview}\n\nChoose a genre:",
            parse_mode='Markdown',
            reply_markup=make_keyboard(GENRES, 'genre_')
        )
        return GENRE

    except Exception as e:
        logger.error(f"Error in /generate: {e}", exc_info=True)
        await msg.edit_text(f"Could not read the doc.\n\n`{e}`", parse_mode='Markdown')
        return ConversationHandler.END


async def genre_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace('genre_', '')
    context.user_data['genre'] = key
    await query.edit_message_text(
        f"{GENRES[key]} chosen.\n\nChoose a setting:",
        reply_markup=make_keyboard(SETTINGS, 'setting_')
    )
    return SETTING


async def setting_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace('setting_', '')
    context.user_data['setting'] = key
    await query.edit_message_text(
        f"{GENRES[context.user_data['genre']]} / {SETTINGS[key]}\n\nWho is the protagonist?",
        reply_markup=make_keyboard(PROTAGONISTS, 'prot_')
    )
    return PROTAGONIST


async def protagonist_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace('prot_', '')
    context.user_data['protagonist'] = key

    await query.edit_message_text("Writing the story...")

    lesson  = context.user_data['lesson']
    student = context.user_data.get('student')
    doc_id  = student['doc_id'] if student else os.getenv('GOOGLE_DOC_ID')

    try:
        from story_generator import generate_story_and_exercises, generate_cover_image, generate_voiceover
        from google_docs import append_story_to_doc

        result = generate_story_and_exercises(
            phrases=lesson['phrases'],
            genre=context.user_data['genre'],
            setting=context.user_data['setting'],
            protagonist=context.user_data['protagonist'],
            student=student,
        )

        await query.edit_message_text("Generating cover image...")
        image_url = generate_cover_image(
            image_prompt=result.get('image_prompt', 'A warm Italian scene'),
            genre=context.user_data['genre'],
            setting=context.user_data['setting'],
        )

        await query.edit_message_text("Recording voiceover...")
        audio_buffer = generate_voiceover(result['story'])

        await query.edit_message_text("Saving to Google Doc...")
        append_story_to_doc(
            doc_id=doc_id,
            lesson_title=lesson['title'],
            story=result['story'],
            translation=result.get('translation', ''),
            exercises=result.get('exercises', []),
            insert_index=lesson['insert_index'],
            image_url=image_url,
        )

        # Send to student's Telegram if this is a /make flow
        if student and student.get('chat_id'):
            story_preview = result['story'][:220].rsplit(' ', 1)[0] + '...'
            await context.bot.send_photo(
                chat_id=student['chat_id'],
                photo=image_url,
                caption=f"*{lesson['title']}*\n\n_{story_preview}_",
                parse_mode='Markdown'
            )
            await context.bot.send_voice(
                chat_id=student['chat_id'],
                voice=audio_buffer,
                caption="Listen to your story",
            )
            audio_buffer.seek(0)  # reset for teacher preview below

        # Send cover image + voice to teacher as confirmation
        story_preview = result['story'][:220].rsplit(' ', 1)[0] + '...'
        await query.message.reply_photo(
            photo=image_url,
            caption=f"*{lesson['title']}*\n\n_{story_preview}_",
            parse_mode='Markdown'
        )
        await query.message.reply_voice(
            voice=audio_buffer,
            caption="Voiceover",
        )

        doc_link = f"https://docs.google.com/document/d/{doc_id}"
        recipient = f"Sent to {student['name']}!" if student else "Saved to your doc."
        await query.edit_message_text(
            f"Done! {recipient}\n\n[Open Google Doc]({doc_link})",
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Generation error: {e}", exc_info=True)
        await query.edit_message_text(f"Something went wrong:\n\n`{e}`", parse_mode='Markdown')

    return ConversationHandler.END


# ──────────────────────────────────────────────
# /make  (student delivery flow)
# ──────────────────────────────────────────────

async def make(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from google_sheets import get_all_students

    msg = await update.message.reply_text("Loading student list...")

    try:
        students = get_all_students()
        context.user_data['students'] = {s['name']: s for s in students}

        keyboard = [
            [InlineKeyboardButton(s['name'], callback_data=f"student_{s['name']}")]
            for s in students
        ]
        await msg.edit_text(
            "Which student?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return PICK_STUDENT

    except Exception as e:
        logger.error(f"Error loading students: {e}", exc_info=True)
        await msg.edit_text(f"Could not load students.\n\n`{e}`", parse_mode='Markdown')
        return ConversationHandler.END


async def student_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    name = query.data.replace('student_', '')
    student = context.user_data['students'].get(name)
    if not student:
        await query.edit_message_text("Student not found. Try /make again.")
        return ConversationHandler.END

    # Load student's Google Doc
    from google_docs import get_latest_lesson
    try:
        lesson = get_latest_lesson(student['doc_id'])
    except Exception as e:
        await query.edit_message_text(f"Could not read {name}'s doc.\n\n`{e}`", parse_mode='Markdown')
        return ConversationHandler.END

    context.user_data['lesson']  = lesson
    context.user_data['student'] = student

    preview = '\n'.join(f"- {p}" for p in lesson['phrases'][:6])
    if len(lesson['phrases']) > 6:
        preview += f"\n  (+{len(lesson['phrases']) - 6} more)"

    await query.edit_message_text(
        f"*{student['name']}* - {student['level']} - {student['language']}\n"
        f"Interests: {student['interests']}\n\n"
        f"*{lesson['title']}*\n\n{preview}\n\nChoose a genre:",
        parse_mode='Markdown',
        reply_markup=make_keyboard(GENRES, 'makegenre_')
    )
    return MAKE_GENRE


async def make_genre_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace('makegenre_', '')
    context.user_data['genre'] = key
    await query.edit_message_text(
        f"{GENRES[key]} chosen.\n\nChoose a setting:",
        reply_markup=make_keyboard(SETTINGS, 'makesetting_')
    )
    return MAKE_SETTING


async def make_setting_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace('makesetting_', '')
    context.user_data['setting'] = key
    await query.edit_message_text(
        f"{GENRES[context.user_data['genre']]} / {SETTINGS[key]}\n\nWho is the protagonist?",
        reply_markup=make_keyboard(PROTAGONISTS, 'makeprot_')
    )
    return MAKE_PROTAGONIST


async def make_protagonist_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace('makeprot_', '')
    context.user_data['protagonist'] = key
    # Reuse the same generation logic
    await protagonist_chosen(update, context)
    return ConversationHandler.END


# ──────────────────────────────────────────────
# /cancel
# ──────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set.")

    app = Application.builder().token(token).build()

    # /generate — teacher's own doc
    generate_conv = ConversationHandler(
        entry_points=[CommandHandler('generate', generate)],
        states={
            GENRE:       [CallbackQueryHandler(genre_chosen,       pattern='^genre_')],
            SETTING:     [CallbackQueryHandler(setting_chosen,     pattern='^setting_')],
            PROTAGONIST: [CallbackQueryHandler(protagonist_chosen, pattern='^prot_')],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False,
    )

    # /make — student delivery
    make_conv = ConversationHandler(
        entry_points=[CommandHandler('make', make)],
        states={
            PICK_STUDENT:    [CallbackQueryHandler(student_chosen,         pattern='^student_')],
            MAKE_GENRE:      [CallbackQueryHandler(make_genre_chosen,      pattern='^makegenre_')],
            MAKE_SETTING:    [CallbackQueryHandler(make_setting_chosen,    pattern='^makesetting_')],
            MAKE_PROTAGONIST:[CallbackQueryHandler(make_protagonist_chosen, pattern='^makeprot_')],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False,
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(generate_conv)
    app.add_handler(make_conv)

    logger.info("Bot started - polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
