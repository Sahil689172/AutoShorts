# Narration Sanitization Engine (Phase 3.7E)

Adds a lightweight text sanitization stage immediately before **Kokoro** synthesis to improve long-form stability and prevent “gibberish” near the end of narration.

This does **not** modify `KokoroProvider`. It only cleans the narration text passed into it.

---

## Where it runs

`backend/services/narration/narration_manager.py`

Runtime order:

```
prepare_narration_text()
  ↓
NarrationSanitizer.sanitize()
  ↓
KokoroProvider.generate_audio()
  ↓
split_text_for_kokoro()
  ↓
engine.create(chunk) × N
  ↓
audio/output.wav
```

The sanitizer debug lines are printed only when `provider.name == "kokoro"`.

---

## What it does

Input: raw narration text (after `prepare_narration_text()` formatting)  
Output: sanitized narration text

### 1) Normalize whitespace

- Collapses repeated whitespace.
- Trims leading/trailing whitespace.

### 2) Insert missing whitespace after sentence punctuation

Fixes common script-generation artifacts:

- `.Inside` → `. Inside`
- `The.Engine` → `The. Engine`
- `RPM.The` → `RPM. The`

Safeguard:

- Does **not** split decimals like `3.14`.

URLs are temporarily masked so punctuation fixes do not damage links.

### 3) Normalize repeated punctuation

- `...` → `.`
- `!!` → `!`
- `??` → `?`

### 4) Validate sentence boundaries for Kokoro chunk safety (debug)

For Kokoro debugging, the sanitizer estimates chunking using the required split priority:

1. Sentence boundaries (`. ! ?`)
2. `, ; :`
3. Whitespace (words)

This estimate is used only for reporting; actual chunking still happens in `split_text_for_kokoro()`.

---

## Debug output

Printed immediately before Kokoro synthesis:

- Characters Before
- Characters After
- Sentence Count
- Chunk Count (estimate for safe Kokoro chunk length)
- Longest Chunk

Example:

```
NarrationSanitizer debug:
  Characters Before: 512
  Characters After:  526
  Sentence Count:    6
  Chunk Count:       2
  Longest Chunk:     392
```

---

## Why this helps Kokoro stability

Kokoro (and `kokoro-onnx`) has a known hard limit around **510 phonemes** per inference. Long run-on sentences, malformed punctuation, or missing spaces can prevent sentence splitting and lead to unstable phonemization.

By ensuring sentence punctuation is followed by whitespace and by normalizing punctuation/spacing, Kokoro is more likely to receive linguistically well-formed segments and avoid pathological long “sentences”.

