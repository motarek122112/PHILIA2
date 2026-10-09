# Philia AI v30.1 — Groq quota headroom, smaller prompts and truthful stream diagnostics

This is a patch to the ACTUAL Philia backend v30.0 from `Philia_AI_Backend_v30_FULL_WEBSITE_AGENT.zip`.
The Shopify Theme V115 is UNCHANGED. Continue using that existing theme.

## Why user messages failed (what Render logs actually prove)

- Two responses completed in 564ms and 727ms, using 3,098 and 3,247 tokens respectively.
- The third logged `groq_response_headers` but the stream never produced a token. The error was classified `AI_CONNECTION_FAILED`, status null. This does **not** prove the third error was an HTTP 429.
- The fourth had a real provider 429 before opening; the backend slept 9.25s and retried. The follow-up opened a response with just 86 tokens/minute remaining and failed without a first token. This points to quota pressure plus an undiagnosed stream error; it is not definitive proof that every stream error was due to quota.
- Free plan: 8,000 TPM, 1,000 RPD for `openai/gpt-oss-120b`, organization-wide (verify the current account limits). A separate 20B model is also listed at 8,000 TPM, so switching model alone does not solve token throughput.

## Actual changes

- Trimmed the LLM system instruction without changing the action contract or core LLM-first philosophy. It still responds to normal chats directly through one Groq call.
- Request catalog context now indexes 3 verified products and NO product details for an unrelated greeting, versus 8 ranked handles/2 detailed products for relevant shopping context. Pinning recent/selected products and live catalog validation continue unchanged.
- Page excerpts capped to one, shorter excerpts and bounded dynamic page text/history; site action/form map remains intact.
- Server computes a cautious token demand estimate and consults **real preceding Groq rate-limit headers** before consuming another streaming request. If known remaining TPM is insufficient, it sends a truthful temporary rate notice with observed reset time, makes ZERO Groq calls and does not fabricate an answer. It does not use the estimated tokens for charging or as a fake provider status.
- Server calibrates its prompt chars:tokens ratio from successful Groq usage, using a conservative default until measured. Headroom reservations also protect simultaneous requests handled by this one Node process. Other Render replicas do not share the reservations.
- Long provider 429 waits (~9 seconds in user logs) no longer cause a hidden second request. One retry remains ONLY when the provider specifies at most 2 seconds wait; otherwise the user gets the actual wait notice.
- Mid-stream errors with nested numeric HTTP status are now classified accurately; otherwise errors after HTTP headers report their phase and sanitized error class rather than incorrectly claiming all of them were rate limits.
- Output budget capped at 850 tokens per response to bound quota usage. Responses requiring unusually long replies/actions could be truncated: check `finish_reason=length` and increase the cap in code if live tests warrant, balancing quota.
- No changed Shopify action handlers, theme styling, forms, product cards, navigation, history, language decisions, real NDJSON streaming, or LLM-based conversation.

## Deploy

1. Replace backend source files from this ZIP in the SAME GitHub repository, keep the existing Render service/environment secrets. `npm ci`, `npm start`.
2. Remove an unnecessary old `GROQ_MAX_OUTPUT_TOKENS` environment override or set it to `850` (the v30.1 server caps it at 850 regardless).
3. Visit `https://philia-ai-backend.onrender.com/health`: must report `version: 30.1.0`.
4. Keep Shopify Theme `Philia_Flowers_V115_FULL_WEBSITE_AI_AGENT.zip` as is. NO new theme deploy.
5. Test `hello` → `tell me the story of Philia` → `بالعربي` → `عايز ورد` → `في حدود 30` → `وريني` → `التاني` → `ضيفه` → `افتح السلة` with a real Groq quota window. Verify the Shopify mutation; do not assert an add unless it actually completed.
6. Check Render `catalog_prompt`, `groq_request_start`, `token_budget_check`, `groq_response_headers`, `groq_complete` / `request_error`, `request_complete`.

## Local verification (not live)

- `node --test tests/catalog-context.test.mjs tests/quota-headroom-v30_1.test.mjs`: 10/10 passed. Covers prompt index bounding, Gergean real catalog retrieval, history context, token guard, multiple requests, nested SSE 429, stream parsing and action grounding.
- `node --check` on modified JS modules: passed.
- Existing HTTP integration tests in `npm test` need real npm dependencies (express/groq-sdk) and were NOT rerun here; the project environment lacks installed packages.
- Neither live provider throughput, Shopify/cart mutations nor post-deploy client latency was measured.

## Limitations

A shared Groq Free token bucket remains finite. A server-side guard cannot increase it or guarantee uninterrupted chat for unlimited concurrent visitors; a higher capacity subscription/provider will be needed at scale. In-process headroom is advisory if other apps share the same Groq organization/model or Render runs more than one process. Providers may stream errors with no HTTP status; the new phase/class telemetry narrows the cause but cannot identify a specific network fault in a log that has no error code. Avoid polling `/health/groq` because it consumes model quota.
