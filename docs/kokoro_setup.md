# Kokoro TTS Setup

Kokoro is an optional narrator engine for AutoShorts. It uses the [`kokoro-onnx`](https://github.com/thewh1teagle/kokoro-onnx) package with ONNX Runtime (CPU). Piper remains the default — set `NARRATOR_PROVIDER=kokoro` to switch.

---

## Quick Start

### 1. Install Python dependencies

```powershell
pip install -r requirements.txt
```

Required packages:

| Package | Purpose |
|---------|---------|
| `kokoro-onnx` | Kokoro TTS Python API |
| `onnxruntime` | CPU inference |
| `soundfile` | WAV file output |

### 2. Download model files

Create the model directory and download the v1.0 English assets:

```powershell
mkdir models\kokoro
cd models\kokoro

Invoke-WebRequest -Uri "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx" -OutFile "kokoro-v1.0.onnx"
Invoke-WebRequest -Uri "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin" -OutFile "voices-v1.0.bin"
```

Expected layout:

```
models/kokoro/
├── kokoro-v1.0.onnx    (~310 MB)
└── voices-v1.0.bin     (~27 MB)
```

These paths are gitignored (under `models/`).

### 3. Enable Kokoro

Add to your `.env` file or set in the shell:

```env
NARRATOR_PROVIDER=kokoro
```

### 4. Run the pipeline

```powershell
python main.py "your topic here"
```

Or start the API as usual — voice generation uses the configured provider automatically.

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `NARRATOR_PROVIDER` | `piper` | Set to `kokoro` to use Kokoro |
| `KOKORO_MODEL_PATH` | `models/kokoro/kokoro-v1.0.onnx` | ONNX model file |
| `KOKORO_VOICES_PATH` | `models/kokoro/voices-v1.0.bin` | Voice embeddings |
| `KOKORO_VOICE` | `af_heart` | Voice ID (American English female) |

### Popular voices

See the full list in [Kokoro-82M VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md).

| Voice ID | Description |
|----------|-------------|
| `af_heart` | American female (default) |
| `af_bella` | American female (bright) |
| `af_sarah` | American female |
| `am_michael` | American male |
| `bf_emma` | British female |

Example:

```env
NARRATOR_PROVIDER=kokoro
KOKORO_VOICE=af_bella
```

---

## Output contract

Kokoro writes **`audio/output.wav`** — the same path Piper uses. Downstream phases (captions, scenes, video) require no changes.

| Property | Value |
|----------|-------|
| Format | WAV (PCM via soundfile) |
| Sample rate | 24,000 Hz |
| Channels | Mono |

FFmpeg resamples to 48 kHz AAC during final video mux.

---

## Long scripts

Kokoro has a ~510 phoneme limit per synthesis call. AutoShorts automatically:

1. Splits narration at sentence and clause boundaries
2. Synthesizes each chunk (max ~400 characters)
3. Inserts brief pauses between chunks
4. Merges into a single `audio/output.wav`

Typical Shorts scripts (80–100 words) usually fit in one or two chunks.

---

## Troubleshooting

### `kokoro-onnx is not installed`

```powershell
pip install kokoro-onnx onnxruntime soundfile
```

### `Kokoro model not found` / `Kokoro voices not found`

Download the model files into `models/kokoro/` (see step 2 above). Verify paths match `KOKORO_MODEL_PATH` and `KOKORO_VOICES_PATH`.

### `RuntimeError: espeak not installed on your system`

Kokoro uses phonemizer for text-to-phoneme conversion. On Windows:

1. Install [eSpeak NG](https://github.com/espeak-ng/espeak-ng/releases/download/1.52.0/espeak-ng.msi)
2. Add to `.env` or set before running:

```env
PHONEMIZER_ESPEAK_LIBRARY=C:\Program Files\eSpeak NG\libespeak-ng.dll
PHONEMIZER_ESPEAK_PATH=C:\Program Files\eSpeak NG
```

3. If phonemizer conflicts occur, uninstall `phonemizer` and keep only `phonemizer-fork` (bundled with kokoro-onnx):

```powershell
pip uninstall phonemizer phonemizer-fork -y
pip install phonemizer-fork
```

### `Unknown narrator provider`

Supported values: `piper`, `kokoro`. Check spelling and that `.env` is loaded (API uses `python-dotenv`).

### Slow synthesis on CPU

Expected for longer scripts on CPU-only hardware. A typical 80–100 word Shorts script takes roughly 12–30 seconds on an Intel i7-class laptop. Use Piper if you prefer the existing external binary workflow.

### Audio sounds choppy between sentences

Chunk merging uses 150 ms pauses. Very long run-on sentences without punctuation may be split mid-phrase — ensure scripts use normal sentence punctuation.

---

## Switching back to Piper

```env
NARRATOR_PROVIDER=piper
```

Or remove `NARRATOR_PROVIDER` from `.env` (Piper is the default).

---

## References

- [Kokoro feasibility research](kokoro_research.md)
- [Narration architecture](narration_architecture.md)
- [kokoro-onnx on GitHub](https://github.com/thewh1teagle/kokoro-onnx)
- [Model files v1.0 release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0)
