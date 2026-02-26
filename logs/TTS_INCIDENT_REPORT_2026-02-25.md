# TTS Incident Report - 2026-02-25

## Scope
- Issue reported by end users:
  - UI stuck on `Preparando leitura em audio...`
  - Browser error `Failed to load because no supported source was found.`
  - Frontend timeout message after ~90s

## Environment
- Project: `D:\dev\Ratio - Pesquisa Jurisprudencial`
- Frontend endpoint: `/api/tts`
- Backend endpoint: `/api/tts` in FastAPI
- Gemini key used in live validation: provided by operator (redacted in this report)

## Root Causes Identified
1. Incompatible audio MIME returned by backend:
   - Backend received `audio/l16;codec=pcm;rate=24000` (raw PCM).
   - Browser audio element cannot play this payload directly.
   - Result: `Failed to load because no supported source was found.`

2. Frontend timeout too low and static for TTS:
   - Timeout was fixed at 90s.
   - Real TTS latency in this environment regularly exceeded 90s.
   - Result: request abort while still processing backend.

3. Misleading timeout wording:
   - Generic `postJson` timeout error always said `A validacao...`, even for TTS.
   - Result: user-facing message did not match operation context.

4. Model instability / response variability:
   - Some model calls returned no `inline_data` audio payload.
   - Some attempts returned transient 500/Internal.
   - Fallback previously could end at a non-audio-capable model path.

## Code Changes Applied
- Backend
  - Added PCM detection and conversion to WAV (`audio/wav`) before response.
  - Added retryable-error classification for TTS fallbacks.
  - Added per-request TTS HTTP timeout and bounded retry settings.
  - Added per-model attempt loop for transient failures.
  - Relevant references:
    - `backend/main.py:417` (`_is_pcm_mime`)
    - `backend/main.py:458` (`_pcm_to_wav_bytes`)
    - `backend/main.py:591` (`_is_tts_retryable_error`)
    - `backend/main.py:611` (`_synthesize_google_tts`)

- Frontend
  - Replaced fixed TTS timeout with dynamic estimate based on text length.
  - Added contextual timeout label in `postJson` (`A geracao do audio`).
  - Kept abort controller behavior with improved messaging.
  - Relevant references:
    - `frontend/app.js:30` (dynamic timeout constants)
    - `frontend/app.js:232` (`estimateTtsTimeoutMs`)
    - `frontend/app.js:838` (`postJson`, timeout label support)
    - `frontend/app.js:1982` (TTS request with dynamic timeout + label)

## Automated Test Evidence
- Command:
  - `py -m pytest -q tests/test_frontend_sidebar_saved.py tests/test_api_contract.py`
- Result:
  - `48 passed, 1 warning`
- New/updated tests:
  - `tests/test_api_contract.py:195` (`test_tts_extract_converts_pcm_l16_into_wav`)
  - `tests/test_api_contract.py:357` (`test_tts_generation_uses_http_timeout_and_limited_retries`)
  - `tests/test_frontend_sidebar_saved.py:216` (`test_tts_request_has_explicit_timeout_to_avoid_stuck_loading`)

## Live Runtime Measurements (Real Key, Redacted)
- Before final tuning, instability was reproduced with long waits and failures.
- After current changes, live calls observed:
  - Short text (~73 chars): success, `audio/wav`, ~88s
  - Medium text (~3709 chars): success, `audio/wav`, ~96s
- Interpretation:
  - Format incompatibility is solved for successful calls (WAV output).
  - Latency remains high and variable depending on upstream conditions.

## Current Packaging State
- Last compiled executable currently present:
  - `dist/Ratio/Ratio.exe` modified at `2026-02-25 20:49:04`
- Packaging verification:
  - Frontend bundled file (`dist/Ratio/_internal/frontend/app.js`) contains dynamic TTS timeout logic (`estimateTtsTimeoutMs`) and contextual timeout label (`A geracao do audio`).
  - Source timestamps for `backend/main.py` and `frontend/app.js` are older than current `Ratio.exe`, indicating rebuild after the latest source edits.
- Operational implication:
  - The specific "source fixed but executable old" gap is no longer present in this build.
  - Users can still observe failures due to upstream instability/latency even with updated binary.

## Incident Status
- Source-level bugfixes: implemented and tested.
- Packaging gap: closed in current local build.
- User-perceived reliability: still at risk under high latency and transient upstream errors.

## Recommended Engineering Plan
1. Immediate (incident response):
  - Distribute only the latest `dist/Ratio` package (post-`20:49:04` build).
  - In support responses, request user build timestamp before triage to avoid stale-binary false positives.
2. Next sprint (architectural hardening):
  - Implement text chunking (paragraph/sentence boundaries) before TTS generation.
  - Move from monolithic wait to progressive playback/streaming UX.
  - Add trace ID in backend and surface it in frontend errors for support diagnostics.

