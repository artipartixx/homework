import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
)

from story_generator import StoryGenerator, DIALOGUE_TOPICS, ARTICLE_TOPICS
from google_docs import get_latest_lesson, append_story_to_doc
from google_sheets import get_all_students

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env
# ---------------------------------------------------------------------------

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GOOGLE_DOC_ID = os.getenv('GOOGLE_DOC_ID')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')

generator = StoryGenerator(ANTHROPIC_API_KEY, OPENAI_API_KEY)

# ---------------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------------

# /generate (teacher, own doc)
GENRE, SETTING, PROTAGONIST, DIALOGUE_TOPIC, ARTICLE_TOPIC = range(5)

# /make (student delivery)
PICK_STUDENT, MAKE_GENRE, MAKE_SETTING, MAKE_PROTAGONIST, MAKE_DIALOGUE_TOPIC, MAKE_ARTICLE_TOPIC = range(5, 11)

# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

STORY_GENRES = [
    ('Romantico', 'romantico'),
    ('Thriller', 'thriller'),
    ('Commedia', 'commedia'),
    ('Drammatico', 'drammatico'),
    ('Avventura', 'avventura'),
    ('Mistero', 'mistero'),
    ('Dialogo quotidiano', 'dialogo'),
    ('Articolo culturale', 'articolo'),
]

SETTINGS = [
    ('Milano moderna', 'Milano moderna'),
    ('Piccolo paese del sud', 'un piccolo paese del sud Italia'),
    ('Roma storica', 'Roma storica'),
    ('Campagna toscana', 'la campagna toscana'),
    ('Porto ligure', 'un porto ligure'),
    ('Universita', "un'universita italiana"),
]

PROTAGONISTS = [
    ('Uomo', 'un uomo'),
    ('Donna', 'una donna'),
    ('Coppia', 'una coppia'),
    ('Gruppo di amici', 'un gruppo di amici'),
    ('Anziano/a', 'un anziano o una anziana'),
    ('Adolescente', 'un adolescente'),
]

# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def genre_keyboard():
    buttons = []
    row = []
    for label, val in STORY_GENRES:
        row.append(InlineKeyboardButton(label, callback_data=val))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def setting_keyboard():
    buttons = [[InlineKeyboardButton(label, callback_data=val)] for label, val in SETTINGS]
    return InlineKeyboardMarkup(buttons)


def protagonist_keyboard():
    buttons = []
    row = []
    for label, val in PROTAGONISTS:
        row.append(InlineKeyboardButton(label, callback_data=val))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def dialogue_topic_keyboard(student_interests=None):
    topics = list(DIALOGUE_TOPICS)
    if student_interests:
        interests_lower = student_interests.lower()
        keywords = [k.strip() for k in interests_lower.split(',')]
        prioritized = [t for t in topics if any(k in t.lower() for k in keywords)]
        rest = [t for t in topics if t not in prioritized]
        topics = prioritized + rest
    buttons = [[InlineKeyboardButton(t.capitalize(), callback_data=f'dtopic:{t}')] for t in topics]
    return InlineKeyboardMarkup(buttons)


def article_topic_keyboard():
    buttons = [[InlineKeyboardButton(t.capitalize(), callback_data=f'atopic:{t}')] for t in ARTICLE_TOPICS]
    return InlineKeyboardMarkup(buttons)


# ---------------------------------------------------------------------------
# Shared generation pipeline
# ---------------------------------------------------------------------------

