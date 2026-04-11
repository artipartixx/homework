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
    'citta':  'Citta',
    'natura': 'Natura',
    'scuola': 'Scuola',
    'spazio': 'Spazio',
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
        f"Your chat ID is: <code>{chat_id}</code>\n"
        f"(Give this to your teacher to add you to the student list)\n\n"
        f"/generate - create a story for your own doc\n"
        f"/make - create and send a story to a student",
        parse_mode='HTML'
    )


# ──────────────────────────────────────────────
# Shared generation logic
# ──────────────────────────────────────────────

async def run_generation(query, context):
    """Core generation used by both /generate and /make flows."""
    from story_generator import (
        generate_story_and_exercises, generate_cover_image,
        generate_voiceover, format_for_telegram
    )
    from google_docs import append_story_to_doc

    lesson  = context.user_data['lesson']
    student = context.user_data.get('student')
    doc_id  = student['doc_id'] if student else os.getenv('GOOGLE_DOC_ID')

    await query.edit_message_text("Writing the story...")

    result = generate_story_and_exercises(
        phrases=lesson['phrases'],
        genre=context.user_data['genre'],
        setting=context.user_data['setting'],
        protagonist=context.user_data['protagonist'],
        student=student,
    )

    await query.edit_message_text("Generating cover image...")
    image_url = generate_cover_image(
        image_prompt=result.get('image_prompt', 'A warm scene'),
        genre=context.user_data['genre'],
        setting=context.user_data['setting'],
    )

    await query.edit_message_text("Recording voiceover...")
    # Voiceover uses the full plain story (strip ** bold markers)
    plain_story = result['story'].replace('**', '')
    audio_buffer = generate_voiceover(plain_story)

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

    # Format story as parallel text for Telegram
    chunks = result.get('chunks', [])
    telegram_messages = format_for_telegram(lesson['title'], chunks)

    # Send to student
    if student and student.get('chat_id'):
        # Cover image first
        await context.bot.send_photo(
            chat_id=student['chat_id'],
            photo=image_url,
        )
        # Parallel text story
        for msg_text in telegram_messages:
            await context.bot.send_message(
                chat_id=student['chat_id'],
                text=msg_text,
                parse_mode='HTML'
            )
        # Voiceover
        await context.bot.send_voice(
            chat_id=student['chat_id'],
            voice=audio_buffer,
        )
        audio_buffer.seek(0)

    # Confirm to teacher with doc link
    doc_link = f"https://docs.google.com/document/d/{doc_id}"
    recipient = f"Sent to {student['name']}!" if student else "Saved to your doc."
    await query.edit_message_text(
        f"{recipient}\n\n<a href='{doc_link}'>Open Google Doc</a>",
        parse_mode='HTML'
    )


# ──────────────────────────────────────────────
# /generate  (teacher's own doc)
# ──────────────────────────────────────────────

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from google_docs import get_latest_lesson

    msg = await update.message.reply_text("Reading your Google Doc...")

    try:
        lesson = get_latest_lesson(os.getenv('GOOGLE_DOC_ID'))
        context.user_data['lesson']  = lesson
        context.user_data['student'] = None

        preview = '\n'.join(f"- {p}" for p in lesson['phrases'][:6])
        if len(lesson['phrases']) > 6:
            preview += f"\n  (+{len(lesson['phrases']) - 6} more)"

        await msg.edit_text(
            f"<b>{lesson['title']}</b>\n\n{preview}\n\nChoose a genre:",
            parse_mode='HTML',
            reply_markup=make_keyboard(GENRES, 'genre_')
        )
        return GENRE

    except Exception as e:
        logger.error(f"Error in /generate: {e}", exc_info=True)
        await msg.edit_text(f"Could not read the doc.\n\n<code>{e}</code>", parse_mode='HTML')
        return ConversationHandler.END


async def genre_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace('genre_', '')
    context.user_data['genre'] = key
    await query.edit_message_text(
        f"{GENRES[key]} chosen. Choose a setting:",
        reply_markup=make_keyboard(SETTINGS, 'setting_')
    )
    return SETTING


