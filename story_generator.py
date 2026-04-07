import os
import io
import json
import logging
import anthropic
from openai import OpenAI

logger = logging.getLogger(__name__)

# Claude for story generation
claude_client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

# OpenAI only for DALL-E image generation
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))


def generate_story_and_exercises(phrases, genre, setting, protagonist):
    phrases_block = '\n'.join('- ' + p for p in phrases)

    system = (
        "You are an expert Italian language teacher. "
        "You create short, engaging stories that help adult learners practise vocabulary in context. "
        "You always use modern, natural Italian. "
        "You always respond with valid JSON only - no extra text, no markdown, no code blocks."
    )

    user = (
        "Here are phrases from my student's most recent Italian lesson:\n\n"
        + phrases_block
        + "\n\nCreate the following materials and return them as a single JSON object with these exact keys:\n\n"
        "1. \"story\" - A short story in Italian (200-260 words).\n"
        "   - Genre: " + genre + "\n"
        "   - Setting: " + setting + "\n"
        "   - Protagonist: " + protagonist + "\n"
        "   - Naturally use EVERY phrase listed above (bold each one like **phrase** when it appears).\n"
        "   - Keep language appropriate for an intermediate adult learner.\n\n"
        "2. \"translation\" - Full Russian translation of the story.\n\n"
        "3. \"exercises\" - A list of exactly 5 fill-in-the-blank sentences in Italian.\n"
        "   Each item format: \"Marco non e mai stato a Parigi, ma _____ visitarla. (risposta: vorrebbe)\"\n\n"
        "4. \"image_prompt\" - One sentence in English describing the key visual scene,\n"
        "   suitable for image generation. No text or letters in the image.\n\n"
        "Return only the raw JSON object."
    )

    response = claude_client.messages.create(
        model='claude-sonnet-4-6',
        max_tokens=2048,
        system=system,
        messages=[
            {'role': 'user',      'content': user},
            {'role': 'assistant', 'content': '{'},
        ],
    )

    raw = '{' + response.content[0].text
    result = json.loads(raw)

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
    try:
        from elevenlabs import ElevenLabs
    except ImportError:
        raise RuntimeError("elevenlabs package not installed.")

    api_key = os.getenv('ELEVENLABS_API_KEY')
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY is not set.")

    voice_id = os.getenv('ELEVENLABS_VOICE_ID', 'CwhRBWXzGAHq8TQ4Fs17')

    client = ElevenLabs(api_key=api_key)

    audio_stream = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id='eleven_multilingual_v2',
        output_format='mp3_44100_128',
    )

    buffer = io.BytesIO()
    for chunk in audio_stream:
        buffer.write(chunk)
    buffer.seek(0)

    logger.info("Voiceover generated with ElevenLabs.")
    return buffer
