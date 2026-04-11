import json
import re
import random
import io
import logging
import anthropic
import openai

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Story building blocks
# ---------------------------------------------------------------------------

NARRATIVE_ARCS = [
    'rags to riches',
    'the quest',
    'voyage and return',
    'comedy of errors',
    'tragedy',
    'rebirth and redemption',
    'overcoming the monster',
]

CONFLICT_TYPES = [
    'betrayal by someone trusted',
    'impossible choice between two loyalties',
    'a secret that threatens to destroy everything',
    'rivalry that turns personal',
    'a misunderstanding with devastating consequences',
    'desire for something forbidden',
    'a promise that cannot be kept',
]

CHARACTER_ARCHETYPES = [
    'reluctant hero with a hidden past',
    'idealist who slowly loses faith',
    'cynic who rediscovers hope',
    'outsider who sees what insiders cannot',
    'caretaker who reaches their limit',
]

DIALOGUE_TOPICS = [
    'al bar la mattina presto',
    'dal medico con sintomi strani',
    'con il vicino di casa rumoroso',
    'al supermercato senza soldi sufficienti',
    'in treno con un passeggero invadente',
    'al ristorante con un cameriere scortese',
    'con il capo per chiedere un aumento',
    'con un ex incontrato per caso',
    'alla fermata del bus sotto la pioggia',
    'a una cena di famiglia tesa',
    'con un amico che chiede un favore impossibile',
    'in aeroporto con il volo cancellato',
]

ARTICLE_TOPICS = [
    "l'aperitivo italiano: rito sociale o scusa per bere?",
    "Milano vs Roma: due anime dell'Italia",
    "la Liguria e la cucina di mare",
    "il calcio come religione nazionale",
    "il caffe italiano: regole non scritte",
    "estate italiana: ferragosto e il paese che si ferma",
    "la famiglia italiana: mito e realta",
    "moda italiana: stile come identita",
    "il dialetto: lingua morente o patrimonio vivo?",
    "il dolce far niente: filosofia di vita",
    "la scuola italiana: tra tradizione e crisi",
    "emigrazione italiana: chi parte e perche",
]

