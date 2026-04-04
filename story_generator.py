import os
import json
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))


def generate_story_and_exercises(
    phrases: list[str],
    genre: str,
    setting: str,
    protagonist: str,
) -> dict:
    """
    Calls GPT-4o to generate an Italian story using the lesson phrases,
    a Russian translation, fill-in-the-blank exercises, and an image prompt.

    Returns a dict with keys: story, translation, exercises, image_prompt.
    """
    phrases_block = '\n'.join(f'• {p}' for p in phrases)

    system = (
        "You are an expert Italian language teacher. "
        "You create short, engaging stories that help adult learners practise vocabulary in context. "
        "You always use modern, natural Italian."
    )

    user = f"""Here are phrases from my student's most recent Italian lesson:

{phrases_block}

Please create the following materials. Return ONLY valid JSON with these exact keys.

1. "story" — A short story in Italian (200–260 words).
   - Genre: {genre}
   - Setting: {setting}
   - Protagonist: {protagonist}
   - Naturally use EVERY phrase listed above (bold each one like **phrase** when it appears).
   - Keep language appropriate for an intermediate adult learner.

2. "translation" — Full Russian translation of the story (for the student's reference).

3. "exercises" — A list of exactly 5 fill-in-the-blank sentences in Italian.
   Each sentence should test one of the lesson phrases. Format each item as:
   "Marco non è mai stato a Parigi, ma _____ visitarla un giorno. (risposta: vorrebbe)"

4. "image_prompt" — One sentence in English describing the key visual scene of the story,
   suitable for an image generation model. Do NOT mention text, words, or letters.

Return only the JSON object, no extra commentary."""

    response = client.chat.completions.create(
        model='gpt-4o',
        messages=[
            {'role': 'system', 'content': system},
            {'role': 'user',   'content': user},
        ],
        response_format={'type': 'json_object'},
        temperature=0.85,
    )

    result = json.loads(response.choices[0].message.content)
    logger.info("Story generated successfully.")
    return result


def generate_cover_image(image_prompt: str, genre: str, setting: str) -> str:
    """
    Calls DALL-E 3 to generate a cover illustration.
    Returns the image URL (valid for ~1 hour).
    """
    full_prompt = (
        f"Colorful, warm illustration for an Italian language learning story. "
        f"{image_prompt}. "
        f"Style: vibrant editorial illustration, slightly whimsical, like a modern travel book. "
        f"Rich Mediterranean colours. Absolutely no text, letters, or words in the image."
    )

    response = client.images.generate(
        model='dall-e-3',
        prompt=full_prompt,
        size='1024x1024',
        quality='standard',
        n=1,
    )

    url = response.data[0].url
    logger.info("Cover image generated.")
    return url