## Remaining Risk
- Upstream Gemini TTS latency and intermittent internal errors still occur.
- Even with resilient fallback, end-user experience may vary under network/API instability.
- Recommended next step for hardening:
  - Add backend telemetry per chunk/model/attempt with durations and error codes.
  - Return trace ID to frontend for actionable support diagnostics.

## Update - 2026-02-25 21:26
- Telemetry and support diagnostics were implemented:
  - Backend now emits per-request `trace_id` for `/api/tts`.
  - Backend logs TTS attempt/chunk events to `logs/runtime/tts_backend.log`.
  - Frontend now surfaces `trace_id` in TTS errors for support triage.
- Error classification improved:
  - Gemini `500 INTERNAL` responses in TTS are now classified as `upstream_unavailable` (HTTP 503), instead of generic internal backend error.
- Verification:
  - `py -m pytest -q tests/test_frontend_sidebar_saved.py tests/test_api_contract.py`
  - Result: `51 passed, 1 warning`

## Update - 2026-02-25 21:52 (live long-text validation)
- Real long-text TTS test (~7643 chars) was executed against `/api/tts` with valid key.
- Both attempts failed with backend response `500 internal_error` after long waits.
- Trace IDs captured:
  - `28052ff08d0e`
  - `8949be97c06d`
- `tts_backend.log` evidence:
  - recurrent read timeouts on `gemini-2.5-flash-preview-tts`;
  - fallback model `gemini-2.5-flash-tts` returned `404 NOT_FOUND` (unsupported/not available for this key/API version);
  - one partial success chunk (`audio/wav`) followed by missing audio parts in subsequent chunk.
- Additional compatibility check:
  - `gemini-2.5-flash-preview-tts`: accepted via `generate_content` (audio returned);
  - `gemini-2.5-flash-tts`: `404 NOT_FOUND`;
  - `gemini-2.5-flash-native-audio-preview-12-2025`: `404 NOT_FOUND` on `generate_content` (Live API model, not valid in current non-live path).
- Conclusion:
  - Current implementation is improved diagnostically, but reliability for long text is still not guaranteed under current architecture/model path.

## Update - 2026-02-25 22:27 (chunk/timeouts hardening validation)
- Code hardening applied:
  - Default TTS chunk size lowered to 400 chars (`GEMINI_TTS_MAX_CHARS`, bounded).
  - Invalid fallback default removed (`gemini-2.5-flash-tts` no longer forced).
  - Per-chunk retry retained (2 attempts by default), avoiding regeneration from chunk 1 after later failures.
  - `google-genai` call now injects explicit `httpx_client` with strict timeout configuration plus `http_options.timeout`.
- Automated validation:
  - `py -m pytest -q tests/test_frontend_sidebar_saved.py tests/test_api_contract.py`
  - Result: `54 passed, 1 warning`
- Real long-text re-test (~7643 chars):
  - Request returned `503 upstream_unavailable` after `317.79s`
  - Trace ID: `657ba331a457`
  - Runtime log showed:
    - split into 28 chunks (~400 chars target);
    - chunk 1 and 2 succeeded (`audio/wav`);
    - chunk 3 timed out twice and exhausted retries.
  - Important observation:
    - even with explicit `httpx` timeout set to 60s, one attempt still lasted ~144s before `The read operation timed out`.
- Practical conclusion:
  - Chunk reduction improved progress visibility and reduced model-mismatch noise, but did not fully solve upstream latency instability on long text.

## Update - 2026-02-25 22:33 (timeout default adjustment)
- Backend default timeout for TTS request was raised from 60s to 120s:
  - `GEMINI_TTS_REQUEST_TIMEOUT_MS` default: `120000`.
- Rationale:
  - successful chunks in this environment can exceed 60s under load.
- Validation:
  - `py -m pytest -q tests/test_frontend_sidebar_saved.py tests/test_api_contract.py`
  - Result: `54 passed, 1 warning`

## Update - 2026-02-25 22:49 (prefetch + cache behavior hardening)
- Backend stream TTS path was refactored for controlled prefetch and chunk cache on disk:
  - Added worker function with per-chunk retry + cache read/write:
    - `backend/main.py:949` (`_synthesize_stream_chunk_with_retries`)
    - cache key uses `hashlib.sha256` and files under `logs/runtime/tts_cache`.
  - Added bounded concurrent execution in stream path:
    - `backend/main.py:1112` (executor submit path)
    - `backend/main.py:1125` (`fill_prefetch_window`)
  - Added stream cache hit telemetry:
    - `backend/main.py:967` (`tts_stream_chunk_cache_hit`)
- Automated validation expanded to behavioral tests:
  - `tests/test_api_contract.py` now validates real concurrency and cache reuse (not only source-string assertions).
  - `py -m pytest -q tests/test_frontend_sidebar_saved.py tests/test_api_contract.py`
  - Result: `58 passed, 1 warning`