LEVEL_GUIDE = {
    'A1': 'Use only the simplest present tense, very short sentences (5-8 words), and the 500 most common Italian words.',
    'A2': 'Use simple present and passato prossimo only, short clear sentences, everyday vocabulary.',
    'B1': 'Use present, passato prossimo, and imperfetto. Moderate sentence complexity, common idioms allowed.',
    'B2': 'Use a full range of tenses including congiuntivo. More complex syntax, idiomatic expressions welcome.',
    'C1': 'Use nuanced vocabulary, complex syntax, congiuntivo, condizionale, and subtle register shifts.',
    'C2': 'Native-level prose. Full stylistic range, literary vocabulary, implicit meaning and subtext.',
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_text(response):
    parts = []
    for block in response.content:
        if hasattr(block, 'text'):
            parts.append(block.text)
    return ''.join(parts).strip()


def _level_instruction(level: str) -> str:
    level_upper = level.upper().strip()
    return LEVEL_GUIDE.get(level_upper, LEVEL_GUIDE['B1'])


def _strip_fences(raw: str) -> str:
    raw = re.sub(r'^```[a-z]*\n?', '', raw.strip())
    raw = re.sub(r'\n?```$', '', raw.strip())
    return raw.strip()


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class StoryGenerator:

    def __init__(self, anthropic_api_key: str, openai_api_key: str):
        self.client = anthropic.Anthropic(api_key=anthropic_api_key)
        self.openai_client = openai.OpenAI(api_key=openai_api_key)

    # ------------------------------------------------------------------
    # STEP 1 — Generate plot outline (no phrases yet)
    # ------------------------------------------------------------------

    def _generate_plot_outline(self, genre: str, setting: str, protagonist: str) -> str:
        arc = random.choice(NARRATIVE_ARCS)
        conflict = random.choice(CONFLICT_TYPES)
        archetype = random.choice(CHARACTER_ARCHETYPES)

        prompt = f"""You are a story architect. Create a tight 5-sentence plot spine for a short Italian story.

Genre: {genre}
Setting: {setting}
Protagonist type: {protagonist} ({archetype})
Narrative arc: {arc}
Central conflict: {conflict}

Write exactly 5 sentences:
1. Opening situation and protagonist introduction
2. Inciting incident that sets the conflict in motion
3. Escalation — the conflict deepens, stakes rise
4. Crisis point — the worst moment or hardest choice
5. Resolution — not necessarily happy, but meaningful

Be specific and vivid. No clichés. Output only the 5 sentences, nothing else."""

        response = self.client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=400,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return _get_text(response)

    # ------------------------------------------------------------------
    # STEP 1.5 — Select most plot-relevant phrases (~50% of vocab)
    # ------------------------------------------------------------------

    def _select_relevant_phrases(self, all_phrases: list, plot_outline: str) -> list:
        if not all_phrases:
            return []

        target = max(6, len(all_phrases) // 2)  # 50%, minimum 6
        target = min(target, len(all_phrases))

        numbered = '\n'.join(f'{i+1}. {p}' for i, p in enumerate(all_phrases))

        prompt = f"""You are selecting Italian vocabulary to embed naturally in a story.

STORY PLOT:
{plot_outline}

AVAILABLE VOCABULARY ({len(all_phrases)} items):
{numbered}

Pick exactly {target} items that fit most naturally into this specific plot.
Prefer items with emotional weight, action, or character voice relevant to the conflict and tone.
Single words are fine if thematically strong for this plot.

Return ONLY a valid JSON array of the selected items, exactly as written above.
Example: ["forse", "non ci credo", "tradire qualcuno"]"""

        response = self.client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=512,
            messages=[{'role': 'user', 'content': prompt}]
        )

        raw = _get_text(response)
        raw = re.sub(r'^```[a-z]*\n?', '', raw.strip())
        raw = re.sub(r'\n?```$', '', raw.strip())

        try:
            selected = json.loads(raw)
            if isinstance(selected, list):
                return [str(p) for p in selected]
        except (json.JSONDecodeError, ValueError):
            pass

        return all_phrases[:target]

    # ------------------------------------------------------------------
    # STEP 2 — Write full story using outline + selected phrases
    # ------------------------------------------------------------------

    async def generate_story_and_exercises(
        self,
        phrases: list,
        genre: str,
        setting: str,
        protagonist: str,
        student_name: str = None,
        native_language: str = 'Russian',
        level: str = 'B1',
    ) -> dict:
        from phrase_selector import clean_phrases

        all_phrases = clean_phrases(phrases)
        plot_outline = self._generate_plot_outline(genre, setting, protagonist)
        selected_phrases = self._select_relevant_phrases(all_phrases, plot_outline)

        name_clause = f'The student is named {student_name}.' if student_name else ''
        phrases_str = '\n'.join(f'- {p}' for p in selected_phrases)
        level_instruction = _level_instruction(level)

        prompt = f"""You are writing a short Italian story for a language learner.
{name_clause}
Language level: {level}. {level_instruction}
Native language of the student: {native_language}

PLOT OUTLINE (follow this structure closely):
{plot_outline}

VOCABULARY TO USE (you MUST use ALL of these — embed them naturally, never announce them):
{phrases_str}

RULES:
- Write in Italian. Use tenses appropriate for {level} level.
- NO passato remoto under any circumstances.
- 200-250 words total — tight and punchy, every sentence earns its place.
- Third person unless the protagonist is explicitly "io".
- Any dialogue must sound real, not textbook-clean.
- No cliches. Sensory detail. Subtext.
- Split into chunks of EXACTLY 1-2 sentences. Never more per chunk.
- After the story: 3 exercises appropriate for {level}: fill-in-the-blank, true/false, one open question in {native_language}.

Respond in this exact JSON format (no markdown, no code fences):
{{
  "title": "story title in Italian",
  "chunks": [
    {{
      "italian": "1-2 sentences in Italian",
      "translation": "translation in {native_language}"
    }}
  ],
  "exercises": {{
    "fill_in_blank": ["sentence with ___ gap", "sentence with ___ gap", "sentence with ___ gap"],
    "true_false": ["statement 1", "statement 2", "statement 3"],
    "open_question": "one open question in {native_language}"
  }}
}}"""

        response = self.client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=4096,
            messages=[{'role': 'user', 'content': prompt}]
        )

        raw = _get_text(response)
        raw = re.sub(r'^```[a-z]*\n?', '', raw.strip())
        raw = re.sub(r'\n?```$', '', raw.strip())

        try:
            result = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            result = {
                'title': 'Storia',
                'chunks': [{'italian': raw, 'translation': ''}],
                'exercises': {'fill_in_blank': [], 'true_false': [], 'open_question': ''},
            }

        result['plot_outline'] = plot_outline
        result['selected_phrases'] = selected_phrases
        result['genre'] = genre
        result = self._edit_content(result, level, native_language)
        return result

    # ------------------------------------------------------------------
    # Dialogue generator
    # ------------------------------------------------------------------

    async def generate_dialogue(
        self,
        phrases: list,
        topic: str,
        student_name: str = None,
        native_language: str = 'Russian',
        level: str = 'B1',
    ) -> dict:
        from phrase_selector import clean_phrases

        all_phrases = clean_phrases(phrases)
        target = max(6, len(all_phrases) // 2)
        target = min(target, len(all_phrases))
        selected_phrases = random.sample(all_phrases, target)

        name_clause = f'The student is named {student_name}.' if student_name else ''
        phrases_str = '\n'.join(f'- {p}' for p in selected_phrases)
        level_instruction = _level_instruction(level)

        prompt = f"""You are writing a realistic everyday Italian dialogue for a language learner.
{name_clause}
Language level: {level}. {level_instruction}
Native language: {native_language}
Setting: {topic}

VOCABULARY TO USE (you MUST use ALL of these — embed them naturally):
{phrases_str}

RULES:
- 2 speakers, 8-10 exchanges total — keep it tight.
- Real tension or mild conflict — not a textbook exchange.
- Language appropriate for {level} level.
- NO passato remoto.
- Each chunk = exactly one speaker turn (1-2 lines max).
- After the dialogue: fill-in-the-blank (2 gaps) and one comprehension question in {native_language}.

Respond in this exact JSON format (no markdown, no code fences):
{{
  "title": "dialogue title in Italian",
  "chunks": [
    {{
      "italian": "A: one speaker line",
      "translation": "translation in {native_language}"
    }}
  ],
  "exercises": {{
    "fill_in_blank": ["sentence with ___ gap", "sentence with ___ gap"],
    "open_question": "one question in {native_language}"
  }}
}}"""

        response = self.client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=3000,
            messages=[{'role': 'user', 'content': prompt}]
        )

        raw = _get_text(response)
        raw = re.sub(r'^```[a-z]*\n?', '', raw.strip())
        raw = re.sub(r'\n?```$', '', raw.strip())

        try:
            result = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            result = {
                'title': 'Dialogo',
                'chunks': [{'italian': raw, 'translation': ''}],
                'exercises': {'fill_in_blank': [], 'open_question': ''},
            }

        result['selected_phrases'] = selected_phrases
        result['genre'] = 'dialogo'
        result = self._edit_content(result, level, native_language)
        return result

    # ------------------------------------------------------------------
    # Cultural article generator
    # ------------------------------------------------------------------

    async def generate_article(
        self,
        phrases: list,
        topic: str,
        student_name: str = None,
        native_language: str = 'Russian',
        level: str = 'B1',
    ) -> dict:
        from phrase_selector import clean_phrases

        all_phrases = clean_phrases(phrases)
        target = max(6, len(all_phrases) // 2)
        target = min(target, len(all_phrases))
        selected_phrases = random.sample(all_phrases, target)

        name_clause = f'The student is named {student_name}.' if student_name else ''
        phrases_str = '\n'.join(f'- {p}' for p in selected_phrases)
        level_instruction = _level_instruction(level)

        prompt = f"""You are writing a short cultural article about Italy for a language learner.
{name_clause}
Language level: {level}. {level_instruction}
Native language: {native_language}
Topic: {topic}

VOCABULARY TO USE (you MUST use ALL of these — embed them naturally):
{phrases_str}

RULES:
- Warm, curious journalistic tone — not academic.
- 150-200 words total.
- No narrative arc — this is an article, not a story.
- Include one concrete anecdote or example.
- Language appropriate for {level} level. NO passato remoto.
- Split into chunks of EXACTLY 1-2 sentences. Never more.
- One open reflection question at the end in {native_language}.

Respond in this exact JSON format (no markdown, no code fences):
{{
  "title": "article title in Italian",
  "chunks": [
    {{
      "italian": "1-2 sentences in Italian",
      "translation": "translation in {native_language}"
    }}
  ],
  "exercises": {{
    "open_question": "one reflection question in {native_language}"
  }}
}}"""

        response = self.client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=3000,
            messages=[{'role': 'user', 'content': prompt}]
        )

        raw = _get_text(response)
        raw = re.sub(r'^```[a-z]*\n?', '', raw.strip())
        raw = re.sub(r'\n?```$', '', raw.strip())

        try:
            result = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            result = {
                'title': 'Articolo',
                'chunks': [{'italian': raw, 'translation': ''}],
                'exercises': {'open_question': ''},
            }

        result['selected_phrases'] = selected_phrases
        result['genre'] = 'articolo'
        result = self._edit_content(result, level, native_language)
        return result

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # STEP 3 — Editor pass (consistency, naturalness, level check)
    # ------------------------------------------------------------------

    def _edit_content(self, result: dict, level: str, native_language: str) -> dict:
        """
        Reviews the generated chunks for:
        - Narrative inconsistencies (names changing, contradicting facts, timeline)
        - Characters or objects appearing without introduction
        - Unnatural Italian phrasing
        - Wrong language level (too hard or too easy)
        - Passato remoto (forbidden — replace with passato prossimo)

        Returns the result dict with corrected chunks.
        """
        chunks = result.get('chunks', [])
        if not chunks:
            return result

        level_instruction = _level_instruction(level)

        # Build numbered chunk list for the prompt
        chunk_list = '\n'.join(
            f'{i+1}. IT: {c.get("italian","")}\n   {native_language}: {c.get("translation","")}'
            for i, c in enumerate(chunks)
        )

        prompt = f"""You are an expert Italian language editor reviewing a short text for a {level} level learner.

CHUNKS TO REVIEW:
{chunk_list}

CHECK FOR EACH CHUNK:
1. Narrative consistency — do character names, facts, and timeline stay coherent across all chunks?
2. Unintroduced elements — does anything appear (person, object, place) without being established earlier?
3. Natural Italian — flag any awkward phrasing, calques, or unidiomatic expressions and fix them
4. Level fit ({level}) — {level_instruction}. Fix anything too complex or too simple.
5. Passato remoto — if found, replace with passato prossimo

Fix only what needs fixing. If a chunk is fine, return it unchanged.
Return the SAME number of chunks as input.

Respond in this exact JSON format (no markdown, no code fences):
[
  {{
    "italian": "corrected or unchanged Italian text",
    "translation": "corrected or unchanged {native_language} translation"
  }}
]"""

        response = self.client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=2048,
            messages=[{'role': 'user', 'content': prompt}]
        )

        raw = _strip_fences(_get_text(response))

        try:
            corrected = json.loads(raw)
            if isinstance(corrected, list) and len(corrected) == len(chunks):
                result['chunks'] = corrected
                logger.info("Editor pass completed successfully.")
            else:
                logger.warning("Editor returned wrong number of chunks — keeping original.")
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Editor pass failed to parse: {e} — keeping original.")

        return result

    # ------------------------------------------------------------------
    # Format for Telegram (parallel text)
    # ------------------------------------------------------------------

    def format_for_telegram(self, result: dict) -> list:
        """
        Each chunk renders as:
            Italian sentence(s)
            ———
            Translation in italics

        Exercises appended at the end.
        Returns list of strings, each under 4096 chars.
        """
        title = result.get('title', 'Storia')
        chunks = result.get('chunks', [])
        exercises = result.get('exercises', {})

        messages = []
        current = f'<b>{title}</b>\n\n'

        for chunk in chunks:
            italian = chunk.get('italian', '').strip()
            translation = chunk.get('translation', '').strip()

            block = italian
            if translation:
                block += f'\n———\n<i>{translation}</i>'
            block += '\n\n'

            if len(current) + len(block) > 4000:
                messages.append(current.strip())
                current = block
            else:
                current += block

        # Exercises
        ex_text = '<b>Esercizi</b>\n\n'

        fill = exercises.get('fill_in_blank', [])
        if fill:
            ex_text += '<b>Completa le frasi:</b>\n'
            for i, s in enumerate(fill, 1):
                ex_text += f'{i}. {s}\n'
            ex_text += '\n'

        tf = exercises.get('true_false', [])
        if tf:
            ex_text += '<b>Vero o falso:</b>\n'
            for i, s in enumerate(tf, 1):
                ex_text += f'{i}. {s}\n'
            ex_text += '\n'

        oq = exercises.get('open_question', '')
        if oq:
            ex_text += f'<b>Domanda aperta:</b>\n{oq}\n'

        if ex_text.strip() != '<b>Esercizi</b>':
            if len(current) + len(ex_text) > 4000:
                messages.append(current.strip())
                messages.append(ex_text.strip())
            else:
                current += ex_text
                messages.append(current.strip())
        else:
            messages.append(current.strip())

        return messages

    # ------------------------------------------------------------------
    # Cover image (DALL-E 3)
    # ------------------------------------------------------------------

    def generate_cover_image(self, result: dict) -> str:
        title = result.get('title', 'Italian story')
        genre = result.get('genre', 'story')

        style_map = {
            'dialogo': 'warm editorial illustration, cafe setting, two people talking',
            'articolo': 'travel magazine style, Italy, golden hour, no people',
        }
        style = style_map.get(genre, 'cinematic painting, dramatic lighting, Italian setting')

        # Keep prompt short and safe to avoid content policy rejections
        prompt = (
            f'Illustration for an Italian language learning story titled "{title[:60]}". '
            f'{style}. '
            f'No text, letters, or words anywhere in the image.'
        )

        try:
            response = self.openai_client.images.generate(
                model='dall-e-3',
                prompt=prompt,
                size='1024x1024',
                quality='standard',
                n=1,
            )
            return response.data[0].url
        except Exception:
            # Fallback: generic safe prompt
            fallback_prompt = (
                'Illustration of a sunny Italian piazza with a fountain, '
                'warm afternoon light, painterly style. '
                'No text, no letters, no words.'
            )
            response = self.openai_client.images.generate(
                model='dall-e-3',
                prompt=fallback_prompt,
                size='1024x1024',
                quality='standard',
                n=1,
            )
            return response.data[0].url

    # ------------------------------------------------------------------
    # Voiceover (OpenAI TTS)
    # ------------------------------------------------------------------

    def generate_voiceover(self, result: dict) -> io.BytesIO:
        chunks = result.get('chunks', [])
        italian_text = ' '.join(
            chunk.get('italian', '') for chunk in chunks
        ).strip()

        if not italian_text:
            italian_text = result.get('title', 'Nessun testo disponibile.')

        if len(italian_text) > 4000:
            italian_text = italian_text[:4000]

        response = self.openai_client.audio.speech.create(
            model='tts-1',
            voice='nova',
            input=italian_text,
        )

        audio_buffer = io.BytesIO()
        for chunk in response.iter_bytes():
            audio_buffer.write(chunk)
        audio_buffer.seek(0)
        return audio_buffer
