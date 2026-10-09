# Philia AI Backend v30.1 + Theme V115 — Token headroom and stream diagnostics

**Current release note:** See `README_V30_1_RATE_LIMIT_DIAGNOSIS.md` for the
actual v30.1 changes, deployment and limits. The older release notes below are
historical and must not be mistaken for the current version. Theme V115 does
not need any changes for this backend-only patch.

---

# Historical notes (v29.4 + Theme V114)

**Deployment pairing:** `Philia_AI_Backend_v29_4_QUOTA_OPTIMIZED.zip` and `Philia_Flowers_V114_QUOTA_OPTIMIZED.zip` (V114 was built from the supplied, functioning V112, NOT from the broken/unavailable V113 ZIP). Both must be deployed; keep the same Render service/environment variables, Shopify store and browser history namespace.

## Changes verified in this update

- v29.3 sent the complete cached Shopify catalog and all its variants to Groq for EVERY user message, including greetings. Server cache avoided repeated Shopify fetches but did not avoid provider token accounting. On a shared free Groq quota, repeated large prompts can produce `429` even when messages are simple. A `429` is a real provider quota refusal, not a language/semantic understanding bug.
- v29.4 sends a small, ranked **verified catalog index** (up to 32 products, including up to five with detailed real variant metadata) on each request. This is deterministic retrieval/knowledge packing only, NOT an intent router or a source of canned answers. A single Groq request still decides text and structured actions. The FULL cached catalog remains available for Shopify card/action validation; nothing is invented. If the store has more than the indexed products, the model is explicitly told the context is only a partial index, so it must not claim exhaustive stock.
- User-history character budget is 11,500 (up to 40 short messages), with persistent client memory and last suggested product order retained. Backend catalog TTL is still 300s; Shopify is not fetched on every turn.
- V112 sent Shopify's UI locale for chat and lacked v29.3's quota/dialect notice. V114 separates `locale` (user conversation) from `storefront_locale` (store language). Provider `retry_after_seconds` and minute/day scope are shown in clear Arabic/English notices and respected in tab storage across navigation. No fake replies, no automatic hidden retries, no artificial typing waits. Rate-limit notices are errors, not saved simulated AI messages.
- All existing product cards, cart operations, navigation, chat UI styling and history mechanisms remain. Only `assets/theme.js` differs from V112, and only assistant/transport logic changes there.
- `/health` reports `29.4.0`. `/health/groq` is an OPTIONAL provider probe that consumes quota; do not poll it. Read the `request_error` event in Render for actual rate-limit scope and retry duration; all such logs are sanitized. `groq_request_start.input_characters`, `catalog_prompt.characters`, `groq_complete.token_usage` provide evidence for after-deploy evaluation.

## Tests and limitations

- 22 relevant Node unit/integration tests passed using an injected fake Groq stream and a **temporary minimal Express test shim** because this evaluation container cannot download npm dependencies (registry DNS unavailable). The shim is NOT shipped and these are NOT a live provider test, real Express/SDK test, or Shopify end-to-end test.
- 15 Node VM assertions passed for the actual theme's language/cooldown/helper code and request contract. Both modified JS files passed `node --check`. No full browser/Shopify deployment was performed.
- `verification-results/v29_4-catalog-comparison.json` contains a **synthetic fixture** before/after character measurement, not actual Groq token usage. The previously shared 19,479-character production request was from an older version and is not a new measurement.
- An actually exhausted organization-wide **daily quota cannot be reset by code**. Wait for the provider reset or increase the Groq plan capacity. Do not switch models/keys to evade a limit. For real validation run `node tests/live-acceptance.mjs https://philia-ai-backend.onrender.com` AFTER deployment; the script needs real Groq capacity and includes action-metadata tests, not the browser cart mutation itself.

## Install / deploy