async def run_generation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    doc_id: str,
    student: dict = None,
):
    query = update.callback_query
    genre = context.user_data.get('genre', '')
    setting = context.user_data.get('setting', '')
    protagonist = context.user_data.get('protagonist', '')
    topic = context.user_data.get('topic', '')

    student_name = student['name'] if student else None
    native_language = student.get('language', 'Russian') if student else 'Russian'

    await query.edit_message_text('Leggo le note della lezione...')

    try:
        lesson_data = get_latest_lesson(doc_id)
        phrases = lesson_data['phrases']
        insert_index = lesson_data['insert_index']
        lesson_title = lesson_data['title']
    except Exception as e:
        await query.edit_message_text(f'Errore nel leggere il doc: {e}')
        return ConversationHandler.END

    if not phrases:
        await query.edit_message_text('Nessuna frase trovata nella lezione.')
        return ConversationHandler.END

    await query.edit_message_text(f'Genero il contenuto per "{lesson_title}"...')

    try:
        if genre == 'dialogo':
            result = await generator.generate_dialogue(
                phrases,
                topic,
                student_name=student_name,
                native_language=native_language,
            )
        elif genre == 'articolo':
            result = await generator.generate_article(
                phrases,
                topic,
                student_name=student_name,
                native_language=native_language,
            )
        else:
            result = await generator.generate_story_and_exercises(
                phrases,
                genre,
                setting,
                protagonist,
                student_name=student_name,
                native_language=native_language,
            )
    except Exception as e:
        logger.error(f'Generation error: {e}')
        await query.edit_message_text(f'Errore nella generazione: {e}')
        return ConversationHandler.END

    await query.edit_message_text('Genero immagine di copertina...')
    image_url = None
    try:
        image_url = generator.generate_cover_image(result)
    except Exception as e:
        logger.warning(f'Cover image failed: {e}')

    await query.edit_message_text('Genero voiceover...')
    audio = None
    try:
        audio = generator.generate_voiceover(result)
    except Exception as e:
        logger.warning(f'Voiceover failed: {e}')

    await query.edit_message_text('Salvo nel Google Doc...')
    try:
        append_story_to_doc(doc_id, result, insert_index, image_url)
    except Exception as e:
        logger.warning(f'Doc append failed: {e}')

    # Determine destination chat
    chat_id = update.effective_chat.id
    if student and student.get('chat_id'):
        try:
            chat_id = int(student['chat_id'])
        except (ValueError, TypeError):
            pass

    bot = context.bot
    messages = generator.format_for_telegram(result)

    # Send cover image
    if image_url:
        try:
            await bot.send_photo(chat_id=chat_id, photo=image_url)
        except Exception as e:
            logger.warning(f'Photo send failed: {e}')

    # Send text (parallel format)
    for msg in messages:
        try:
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
        except Exception as e:
            logger.warning(f'Message send failed: {e}')

    # Send voiceover
    if audio:
        try:
            await bot.send_audio(
                chat_id=chat_id,
                audio=audio,
                filename=f"{result.get('title', 'storia')}.mp3",
                title=result.get('title', 'Storia'),
            )
        except Exception as e:
            logger.warning(f'Audio send failed: {e}')

    await query.edit_message_text('Fatto!')
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f'Ciao! Il tuo chat ID e: <code>{chat_id}</code>\n\n'
        f'Condividilo con il tuo insegnante per ricevere i contenuti.',
        parse_mode='HTML',
    )


# ---------------------------------------------------------------------------
# /generate — teacher, own doc
# ---------------------------------------------------------------------------

async def generate_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        'Che tipo di contenuto genero?',
        reply_markup=genre_keyboard(),
    )
    return GENRE


async def generate_genre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    genre = query.data
    context.user_data['genre'] = genre

    if genre == 'dialogo':
        await query.edit_message_text(
            'Scegli il contesto del dialogo:',
            reply_markup=dialogue_topic_keyboard(),
        )
        return DIALOGUE_TOPIC

    if genre == 'articolo':
        await query.edit_message_text(
            "Scegli il tema dell'articolo:",
            reply_markup=article_topic_keyboard(),
        )
        return ARTICLE_TOPIC

    await query.edit_message_text(
        'Dove si svolge la storia?',
        reply_markup=setting_keyboard(),
    )
    return SETTING


async def generate_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['setting'] = query.data
    await query.edit_message_text(
        'Chi e il protagonista?',
        reply_markup=protagonist_keyboard(),
    )
    return PROTAGONIST


async def generate_protagonist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['protagonist'] = query.data
    context.user_data['topic'] = ''
    return await run_generation(update, context, GOOGLE_DOC_ID)


async def generate_dialogue_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['topic'] = query.data.replace('dtopic:', '')
    context.user_data['setting'] = ''
    context.user_data['protagonist'] = ''
    return await run_generation(update, context, GOOGLE_DOC_ID)


async def generate_article_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['topic'] = query.data.replace('atopic:', '')
    context.user_data['setting'] = ''
    context.user_data['protagonist'] = ''
    return await run_generation(update, context, GOOGLE_DOC_ID)


# ---------------------------------------------------------------------------
# /make — student delivery
# ---------------------------------------------------------------------------

