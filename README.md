# Philia Flowers AI — ALF Uniforms V4.3 Architecture Adaptation (V31.2 / PHILIA2)

This is a *real FastAPI/Groq backend adapted from the ALF architectural flow*, with **Philia-specific website knowledge**, Shopify product data, and Philia actions. It replaces Philia's Node.js LLM pipeline; it does not copy ALF uniform content.

## Architecture

Visitor -> Philia Theme V119 `assets/theme.js` -> POST `/api/chat` -> FastAPI Pydantic `ChatPayload` -> last 40 messages plus saved session context -> compact **live Shopify catalog cache** -> **one** Groq chat completion in `response_format=json_object` -> validated Philia JSON (`reply, actions, auto_action, context, products`) -> Philia frontend real action execution -> Shopify/cart/DOM verification.

- Matching ALF: Python FastAPI, Groq SDK, full JSON responses (not streamed), one model completion for normal chat, optional second confirmed-details extraction **only for form autofill**; clean, short English/Arabic reply style, dynamic suggested buttons, persistent frontend history.
- Philia-specific extensions: genuine Shopify catalog/collections and page data cached on the backend, genuine product cards, verified Shopify add/remove/change cart requests in theme, consent gates, product price check, exact contact/bespoke/events/corporate form maps.
- The frontend V117 still accepts the old Philia NDJSON backend while migrating, but FastAPI V31 returns **JSON only** (ALF parity). No fake typing.
- Static navigation commands to known pages/bag may be completed in the frontend with zero LLM calls, as they were in V116.

## IMPORTANT: Render deployment changes

ALF uses **Python**, unlike Philia V30.2 on **Node.js**. **This release targets the existing Python service PHILIA2 at https://philia2.onrender.com. Do not use the old Node Render backend URL.**

GitHub repository: `motarek122112/PHILIA2`, branch `main`. The service is already created; keep using that Python Render Web Service. For redeploys, use:

- Runtime: Python
- Build Command: `pip install -r requirements.txt`
- Start Command: `python -m uvicorn main:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/health`
- Environment: copy your existing `GROQ_API_KEY`, `SHOPIFY_STORE_DOMAIN`, `SHOPIFY_STOREFRONT_PRIVATE_TOKEN`, and `SHOPIFY_API_VERSION`, using Render's protected environment settings.
- Set `GROQ_MODEL=openai/gpt-oss-20b` if you want **the same ALF default model**. Your recent Philia logs showed 120B configured; merely uploading the ZIP does not override `GROQ_MODEL` in Render.
- Optional `GROQ_MAX_OUTPUT_TOKENS=1400`, `CATALOG_TTL_SECONDS=300`, `PAGES_TTL_SECONDS=3600`. `GROQ_FALLBACK_MODEL` may be omitted.

Do not upload `.env`/live API keys to GitHub. `.env.example` is only an example.

In Shopify Admin, upload **Theme V119** as unpublished theme, then in **Customize -> Theme settings -> AI backend endpoint** set your **new Python Render service URL** (root URL, not necessarily `/api/chat`). Test the unpublished theme before switching live. Old V116 + Node v30.2 remain your rollback path.

## Endpoints

- `GET /health`: version/model/cache/service status without calling Groq.
- `GET /health/shopify`: cached Shopify product status (may wait for first fetch).
- `GET /health/groq`: **optional manual** provider test, consumes a Groq request. No polling.
- `POST /api/chat`: ALF-style full JSON (not NDJSON).
- `POST /api/action-result`: optional action-timing logging, without customer data.

## Tests

Install dev test dependencies `pip install pytest`, then `pytest -q test_agent.py`.

Tests use a **fake Groq transport and offline Shopify fixture**, not live provider or Shopify mutation. They verify the real Python action/caching contract and that the normal path uses 1 LLM call; form autofill uses a second extraction call like ALF V4.3. A separate frontend Node test and Chromium Liquid-form tests ran during packaging. Live acceptance requires protected API secrets and your deployed store.

## Limitations / accuracy

This migration intentionally changes Philia's real streaming to **ALF-style completed JSON**, to match ALF's response architecture. Display speed on Render depends on cold starts, Groq availability, model setting, prompt size, and quotas; identical numerical latency is not guaranteed by code alone. Rate-limit 429 cannot be eliminated at the account level by software.

No checkout or form submission is automatic, and no service availability is invented. Verified Shopify cart mutations still happen in the browser and are not claimed complete until the cart endpoint responds and the updated cart is verified. Product cards only use handles found in cached actual Shopify data.


## PHILIA2 deployment and integration (2026-10-09)

- GitHub: https://github.com/motarek122112/PHILIA2 (not the previous `philia-ai-backend` repository).
- Render service root: `https://philia2.onrender.com`
- Chat API: `https://philia2.onrender.com/api/chat`
- Health: `https://philia2.onrender.com/health`; expect `version` `31.2.0` once this updated code is deployed.
- Shopify theme: **Philia Flowers V119 PHILIA2**, which explicitly sets the AI backend endpoint to the new Render URL in `config/settings_data.json` and its code fallback.
- Backend keeps ALF-style single Groq JSON response; not streaming.
- `GROQ_API_KEY` and `SHOPIFY_STOREFRONT_PRIVATE_TOKEN` must be configured in Render Environment, never committed to GitHub.
- `render.yaml` is a Blueprint template; a manually created existing Render service uses its own service configuration.
- No repository commits and no live Render changes are performed just by downloading this ZIP.


## V31.2 parity repair
- Uses ALF V4.3 model preference order (20b / 120b / Qwen after any configured fallback), `max_completion_tokens=1400`, SDK retries capped at 2, and 85-second HTTP request timeout.
- One primary request for successful normal conversation; provider retries/fallbacks mean more API attempts **only on failure**, form extraction may add one call.
- HTTP 429 skips extra fallback requests and returns `AI_RATE_LIMIT` with `retry_after_seconds`; a bounded in-memory cooldown prevents immediate duplicate failures on a warm Render worker. (State resets on restart and is per worker.)
- Distinct codes for invalid JSON, network, timeouts, missing key and provider failure. Logs contain timings and token usage, never API credentials or customer message text.
- Kept Philia-specific Shopify catalog, real product actions, forms, historical conversations, and theme layout.
- Theme V119 changes only backend error messaging in `assets/theme.js`; backend URL stays `https://philia2.onrender.com`.
- Free Groq rate limits remain a provider/account constraint, not a backend defect. Live token consumption and speed cannot equal ALF exactly because site content, prompts, and history differ.