1. Replace the Render/GitHub repository files with the backend ZIP contents. Do NOT upload `node_modules`, and retain existing private environment variables. Render's `npm install` build resolves the real Express, Groq SDK and other dependencies.
2. Confirm `/health` says `version: 29.4.0`, and the model configured is the intended `openai/gpt-oss-20b` unless you have changed it in Render.
3. Upload the V114 theme ZIP as a new Shopify theme (don't overwrite a working live one without testing). Use Shopify Preview first, verify chat on mobile/desktop, then publish.
4. Test `هلا` → `عايز ورد` → `في حدود 30` and `hello` → `i need flowers`, plus real product cards, correct selection, and a cart operation. Check Render `request_error` for any failed attempts. Real new Groq usage/latency can be evaluated **only** after running against your service.

---

## Historical v29.3 notes (preserved below for reference only)

# Philia AI Backend v29.3 + Theme V113 — conversation language and real quota handling

This release builds on the actually deployed v29.2 backend and the latest V112 theme. Deploy this backend ZIP to the same Render service, then upload the V113 theme. The site and chat layout, CSS, product records/cards, actions, history namespaces, model, readable replies and the one-request streaming protocol are preserved.

## Installation

1. Replace the existing backend source in its GitHub repository with this ZIP's contents. Keep the existing Render service, domain, secrets and Shopify tokens.
2. Render uses `npm install` and `npm start` as before. `package-lock.json` is included; `npm ci` also works.
3. In Render Environment keep the real `GROQ_API_KEY`, `SHOPIFY_STORE_DOMAIN` and `SHOPIFY_STOREFRONT_PRIVATE_TOKEN`. The currently observed live store is `philia-flowers-kw.myshopify.com`. The sample env file contains no secrets and does not replace the service environment.
4. Set `GROQ_MODEL=openai/gpt-oss-20b`. It uses supported `reasoning_effort=low`, streamed JSON Object Mode and 1000 maximum completion tokens. There is no separate router, classifier, extraction call, SDK retry or model-fallback chain. Legacy `GROQ_CHAT_MODEL`, `GROQ_ROUTER_MODEL` and `GROQ_FALLBACK_MODEL` are ignored.
5. Keep `SHOPIFY_API_VERSION=2026-10`. Optional values: `CATALOG_TTL_SECONDS=300`, `PAGES_TTL_SECONDS=3600`, `GROQ_TIMEOUT_MS=30000`, `GROQ_MAX_OUTPUT_TOKENS=1000`.
6. Verify `/health` reports `version: 29.3.0`. `/health/shopify` checks Shopify. `/health/groq` explicitly performs a small paid/token-consuming provider probe; normal health/warm-up does not call the LLM. Repeated provider health probes also use the organization's quota.
7. Upload `Philia_Flowers_V113_CONVERSATION_LANGUAGE_AND_QUOTA.zip`. The V113 theme sends conversation and storefront languages separately and displays the actual provider retry duration. Its four modified files are `assets/theme.js`, `layout/theme.liquid`, `locales/en.default.json` and `locales/ar.json`; all other 118 files are byte-identical to V112.

## Request path

`ask → POST /api/chat → cached catalog + bounded conversation + saved memory → one streamed Groq completion → incremental reply deltas + validated metadata → existing product cards / deterministic Shopify Ajax actions`

JSON keys are requested in `actions, reply, products, memory` order. The reply string is decoded incrementally from the provider stream. JSON metadata never appears in the conversation. Automatic action replies are withheld: the browser displays success only after the real action succeeds. Explicit additions do not require another LLM call or redundant confirmation. Multiple variants without a selected option use the existing button styles to ask for that real option.

The normal conversation never uses keyword routing or canned replies. Action and URL validation is deterministic and separate from conversation understanding. The backend accepts at most 40 messages / 24,000 characters; the theme sends at most 40 / 20,000 characters plus card order. Guest sessionStorage and signed-in localStorage retain the same V80 namespaces and migrate existing conversations in place. Memory is per thread and is sent back by the browser, so navigation, Render restarts and backend cache eviction do not erase it. This remains browser/device history, not cross-device sync.

## Catalog and cold starts

Catalog and page knowledge load at process startup and health warm-up. Products use a five-minute cache, pages one hour. Concurrent misses share one in-flight fetch; recently expired entries return immediately and refresh in the background. Products paginate up to 600 records and expose a completeness flag. Cold/empty catalog loads can still take Shopify network time. Pages never block a normal message. Cache failure is not converted into invented products; the model receives an explicit unavailable catalog.

The theme preconnects and issues one health warm-up per tab session; navigation does not repeat it and there is no polling. A cold chat request waits normally. Client disconnect and timeout abort the provider request. An idle Render instance may still sleep later; this architecture does not claim to eliminate platform startup time or change the hosting plan.

## Logging

Structured logs: `request_received`, `catalog_lookup`, `groq_request_start`, `groq_first_token`, `first_visible_token`, `groq_complete`, `request_complete`, `shopify_action`. Timings are milliseconds. The browser sends action type, opaque request ID, success flag and duration to `/api/action-result`; it never sends customer content to the timing log. The frontend also logs first visible text and total duration internally. No keys, prompts, chat content, names, emails, buyer IPs or cart details are logged.

Connection, rate-limit, interrupted-stream and protocol errors are explicit UI notices. There is no nonstreaming fake-typing recovery and no automatic retry that might duplicate a cart operation.

## Actual investigation — v29.3 / V113

The live Render health endpoint reported v29.2.0 with both provider and Shopify configured. A real `بدي ورد` request following an Arabic greeting, with the old frontend's `locale: en`, reproduced an English recommendation. Repeating the same transcript with `locale: ar` returned an Arabic recommendation. Both probes completed successfully; they did not establish which minute/day quota caused the user's earlier failures. The captures are retained in verification-results; these test prompts contain no customer personal data.

The underlying language mismatch was concrete: V112 changed the chat UI to Arabic based on the user's message, but still sent `locale: getLang()` from the storefront. V113 sends the actual conversation language as `locale` and the UI language separately as `storefront_locale`. The backend also derives a language default from the user's letters/history independently, so even older frontends with English UI cannot silently override an Arabic message. This only produces language metadata, never shopping intents or conversation replies.

The ONE main LLM completion understands explicit language/dialect requests and can patch `response_language` and `response_dialect` into the existing per-thread persistent memory. Confirmed preferences survive navigation and product names in English. The system explicitly says to honor language preferences from earlier user messages even if those requests failed. Explicit requests for another language and Franco Arabic remain LLM-understood. No translation call, semantic router, regex-generated reply or canned conversation is added.

## Provider retry duration — v29.3 / V113

The backend shares a short-lived cooldown only after an actual Groq 429 supplies a valid retry duration. Requests during that known window receive an explicit error with the remaining duration and make zero Groq requests; they do not fetch the catalog first. After expiry, the next normal message makes one streamed completion. No retry, polling, delayed queue or automatic action execution is scheduled. If the provider omits a retry duration, the code does not guess one. The state is local to each backend process, not a distributed quota system.

The theme retains the same observed cooldown in tab sessionStorage across navigation and shows an honest provider-limit notice instead of repeatedly calling Groq during the reported wait. Failed user messages remain in the real conversation history, including language requests. A daily-limit notice is used only if the provider explicitly identifies a daily quota; otherwise the UI stays noncommittal. Seconds/minutes/hours are displayed approximately using the provider's reported duration. These are connection/status notices, not substitute AI replies. Normal conversations are never answered locally.

This does not provision more quota. Repeated daily limits still require waiting for reset or arranging sufficient provider capacity. Existing free quotas can also be shared with other projects using the same organization/model. The user's earlier 429 scope remains unknown without its corresponding Render error log; the new error metadata and logs distinguish that scope when Groq supplies it.

## Rate-limit diagnosis — v29.2

The V112 temporary usage notice means the backend received HTTP 429 from Groq. It does not distinguish minute and day quotas. The general connection notice also covers provider authentication/request/server errors, SDK timeouts and an incomplete JSON envelope; it cannot establish their cause on its own. A previous successful 617 ms request does not identify why a later request failed.

`request_error` now includes fixed `provider_error_kind` labels, `provider_status`, and `rate_limit_scope` when Groq's error explicitly identifies TPM, TPD, RPM, RPD, ITPM or OTPM. Unknown scope stays null. `rate_limit` includes only sanitized numeric counters, reset durations and `retry_after_seconds`; raw provider errors and organization IDs are never logged. A timeout from the SDK is now recognized even before the outer abort timer fires. A truncated JSON envelope records `finish_reason: length` when supplied by the stream.

Interpret examples:

```json
{"event":"request_error","code":"AI_RATE_LIMIT","provider_status":429,"provider_error_kind":"rate_limit","rate_limit_scope":"tokens_per_minute","rate_limit":{"retry_after_seconds":6}}
```

This indicates a minute token limit; wait the provider's reported duration. `tokens_per_day` or `requests_per_day` indicates a daily quota. Use the actual reset/limits in the Groq account, or provision sufficient capacity. Do not rotate keys to evade an organization-wide limit. `authentication_or_permission` with 401/403 requires fixing the existing key or model permission. `invalid_provider_request` with 400 requires checking request compatibility; `provider_unavailable` with 5xx is a provider outage. Do not infer any of these from the UI notice alone.

`groq_response_headers` records rate-limit counters from the SAME streamed completion, with no extra provider request. Groq documents request headers as daily counts and token headers as minute counts. `groq_complete.token_usage` records prompt, completion, total, cached prompt and reasoning token counts when supplied. Missing usage fields remain absent/unknown rather than being reported as zero. The final contentless stream chunk is processed for usage and finish reason.

References: [Groq rate limits](https://console.groq.com/docs/rate-limits), [error codes](https://console.groq.com/docs/errors), [prompt caching](https://console.groq.com/docs/prompt-caching). Limits vary by account; inspect the actual account's limits. This release does not increase provider quotas or claim to remove every 429.

## Smaller requests — v29.2

The Shopify fetch cache and the provider's token accounting are separate. Previously every message still sent the verbose catalog JSON to Groq. Product/variant/option field names are now defined once as columns, with all existing descriptions, tags, prices, availability, handles, variant IDs and option values retained in positional rows. The full original records still drive cards and action validation. The compact serialization is cached once per catalog snapshot, not rebuilt per message. No keyword filter, intent classifier, extra LLM call or reduced catalog scope is added.

Static store knowledge remains before dynamic session data; changing cache age now lives in session context. Groq supports automatic prefix caching for the default model, but cache hits are controlled by Groq and are not guaranteed. Only reported cached token counts establish a hit.

An offline comparison on the same 24-product public snapshot reduced catalog JSON from 12,677 to 9,470 characters (25.30%) and the captured greeting request from 17,002 to 13,916 characters (18.15%). Full product/variant facts were decoded and compared for equality. These are character counts, not token measurements, and this fixture is not the exact 19,479-character production request. Production token usage and post-deploy latency require the new Render/Groq logs.

## Verification

`npm test` runs deterministic architecture/streaming/cache/grounding tests without network or credentials.

After deploying v29.3 to the service with its existing credentials, run:

```sh
node tests/live-acceptance.mjs https://philia-ai-backend.onrender.com
```

This sends the user's exact Arabic, English and typo conversations to the real LLM and records before/after-comparable first visible token and total times. It fails on an old backend version, provider error or incorrect selection/action metadata. This CLI does not execute a customer's cart; test addition, change, removal and navigation in the updated Shopify theme browser session.

This release was checked with 10 backend architecture tests and Chromium rendering tests on desktop/mobile. Controlled provider/cart fixtures covered the 48 literal Arabic/English/typo turns, plus table-to-list rendering, bold labels, ordered options, streaming, escaped HTML and restored history. Results are included in verification-results. These are local rendering/integration checks, not a live Groq benchmark or a customer-cart mutation on the deployed shop.

The v29.2 update passes 19 automated tests: the existing 10 architecture checks plus catalog fact preservation, sanitized quota/usage diagnostics, static prefix stability, provider header extraction, actual SDK streaming with a mocked fetch, SDK 429 propagation without retries, and truncated-stream classification. The earlier V112 browser results are retained as historical formatting coverage of that release. Those earlier v29.2 local checks did not measure post-deploy quota or latency. `verification-results/rate-limit-payload-comparison.json` records the offline comparison and its scope.

For v29.3, 25 backend tests pass, including language separation, numeric contextual messages, persistent dialect patches, provider cooldown expiry and zero calls during a reported wait. Desktop/mobile Chromium fixtures cover the literal Arabic, English and typo acceptance conversations (48 turns across both viewports), formatting/real delta rendering, product cards, deterministic cart additions/quantity/removal, navigation/history, and the new language/quota behaviors. Fixtures exercise implementation and rendering, not the new model's live semantic understanding. The two real production language probes were against v29.2 using identical history and different locale metadata; v29.3 has not been deployed or benchmarked against the real provider here. Do not interpret these as post-deploy v29.3 latency measurements. The live acceptance script now refuses any version other than 29.3.0 and stops on a quota error without retrying.

## Readable replies — v29.1 / V112

This update preserves the v29 LLM-first architecture and changes reply presentation. The model is instructed to use a short introduction, clear bullets or numbered product options, blank lines, and bold names instead of pipe-delimited tables. The companion theme renders headings, bold labels, real ordered/unordered lists and code safely during the real stream and after reload. Historical Markdown tables are displayed as stacked items with separate labeled details, so they do not produce raw pipes or horizontal overflow. HTML remains escaped. Mixed Arabic/English official names use bidirectional isolation; Arabic replies have their own text direction and font even when the storefront locale is English.

Deploy the theme update to fix rendering of existing replies; deploy this backend update too to apply the new output-format guidance. No extra LLM request, typing delay, routing change, cart change or storage namespace change was added.

## v29.5 — short-window Groq 429 recovery and prompt-budget reduction (2026-10-09)

This release is **backend only**. Use with the existing `Philia_Flowers_V114_QUOTA_OPTIMIZED.zip` storefront theme; do not replace that theme with an older build. Real NDJSON provider streaming, model-led conversation (one successful request per turn), persistent frontend history, verified Shopify cards/cart/navigation and Arabic language metadata remain unchanged.

Changes:
- `page-selection.mjs`: official Shopify pages are kept in server-side TTL cache but only a bounded path/title index and up to two pertinent short official excerpts go into the model message. Earlier versions sent all cached page summaries to Groq on *every* user turn.
- `catalog-selection.mjs`: index defaults to 12 products and detailed options for up to 3, pins recent choices, prioritizes the most recent user message and expands common Kuwaiti/Arabic flower/Gergean vocabulary solely for Shopify **record retrieval**. The LLM (not a regex router) still chooses the reply and site action; product verification continues against the full cached catalog.
- `server.mjs`: stable conversation/system/site navigation instructions are before dynamic catalog/page/session/history fields to enable Groq's automatic prefix caching when supported. History size budget is 7500 characters across up to 36 messages (plus compact shopping memory). This changes provider input only, not the existing saved frontend chat history.
- One bounded retry **only if** Groq rejects the request with 429 *before any streamed tokens*, gives a provider-specified retry-after `<= 25` seconds, and the scope is not a daily quota. It waits the exact delay (plus 250ms) once and retries the same completion. Requests that already streamed content, daily limits, unreported/long waits and Shopify cart mutations are **not** retried. This does not circumvent provider limits. Log `provider_short_retry` records the wait and `request_complete.llm_calls` is 2 for a rejected-then-retried attempt, 1 normally.
- Stronger prompt distinction: requests to **go to** products should navigate to `/collections/all`, whereas requests to **show** suggestions within chat should produce real product cards. Actual language/action quality must be verified with live Groq after deployment.
- Version `/health` is now `29.5.0`.

Live debugging: look at sanitized Render events `catalog_prompt`, `page_prompt`, `groq_response_headers`, `provider_short_retry`, `groq_complete`, `request_error`, `request_complete`. No raw customer text, Groq keys or provider organization IDs are logged. Groq rate limits apply across all requests in the account; production capacity may require a higher Groq plan. No automatic retry occurs for daily quotas.

**Deploy:** Replace the files in the existing GitHub/Render backend repository, keep the current environment secrets and service URL, deploy, and check GET `/health` for `29.5.0`. There is no theme change in this release. `/health/groq` consumes provider tokens: do not poll it. Test `هلا` → `عايز ورد` → `عايز قرقيعان` → `الثني` → `ضيفه`, then `وديني للمنتجات` and `افتحلي السله` on the actual Shopify site. For safety, verify the cart action genuinely succeeded before showing success.

**Testing limitation:** Node integration tests in the development environment used only local temporary Express/cors/Groq stubs because real npm packages and customer provider secrets were not accessible. These stub packages are not included in the shipped ZIP. Run `npm ci && npm test` with actual dependencies in CI/Render. Live Groq quota, real Shopify cart and true production latency were NOT measured here.

## v30.0 — Philia Full Website AI Agent (Theme V115)

This is a targeted upgrade on v29.5, **not an ALF content transplant**. It retains the
same Groq LLM-first conversation (one successful streaming completion per message;
one extra request can occur only for a provider-prescribed short 429 retry), real
Shopify catalog cache, session memory, real cart mutation checks and NDJSON streaming.

### Actual Shopify theme capability map

`agent-site.mjs` defines the allowed pages, 4 real Shopify contact-form schemas,
and whitelisted actions. Its exact fields were read from the current V114 Liquid:

- `contact` /pages/contact: name, email, body
- `bespoke` /pages/bespoke-orders: occasion, budget, required_date, colours, body
- `events` /pages/events-weddings: event_date, guest_count, venue, budget, body
- `corporate` /pages/corporate-events: company, quantity, body

A `form_patch` **never submits**. The V115 frontend navigates to the actual form,
uses only exact existing `name` attributes, dispatches native `input`/`change`,
checks resulting `.value`, highlights changed fields, leaves existing nonmatching
customer values alone, then persists the actual number modified. When a new page
is needed, the approved patch is staged in sessionStorage and applied only if
its path, active conversation, and 2-minute expiry match. Customer reviews and
submits the original Shopify contact form manually.

Additional `search(query)` uses the existing Shopify `/search?q=` results page,
`open_whatsapp` reads the live theme's `data-whatsapp` setting (validated host),
and `open_account` is enabled only when the current header has a Shopify account
link. Navigation still uses validated store paths; cart actions preserve Shopify
`/cart.js` verification. Non-auto actions are context-dependent 1–4 button
suggestions; button clicks require no new LLM request. They are saved in the
existing per-session/per-account chat archive (the archive key is unchanged).

### Environment and deployment

Keep the existing GROQ_API_KEY, SHOPIFY_STOREFRONT_PRIVATE_TOKEN, Render URL and
SHOPIFY_STORE_DOMAIN. Set `GROQ_MAX_OUTPUT_TOKENS=1050` if you previously set
850 and want room for structured actions; output limit is still bounded. Publish
the backend to Render first; GET `/health` must report `30.0.0`; then upload
Theme V115. No accounts/payment/booking backend was invented.

### Verification

`node --test tests/agent-v30.test.mjs` tests the actual action/field validator,
stream parser, memory, and fixture snapshots of the corresponding V114 Liquid.
`python tests/browser-agent-v30.py` performs real Chromium DOM edits against
form HTML copied from those actual Liquid snippets. These are local tests,
**not Shopify production tests or live Groq language-intelligence tests**.
Full inherited npm tests require `npm ci` (all packages available). Compare
errors and times on deployed Render before claiming live outcomes.