async def make_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    try:
        students = get_all_students(GOOGLE_SHEET_ID)
    except Exception as e:
        await update.message.reply_text(f'Errore nel leggere gli studenti: {e}')
        return ConversationHandler.END

    if not students:
        await update.message.reply_text('Nessuno studente trovato nel foglio.')
        return ConversationHandler.END

    context.user_data['students'] = students
    buttons = [
        [InlineKeyboardButton(s['name'], callback_data=f'student:{s["name"]}')]
        for s in students
    ]
    await update.message.reply_text(
        'Per quale studente genero il contenuto?',
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return PICK_STUDENT


async def make_pick_student(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    name = query.data.replace('student:', '')
    students = context.user_data.get('students', [])
    student = next((s for s in students if s['name'] == name), None)

    if not student:
        await query.edit_message_text('Studente non trovato.')
        return ConversationHandler.END

    context.user_data['student'] = student
    await query.edit_message_text(
        f'Genero per {name}. Che tipo di contenuto?',
        reply_markup=genre_keyboard(),
    )
    return MAKE_GENRE


async def make_genre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    genre = query.data
    context.user_data['genre'] = genre
    student = context.user_data.get('student', {})

    if genre == 'dialogo':
        interests = student.get('interests', '')
        await query.edit_message_text(
            'Scegli il contesto del dialogo:',
            reply_markup=dialogue_topic_keyboard(student_interests=interests),
        )
        return MAKE_DIALOGUE_TOPIC

    if genre == 'articolo':
        await query.edit_message_text(
            "Scegli il tema dell'articolo:",
            reply_markup=article_topic_keyboard(),
        )
        return MAKE_ARTICLE_TOPIC

    await query.edit_message_text(
        'Dove si svolge la storia?',
        reply_markup=setting_keyboard(),
    )
    return MAKE_SETTING


async def make_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['setting'] = query.data
    await query.edit_message_text(
        'Chi e il protagonista?',
        reply_markup=protagonist_keyboard(),
    )
    return MAKE_PROTAGONIST


async def make_protagonist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['protagonist'] = query.data
    context.user_data['topic'] = ''
    student = context.user_data.get('student', {})
    doc_id = student.get('doc_id') or GOOGLE_DOC_ID
    return await run_generation(update, context, doc_id, student=student)


async def make_dialogue_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['topic'] = query.data.replace('dtopic:', '')
    context.user_data['setting'] = ''
    context.user_data['protagonist'] = ''
    student = context.user_data.get('student', {})
    doc_id = student.get('doc_id') or GOOGLE_DOC_ID
    return await run_generation(update, context, doc_id, student=student)


async def make_article_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['topic'] = query.data.replace('atopic:', '')
    context.user_data['setting'] = ''
    context.user_data['protagonist'] = ''
    student = context.user_data.get('student', {})
    doc_id = student.get('doc_id') or GOOGLE_DOC_ID
    return await run_generation(update, context, doc_id, student=student)


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Operazione annullata.')
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler('start', start))

    generate_handler = ConversationHandler(
        entry_points=[CommandHandler('generate', generate_start)],
        states={
            GENRE:          [CallbackQueryHandler(generate_genre)],
            SETTING:        [CallbackQueryHandler(generate_setting)],
            PROTAGONIST:    [CallbackQueryHandler(generate_protagonist)],
            DIALOGUE_TOPIC: [CallbackQueryHandler(generate_dialogue_topic, pattern=r'^dtopic:')],
            ARTICLE_TOPIC:  [CallbackQueryHandler(generate_article_topic, pattern=r'^atopic:')],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    make_handler = ConversationHandler(
        entry_points=[CommandHandler('make', make_start)],
        states={
            PICK_STUDENT:        [CallbackQueryHandler(make_pick_student, pattern=r'^student:')],
            MAKE_GENRE:          [CallbackQueryHandler(make_genre)],
            MAKE_SETTING:        [CallbackQueryHandler(make_setting)],
            MAKE_PROTAGONIST:    [CallbackQueryHandler(make_protagonist)],
            MAKE_DIALOGUE_TOPIC: [CallbackQueryHandler(make_dialogue_topic, pattern=r'^dtopic:')],
            MAKE_ARTICLE_TOPIC:  [CallbackQueryHandler(make_article_topic, pattern=r'^atopic:')],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    app.add_handler(generate_handler)
    app.add_handler(make_handler)

    logger.info('Bot started.')
    app.run_polling()


if __name__ == '__main__':
    main()
