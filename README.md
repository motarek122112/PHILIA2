# Philia Flowers AI — ALF Uniforms V4.3 Architecture Adaptation (V31)

This is a *real FastAPI/Groq backend adapted from the ALF architectural flow*, with **Philia-specific website knowledge**, Shopify product data, and Philia actions. It replaces Philia's Node.js LLM pipeline; it does not copy ALF uniform content.

## Architecture

Visitor -> Philia Theme V117 `assets/theme.js` -> POST `/api/chat` -> FastAPI Pydantic `ChatPayload` -> last 40 messages plus saved session context -> compact **live Shopify catalog cache** -> **one** Groq chat completion in `response_format=json_object` -> validated Philia JSON (`reply, actions, auto_action, context, products`) -> Philia frontend real action execution -> Shopify/cart/DOM verification.

- Matching ALF: Python FastAPI, Groq SDK, full JSON responses (not streamed), one model completion for normal chat, optional second confirmed-details extraction **only for form autofill**; clean, short English/Arabic reply style, dynamic suggested buttons, persistent frontend history.
- Philia-specific extensions: genuine Shopify catalog/collections and page data cached on the backend, genuine product cards, verified Shopify add/remove/change cart requests in theme, consent gates, product price check, exact contact/bespoke/events/corporate form maps.
- The frontend V117 still accepts the old Philia NDJSON backend while migrating, but FastAPI V31 returns **JSON only** (ALF parity). No fake typing.
- Static navigation commands to known pages/bag may be completed in the frontend with zero LLM calls, as they were in V116.

## IMPORTANT: Render deployment changes

ALF uses **Python**, unlike Philia V30.2 on **Node.js**. **Do not just upload these files to the current Node Render service expecting `npm start` to work.**

Safest migration: keep the current Node service unchanged while testing a second Render **Python Web Service** from this GitHub repo/branch. In the new service set:

- Runtime: Python
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/health`
- Environment: copy your existing `GROQ_API_KEY`, `SHOPIFY_STORE_DOMAIN`, `SHOPIFY_STOREFRONT_PRIVATE_TOKEN`, and `SHOPIFY_API_VERSION`, using Render's protected environment settings.
- Set `GROQ_MODEL=openai/gpt-oss-20b` if you want **the same ALF default model**. Your recent Philia logs showed 120B configured; merely uploading the ZIP does not override `GROQ_MODEL` in Render.
- Optional `GROQ_MAX_OUTPUT_TOKENS=1100`, `CATALOG_TTL_SECONDS=300`, `PAGES_TTL_SECONDS=3600`. `GROQ_FALLBACK_MODEL` may be omitted.

Do not upload `.env`/live API keys to GitHub. `.env.example` is only an example.

In Shopify Admin, upload **Theme V117** as unpublished theme, then in **Customize -> Theme settings -> AI backend endpoint** set your **new Python Render service URL** (root URL, not necessarily `/api/chat`). Test the unpublished theme before switching live. Old V116 + Node v30.2 remain your rollback path.

## Endpoints

- `GET /health`: version/model/cache/service status without calling Groq.
- `GET /health/shopify`: cached Shopify product status (may wait for first fetch).
- `GET /health/groq`: **optional manual** provider test, consumes a Groq request. No polling.
- `POST /api/chat`: ALF-style full JSON (not NDJSON).
- `POST /api/action-result`: optional action-timing logging, without customer data.

## Tests

Install dev test dependencies `pip install pytest`, then `pytest -q tests`.

Tests use a **fake Groq transport and offline Shopify fixture**, not live provider or Shopify mutation. They verify the real Python action/caching contract and that the normal path uses 1 LLM call; form autofill uses a second extraction call like ALF V4.3. A separate frontend Node test and Chromium Liquid-form tests ran during packaging. Live acceptance requires protected API secrets and your deployed store.

## Limitations / accuracy

This migration intentionally changes Philia's real streaming to **ALF-style completed JSON**, to match ALF's response architecture. Display speed on Render depends on cold starts, Groq availability, model setting, prompt size, and quotas; identical numerical latency is not guaranteed by code alone. Rate-limit 429 cannot be eliminated at the account level by software.

No checkout or form submission is automatic, and no service availability is invented. Verified Shopify cart mutations still happen in the browser and are not claimed complete until the cart endpoint responds and the updated cart is verified. Product cards only use handles found in cached actual Shopify data.
