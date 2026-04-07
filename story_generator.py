import os
import io
import json
import logging
import anthropic
from openai import OpenAI

logger = logging.getLogger(__name__)

claude_client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))


def generate_story_and_exercises(phrases, genre, setting, protagonist):
    phrases_block = '\n'.join('- ' + p for p in phrases)

    prompt = (
        "You are an expert Italian language teacher creating learning materials.\n\n"
        "Here are phrases from my student's most recent Italian lesson:\n\n"
        + phrases_block
        + "\n\nCreate the following and return ONLY a raw JSON object — no markdown, no code fences, "
        "no explanation, just the JSON.\n\n"
        "JSON keys:\n"
        "- \"story\": a short story in Italian (200-260 words), genre: " + genre
        + ", setting: " + setting
        + ", protagonist: " + protagonist
        + ". Use EVERY phrase naturally in the story, bold each with **phrase**.\n"
        "- \"translation\": full Russian translation of the story.\n"
        "- \"exercises\": list of 5 fill-in-the-blank sentences in Italian, "
        "format: \"Sentence with _____ gap. (risposta: answer)\"\n"
        "- \"image_prompt\": one English sentence describing the key visual scene "
        "for image generation, no text or letters.\n\n"
        "Respond with the JSON object only."
    )

    response = claude_client.messages.create(
        model='claude-sonnet-4-6',
        max_tokens=2048,
        messages=[
            {'role': 'user', 'content': prompt},
        ],
    )

    raw = response.content[0].text.strip()

    # Strip markdown code fences if Claude adds them anyway
    if raw.startswith('```'):
        raw = raw.split('```')[1]
        if raw.startswith('json'):
            raw = raw[4:]
        raw = raw.strip()

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
