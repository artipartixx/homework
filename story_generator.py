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

# --- Story architecture elements (randomly selected per generation) ---

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


def generate_story_and_exercises(phrases, genre, setting, protagonist):
    # Randomly select one of each — done in Python, not left to the model
    arc       = random.choice(NARRATIVE_ARCS)
    conflict  = random.choice(CONFLICT_TYPES)
    archetype = random.choice(CHARACTER_ARCHETYPES)

    logger.info(f"Story arc: {arc} | Conflict: {conflict} | Archetype: {archetype}")

    phrases_block = '\n'.join('- ' + p for p in phrases)

    prompt = f"""You are a skilled Italian author writing short literary fiction for language learners.

STORY PARAMETERS (you must follow all of these):
- Genre: {genre}
- Setting: {setting}
- Protagonist type: {protagonist}
- Narrative arc: {arc}
- Conflict type: {conflict}
- Character archetype: {archetype}

VOCABULARY TO INCORPORATE:
{phrases_block}

GRAMMAR RULES (strict):
- Write entirely in the present tense (presente) or imperfect (imperfetto). Never use passato remoto.
- The story is in third person. Adapt all phrases to match: "ne vado fiero" becomes "ne va fiero", "per conto mio" becomes "per conto suo", etc.
- You do NOT need to use every phrase verbatim. If a phrase is a grammar example or conjugation pattern, demonstrate the concept naturally instead of quoting it.
- Aim to use 12-18 of the most interesting phrases. Quality over quantity.

PROSE QUALITY RULES (strict):
- Specificity: name real places, objects, sensations. Not "a bar" but "a bar with chipped formica tables and a radio stuck on a football channel". Not "she was nervous" but "she kept folding and unfolding the receipt in her pocket".
- Show don't tell: NEVER use adjectives to describe a character's emotion. Show it through action, gesture, or dialogue instead.
- One central image: choose one concrete visual metaphor and return to it at least twice.
- Subtext in dialogue: characters never say exactly what they mean. They talk around it.
- Bold each incorporated lesson phrase like **phrase** when it appears in the story.

STATE YOUR CHOICES at the very top of the "story" field like this:
[Arc: ... | Conflict: ... | Archetype: ... | Central image: ...]
Then write the story (200-260 words).

Return ONLY a raw JSON object with these keys - no markdown, no code fences:
- "story": the story in Italian including the choices header
- "translation": full Russian translation (no header needed)
- "exercises": list of 5 fill-in-the-blank sentences in Italian, format: "Sentence with _____ gap. (risposta: answer)"
- "image_prompt": one English sentence describing the key visual scene, no text or letters in image"""

    response = claude_client.messages.create(
        model='claude-sonnet-4-6',
        max_tokens=2048,
        messages=[{'role': 'user', 'content': prompt}],
    )

    raw = response.content[0].text.strip()

    # Strip markdown code fences if Claude adds them anyway
    if raw.startswith('```'):
        raw = raw.split('```')[1]
        if raw.startswith('json'):
            raw = raw[4:]
        raw = raw.strip()

    result = json.loads(raw)

    # Attach the selected parameters so bot.py can log/display them
    result['arc']       = arc
    result['conflict']  = conflict
    result['archetype'] = archetype

    logger.info("Story generated with Claude.")
    return result


def generate_cover_image(image_prompt, genre, setting):
    full_prompt = (
        "Colorful warm illustration for an Italian language learning story. "
        + image_prompt
        + ". Style: vibrant editorial illustration, slightly whimsical, like a modern travel book. "
        "Rich Mediterranean colours. Absolutely no text, letters, or words in the image."
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