## Update - 2026-02-25 23:11 (live validation after queue-stability tuning)
- Queue-stability tuning applied:
  - `GEMINI_TTS_PREFETCH_CONCURRENCY` default changed from `3` to `1` for safer behavior on preview model.
  - Stream warm-up changed so first chunk is always requested alone before any extra prefetch window.
  - HTTP pool-wait timeout reduced:
    - `backend/main.py:174` (`pool=min(15.0, timeout_s)`).
- Real test A (before changing default to 1, with burst behavior):
  - Trace ID: `7a24986dc2e3`
  - Request split into `36` chunks (~253 chars each).
  - Chunk 1 succeeded (~99s), chunks 2/3 timed out after long waits, request failed.
  - Cache hit observed for repeated content (`chunk 4` reused cached audio from earlier equivalent chunk).
- Real test B (after default/stability tuning, effective concurrency = 1):
  - Trace ID: `cb22af264d17`
  - Text: ~2780 chars, split into `10` chunks (~277 chars each).
  - Progress:
    - chunks `1..6` succeeded (`audio/wav`);
    - chunk `7` timed out twice and exhausted retries.
  - End status: `503 upstream_unavailable` after ~697s total.
- Practical conclusion:
  - The burst-queue pathology was mitigated (no simultaneous 1/2/3 launch in default path).
  - Reliability improved materially for partial completion, but upstream preview-model instability still prevents deterministic long-text completion.

## Update - 2026-02-25 23:34 (frontend UX hardening for long waits)
- Frontend TTS UX was improved to mask upstream latency without hiding failures:
  - Added dual progress rail in assistant card:
    - `audio-buffer` (chunks received / buffering progress)
    - `audio-progress` (playback progress)
  - Added subtle buffering microanimations on the same bar:
    - loading sweep + status pulse while waiting new chunks.
  - Added replay action ("Reiniciar audio") that reuses locally downloaded chunks without new API request.
- Local replay model:
  - Chunk URLs are cached per turn and per mode (`resposta` / `explicacao`) in memory (`audioStreamByMode`).
  - Clicking replay starts playback from cached chunks immediately.
  - No additional `/api/tts` or `/api/tts/stream` call is required for replay.
- Cleanup behavior:
  - Cached object URLs are revoked when replacing audio cache for the same turn/mode or when clearing chat history.
- Validation:
  - `node --check frontend/app.js`
  - `py -m pytest -q tests/test_frontend_sidebar_saved.py tests/test_api_contract.py`
  - Result: `60 passed, 1 warning`

## Update - 2026-02-25 23:31 (packaging refresh)
- New Windows executable was rebuilt after backend/frontend TTS + UX updates:
  - `dist/Ratio/Ratio.exe`
  - Timestamp: `2026-02-25 23:31:20`
  - Size: `85,956,806` bytes
- Packaging verification:
  - `dist/Ratio/lancedb_store/jurisprudencia.lance` present.
  - Bundled frontend (`dist/Ratio/_internal/frontend/app.js`) contains:
    - replay action (`data-action="replay-audio"`),
    - dual progress bars (`data-audio-buffer-turn`),
    - local replay function (`replayCachedTurnAudio`).

## Update - 2026-02-26 10:44 (rollback provider strategy)
- Due to persistent instability/noise in Gemini preview native audio, backend default TTS provider was rolled back to legacy Google Cloud TTS.
- A separate module was created to preserve previous work and avoid deleting Gemini path:
  - `backend/tts_legacy_google.py`
  - uses `texttospeech.googleapis.com/v1/text:synthesize`
  - default voice/profile aligned with prior stable settings:
    - `GOOGLE_TTS_VOICE_NAME=pt-BR-Neural2-B`
    - `speakingRate=1.2`
    - `pitch=-4.5`
- Backend now supports provider dispatch without frontend contract changes:
  - `TTS_PROVIDER=legacy_google` (default)
  - `TTS_PROVIDER=gemini_native` (alternative, preserved for future use)
- Endpoints `/api/tts` and `/api/tts/stream` now route through provider dispatcher (`_synthesize_tts` / `_stream_tts_chunks`).
- Verification:
  - `py -m pytest -q tests/test_api_contract.py tests/test_frontend_sidebar_saved.py`
  - Result: `63 passed, 1 warning`

## Update - 2026-02-26 10:54 (new executable after rollback)
- New Windows executable rebuilt after provider rollback and dispatcher integration:
  - `dist/Ratio/Ratio.exe`
  - Timestamp: `2026-02-26 10:54:13`
  - Size: `85,963,503` bytes
- Packaging checks:
  - `dist/Ratio/lancedb_store/jurisprudencia.lance` present.
  - Build script backup created at:
    - `build/database_backups/lancedb_store_20260226-104540`
