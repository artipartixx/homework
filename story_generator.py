import os
import io
import json
import random
import logging
import anthropic
from openai import OpenAI

logger = logging.getLogger(__name__)

claude_client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

NARRATIVE_ARCS = [
    "Hero faces external obstacle, fails once, succeeds through inner change",
    "Two characters want opposite things and must compromise",
    "Character discovers something that forces them to choose between two values",
    "Ordinary person stumbles into an extraordinary situation and must adapt",
]

CONFLICT_TYPES = [
    "Person vs person",
    "Person vs system or society",
    "Person vs themselves (internal struggle)",
    "Person vs nature or environment",
]

CHARACTER_ARCHETYPES = [
    "The reluctant expert: knows how to fix it but doesn't want to",
    "The outsider who sees clearly what others miss",
    "The believer whose faith is tested",
    "The pragmatist forced to act on principle",
]


def generate_story_and_exercises(phrases, genre, setting, protagonist, student=None):
    arc       = random.choice(NARRATIVE_ARCS)
    conflict  = random.choice(CONFLICT_TYPES)
    archetype = random.choice(CHARACTER_ARCHETYPES)

    logger.info(f"Arc: {arc} | Conflict: {conflict} | Archetype: {archetype}")

    phrases_block = '\n'.join('- ' + p for p in phrases)

    if student:
        student_block = (
            f"\nSTUDENT PROFILE:\n"
            f"- Name: {student['name']}\n"
            f"- Language being learned: {student['language']}\n"
            f"- Level: {student['level']}\n"
            f"- Interests: {student['interests']}\n\n"
            f"Tailor the story to this student: use their interests to inspire the setting "
            f"and character details, calibrate vocabulary complexity to their level, "
            f"and use the most relevant phrases prominently.\n"
        )
        native_language = student.get('native_language', 'Russian')
        language = student['language']
    else:
        student_block = ""
        native_language = 'Russian'
        language = 'Italian'

    prompt = (
        f"You are a skilled {language} author writing short literary fiction for language learners.\n\n"
        f"STORY PARAMETERS:\n"
        f"- Genre: {genre}\n"
        f"- Setting: {setting}\n"
        f"- Protagonist type: {protagonist}\n"
        f"- Narrative arc: {arc}\n"
        f"- Conflict type: {conflict}\n"
        f"- Character archetype: {archetype}\n"
        + student_block +
        f"VOCABULARY TO INCORPORATE:\n"
        f"{phrases_block}\n\n"
        f"GRAMMAR RULES (strict):\n"
        f"- Write in presente or imperfetto only. Never use passato remoto.\n"
        f"- Write in third person. Adapt phrases to match: 'ne vado fiero' becomes 'ne va fiero', "
        f"'per conto mio' becomes 'per conto suo', etc.\n"
        f"- Do NOT copy every phrase verbatim. If a phrase is a grammar example or conjugation, "
        f"demonstrate the concept naturally.\n"
        f"- Use 12-18 of the most interesting phrases. Quality over quantity.\n\n"
        f"PROSE QUALITY RULES (strict):\n"
        f"- Specificity: name real places, objects, sensations.\n"
        f"- Show don't tell: never use adjectives to describe emotion.\n"
        f"- One central image: choose one concrete visual metaphor and return to it at least twice.\n"
        f"- Subtext in dialogue: characters never say exactly what they mean.\n"
        f"- Bold each incorporated lesson phrase like **phrase**.\n\n"
        f"OUTPUT FORMAT:\n"
        f"Return ONLY a raw JSON object - no markdown, no code fences - with these keys:\n\n"
        f"- \"chunks\": an array of objects, each with:\n"
        f"    - \"italian\": exactly 3-4 lines of the story (one sentence per line)\n"
        f"    - \"translation\": the {native_language} translation of those exact lines (one per line, matching order)\n"
        f"  The chunks together form the complete story in order. Aim for 6-8 chunks total.\n\n"
        f"- \"story\": the full story as one continuous block in {language} "
        f"(for saving to Google Doc, with **bolded** phrases, no chunk breaks)\n\n"
        f"- \"exercises\": list of 5 fill-in-the-blank sentences in {language}, "
        f"format: \"Sentence _____ gap. (risposta: answer)\"\n\n"
        f"- \"image_prompt\": one English sentence describing the key visual scene, no text in image"
    )

    response = claude_client.messages.create(
        model='claude-sonnet-4-6',
        max_tokens=3000,
        messages=[{'role': 'user', 'content': prompt}],
    )

    raw = response.content[0].text.strip()

    if raw.startswith('```'):
        raw = raw.split('```')[1]
        if raw.startswith('json'):
            raw = raw[4:]
        raw = raw.strip()

    result = json.loads(raw)
    result['arc']       = arc
    result['conflict']  = conflict
    result['archetype'] = archetype

    logger.info("Story generated with Claude.")
    return result


def format_for_telegram(lesson_title, chunks):
    """
    Formats the story as parallel text for Telegram.
    3-4 lines of story, then translation in italics, separated by dividers.
    Returns a list of message strings (split if too long for one message).
    """
    divider = "\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
    header = f"<b>{lesson_title}</b>\n"

    blocks = []
    for chunk in chunks:
        italian     = chunk.get('italian', '').strip()
        translation = chunk.get('translation', '').strip()
        # Wrap each translation line in italic
        translation_italic = '\n'.join(
            f"<i>{line}</i>" for line in translation.split('\n') if line.strip()
        )
        blocks.append(f"{italian}\n\n{translation_italic}")

    full_text = header + "\n" + divider.join(blocks)

    # Split into multiple messages if over Telegram's 4096 char limit
    messages = []
    if len(full_text) <= 4096:
        messages.append(full_text)
    else:
        # Send header + first few chunks, then continue
        current = header + "\n"
        for i, block in enumerate(blocks):
            chunk_text = (divider if i > 0 else "") + block
            if len(current) + len(chunk_text) > 4096:
                messages.append(current)
                current = block
            else:
                current += chunk_text
        if current:
            messages.append(current)

    return messages


def generate_cover_image(image_prompt, genre, setting):
    full_prompt = (
        "Colorful warm illustration for a language learning story. "
        + image_prompt
        + ". Style: vibrant editorial illustration, slightly whimsical, like a modern travel book. "
        "Rich warm colours. Absolutely no text, letters, or words in the image."
    )

    response = openai_client.images.generate(
        model='dall-e-3',
        prompt=full_prompt,
        size='1024x1024',
        quality='standard',
        n=1,
    )

    url = response.data[0].url
    logger.info("Cover image generated with DALL-E 3.")
    return url


def generate_voiceover(text):
    response = openai_client.audio.speech.create(
        model='tts-1',
        voice='nova',
        input=text,
    )

    buffer = io.BytesIO()
    for chunk in response.iter_bytes():
        buffer.write(chunk)
    buffer.seek(0)

    logger.info("Voiceover generated with OpenAI TTS.")
    return buffer
