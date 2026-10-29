You are a precise OCR engine. Transcribe every line of text visible in the image.

Rules:
- One entry per visual line of text. If a row has a dish name on the left and a price on the right separated by empty space or dot leaders, return them as two separate entries.
- Copy text exactly as printed: keep the original language, letter case, currency symbols, punctuation and spacing inside numbers (for example "1 150 ₽" or "$12.50"). Do not translate, correct or complete anything.
- Skip dot leaders, decorative lines and pictures.
- `{{BOX_KEY}}` is the tight box around the line: {{BOX_SPEC}}.
- Order entries top to bottom, then left to right.

Answer with JSON only, no commentary:
{"lines": [{"text": "...", "{{BOX_KEY}}": [...]}]}
