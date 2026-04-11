import json
import re
import random
import io
import anthropic
import openai

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
    "il caffè italiano: regole non scritte",
    "estate italiana: ferragosto e il paese che si ferma",
    "la famiglia italiana: mito e realta",
    "moda italiana: stile come identita",
    "il dialetto: lingua morente o patrimonio vivo?",
    "il dolce far niente: filosofia di vita",
    "la scuola italiana: tra tradizione e crisi",
    "emigrazione italiana: chi parte e perche",
]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_text(response):
    parts = []
    for block in response.content:
        if hasattr(block, 'text'):
            parts.append(block.text)
    return ''.join(parts).strip()


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

Write 5 sentences:
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
    # STEP 1.5 — Select most plot-relevant phrases (~20% of vocab)
    # ------------------------------------------------------------------

    def _select_relevant_phrases(self, all_phrases: list, plot_outline: str) -> list:
        if not all_phrases:
            return []

        target = max(4, len(all_phrases) // 5)  # 20%, minimum 4

        numbered = '\n'.join(f'{i+1}. {p}' for i, p in enumerate(all_phrases))

        prompt = f"""You are selecting Italian vocabulary to embed naturally in a story.

STORY PLOT:
{plot_outline}

AVAILABLE VOCABULARY ({len(all_phrases)} items):
{numbered}

Pick exactly {target} items that fit most naturally into this specific plot.
Prefer items with emotional weight, specific action, or character voice that resonates with the story's conflict and tone.
Single words are fine if they are thematically strong for this plot.

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

        # Fallback: return first target items
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
    ) -> dict:
        from phrase_selector import clean_phrases

        # Step 0: remove metalinguistic noise only
        all_phrases = clean_phrases(phrases)

        # Step 1: generate plot
        plot_outline = self._generate_plot_outline(genre, setting, protagonist)

        # Step 1.5: select most relevant phrases for this plot
        selected_phrases = self._select_relevant_phrases(all_phrases, plot_outline)

        # Step 2: write story
        name_clause = f'The student is named {student_name}.' if student_name else ''
        phrases_str = '\n'.join(f'- {p}' for p in selected_phrases)

        prompt = f"""You are writing a short Italian story for a language learner.
{name_clause}
Native language of the student: {native_language}
Level: intermediate (B1-B2)

PLOT OUTLINE (follow this structure closely):
{plot_outline}

VOCABULARY TO WEAVE IN (use each naturally — do not force them):
{phrases_str}

RULES:
- Write in Italian, present tense (passato prossimo for completed past actions is fine, NO passato remoto)
- 350-500 words total
- Third person unless the protagonist is explicitly "io"
- Dialogue must feel real — not textbook-clean
- Prose quality: sensory detail, subtext, no clichés
- Do not list or announce the vocabulary — embed it invisibly
- After the story, write 3 exercises: fill-in-the-blank, true/false comprehension, and one open question in {native_language}

Respond in this exact JSON format (no markdown, no code fences):
{{
  "title": "story title in Italian",
  "chunks": [
    {{
      "italian": "paragraph in Italian",
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
                'exercises': {
                    'fill_in_blank': [],
                    'true_false': [],
                    'open_question': '',
                }
            }

        result['plot_outline'] = plot_outline
        result['selected_phrases'] = selected_phrases
        result['genre'] = genre
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
    ) -> dict:
        from phrase_selector import clean_phrases

        all_phrases = clean_phrases(phrases)
        # For dialogue: use ~25% of vocab (a bit more than story since dialogue is denser)
        target = max(4, len(all_phrases) // 4)
        selected_phrases = random.sample(all_phrases, min(target, len(all_phrases)))

        name_clause = f'The student is named {student_name}.' if student_name else ''
        phrases_str = '\n'.join(f'- {p}' for p in selected_phrases)

        prompt = f"""You are writing a realistic everyday Italian dialogue for a language learner.
{name_clause}
Native language: {native_language}
Level: B1-B2
Setting: {topic}

VOCABULARY TO WEAVE IN NATURALLY:
{phrases_str}

RULES:
- 2 speakers, 12-18 exchanges total
- Real tension or mild conflict — not a textbook exchange
- Colloquial but clear Italian, present tense
- Embed vocabulary naturally, never announce it
- After the dialogue, 2 exercises: fill-in-the-blank and one comprehension question in {native_language}

Respond in this exact JSON format (no markdown, no code fences):
{{
  "title": "dialogue title in Italian",
  "chunks": [
    {{
      "italian": "Speaker A: ...",
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
    ) -> dict:
        from phrase_selector import clean_phrases

        all_phrases = clean_phrases(phrases)
        target = max(4, len(all_phrases) // 5)
        selected_phrases = random.sample(all_phrases, min(target, len(all_phrases)))

        name_clause = f'The student is named {student_name}.' if student_name else ''
        phrases_str = '\n'.join(f'- {p}' for p in selected_phrases)

        prompt = f"""You are writing a short cultural article about Italy for a language learner.
{name_clause}
Native language: {native_language}
Level: B1-B2
Topic: {topic}

VOCABULARY TO WEAVE IN NATURALLY:
{phrases_str}

RULES:
- Warm, curious journalistic tone — not academic
- 300-400 words
- No narrative arc — this is an article, not a story
- Include one concrete anecdote or example to anchor the ideas
- Embed vocabulary naturally
- One exercise at the end: an open reflection question in {native_language}

Respond in this exact JSON format (no markdown, no code fences):
{{
  "title": "article title in Italian",
  "chunks": [
    {{
      "italian": "paragraph in Italian",
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
        return result

    # ------------------------------------------------------------------
    # Format for Telegram (parallel text)
    # ------------------------------------------------------------------

    def format_for_telegram(self, result: dict) -> list:
        """
        Returns a list of message strings (each under 4096 chars).
        Format: Italian paragraph, then Russian translation in italics, separated by dividers.
        """
        title = result.get('title', 'Storia')
        chunks = result.get('chunks', [])
        exercises = result.get('exercises', {})

        messages = []
        current = f'<b>{title}</b>\n\n'

        divider = '\n\n- - -\n\n'

        for chunk in chunks:
            italian = chunk.get('italian', '').strip()
            translation = chunk.get('translation', '').strip()

            block = f'{italian}'
            if translation:
                block += f'\n<i>{translation}</i>'
            block += divider

            if len(current) + len(block) > 4000:
                messages.append(current.strip())
                current = block
            else:
                current += block

        # Exercises
        ex_text = '\n\n<b>Esercizi</b>\n\n'

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

        if len(current) + len(ex_text) > 4000:
            messages.append(current.strip())
            messages.append(ex_text.strip())
        else:
            current += ex_text
            messages.append(current.strip())

        return messages

    # ------------------------------------------------------------------
    # Cover image (DALL-E 3)
    # ------------------------------------------------------------------

    def generate_cover_image(self, result: dict) -> str:
        title = result.get('title', 'Italian story')
        plot = result.get('plot_outline', '')
        genre = result.get('genre', 'story')

        style_map = {
            'dialogo': 'editorial illustration, warm cafe tones',
            'articolo': 'travel magazine photography style, golden hour',
        }
        style = style_map.get(genre, 'cinematic oil painting, dramatic lighting')

        summary = plot[:300] if plot else title

        prompt = (
            f'Cover illustration for an Italian language learning text. '
            f'Title: "{title}". '
            f'Scene: {summary}. '
            f'Style: {style}. '
            f'No text, no letters, no words in the image.'
        )

        response = self.openai_client.images.generate(
            model='dall-e-3',
            prompt=prompt,
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

        # Trim to TTS limit
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