async def setting_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace('setting_', '')
    context.user_data['setting'] = key
    await query.edit_message_text(
        f"{GENRES[context.user_data['genre']]} / {SETTINGS[key]}. Who is the protagonist?",
        reply_markup=make_keyboard(PROTAGONISTS, 'prot_')
    )
    return PROTAGONIST


async def protagonist_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['protagonist'] = query.data.replace('prot_', '')
    try:
        await run_generation(query, context)
    except Exception as e:
        logger.error(f"Generation error: {e}", exc_info=True)
        await query.edit_message_text(f"Something went wrong:\n\n<code>{e}</code>", parse_mode='HTML')
    return ConversationHandler.END


# ──────────────────────────────────────────────
# /make  (student delivery)
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
        await msg.edit_text("Which student?", reply_markup=InlineKeyboardMarkup(keyboard))
        return PICK_STUDENT

    except Exception as e:
        logger.error(f"Error loading students: {e}", exc_info=True)
        await msg.edit_text(f"Could not load students.\n\n<code>{e}</code>", parse_mode='HTML')
        return ConversationHandler.END


async def student_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    name    = query.data.replace('student_', '')
    student = context.user_data['students'].get(name)
    if not student:
        await query.edit_message_text("Student not found. Try /make again.")
        return ConversationHandler.END

    from google_docs import get_latest_lesson
    try:
        lesson = get_latest_lesson(student['doc_id'])
    except Exception as e:
        await query.edit_message_text(
            f"Could not read {name}'s doc.\n\n<code>{e}</code>", parse_mode='HTML'
        )
        return ConversationHandler.END

    context.user_data['lesson']  = lesson
    context.user_data['student'] = student

    preview = '\n'.join(f"- {p}" for p in lesson['phrases'][:6])
    if len(lesson['phrases']) > 6:
        preview += f"\n  (+{len(lesson['phrases']) - 6} more)"

    await query.edit_message_text(
        f"<b>{student['name']}</b> - {student['level']} - {student['language']}\n"
        f"Interests: {student['interests']}\n\n"
        f"<b>{lesson['title']}</b>\n\n{preview}\n\nChoose a genre:",
        parse_mode='HTML',
        reply_markup=make_keyboard(GENRES, 'makegenre_')
    )
    return MAKE_GENRE


async def make_genre_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace('makegenre_', '')
    context.user_data['genre'] = key
    await query.edit_message_text(
        f"{GENRES[key]} chosen. Choose a setting:",
        reply_markup=make_keyboard(SETTINGS, 'makesetting_')
    )
    return MAKE_SETTING


async def make_setting_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace('makesetting_', '')
    context.user_data['setting'] = key
    await query.edit_message_text(
        f"{GENRES[context.user_data['genre']]} / {SETTINGS[key]}. Who is the protagonist?",
        reply_markup=make_keyboard(PROTAGONISTS, 'makeprot_')
    )
    return MAKE_PROTAGONIST


async def make_protagonist_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['protagonist'] = query.data.replace('makeprot_', '')
    try:
        await run_generation(query, context)
    except Exception as e:
        logger.error(f"Generation error: {e}", exc_info=True)
        await query.edit_message_text(f"Something went wrong:\n\n<code>{e}</code>", parse_mode='HTML')
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

    make_conv = ConversationHandler(
        entry_points=[CommandHandler('make', make)],
        states={
            PICK_STUDENT:     [CallbackQueryHandler(student_chosen,          pattern='^student_')],
            MAKE_GENRE:       [CallbackQueryHandler(make_genre_chosen,       pattern='^makegenre_')],
            MAKE_SETTING:     [CallbackQueryHandler(make_setting_chosen,     pattern='^makesetting_')],
            MAKE_PROTAGONIST: [CallbackQueryHandler(make_protagonist_chosen, pattern='^makeprot_')],
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
