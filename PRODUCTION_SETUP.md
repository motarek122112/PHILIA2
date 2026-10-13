# Philia Flowers — Shopify Native Requests (Backend V34.1 + Theme V130)

These two ZIPs must be used **together**. No PostgreSQL database is used.

## Deployment order

1. Upload the **contents** of the Backend V34.1 ZIP to the existing GitHub repo linked to Render service **PHILIA2** (`https://philia2.onrender.com`). Do not upload the ZIP as a single file into GitHub.
2. Verify these Render Environment Variables are set (never expose their values in screenshots):

   - `SHOPIFY_SHOP=philia-flowers-kw` — the actual original `.myshopify.com` subdomain without suffix, if it matches your Shopify Admin store domain.
   - `SHOPIFY_CLIENT_ID` — Shopify Dev Dashboard app's Client ID.
   - `SHOPIFY_CLIENT_SECRET` — Shopify Dev Dashboard app's Client secret.
   - `GROQ_API_KEY` — preserve your existing AI credential.
   - `SHOPIFY_ADMIN_API_VERSION=2026-10` (optional; this is the default).
   - `ALLOW_UNSIGNED_PROXY=false` (required for secure production).

   If old `SHOPIFY_STORE_DOMAIN` remains set, the backend prefers `SHOPIFY_SHOP` when present. Do not add `DATABASE_URL`.

3. Wait for **Deploy succeeded / Live**. Check Render logs for `[PHILIA REQUESTS] Shopify-native Metaobject storage ready`. If setup has a missing scope or token issue, logs will say initialization deferred.
4. On Shopify Dev Dashboard, app **Philia Request System**, ensure **V2 Active / installed on Philia** and App Proxy:

   - Prefix `apps`
   - Subpath `philia-briefs`
   - Proxy URL `https://philia2.onrender.com/proxy`

5. Open your storefront URL at `/apps/philia-briefs/api/briefs/health`. A configured proxy/backend should respond with JSON including `"ok":true` and `"storage":"shopify_metaobjects"`. If the browser shows a Shopify 404 or an HTML login page, the proxy is not connected correctly.
6. Upload Theme V130 in **Shopify → Online Store → Themes → Add theme → Upload zip file**. Keep it **unpublished** while testing. Theme Settings → Requests & customer portal → `Request system App Proxy base` should be `/apps/philia-briefs` and enabled.
7. Sign in to a real customer account on the **storefront** before sending a test event brief. Submit one test from Events / Wedding, then verify it appears in **Shopify Admin → Content → Metaobjects → Philia Requests** and **Orders → Drafts**.
8. In the storefront, open account icon → My Philia Requests; edit the request and cancel it, verifying the status and audit history in Shopify Admin. Do not test with real customers until this succeeds.
9. If desired, configure email credentials under Render so New / Edited / Cancelled requests generate email messages:

   - `PHILIA_NOTIFICATION_EMAIL` — merchant inbox
   - `SMTP_HOST`, `SMTP_PORT=587`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`

   **Without SMTP, no cancellation email is sent.** The cancellation still updates Shopify Metaobjects / Draft Orders. Email status must not be assumed from a saved request.
10. Publish V130 after the live tests pass, and retain your published theme as a rollback until then.

## What the merchant can manage

- **Shopify Admin → Content → Metaobjects → Philia Requests**: the central request record, customer identity at time of submission, status, dates, details, quote amount, internal note, cancellation reason, audit JSON.
- **Shopify Admin → Orders → Drafts**: an optional zero-value commercial mirror of each request. This is a draft for tracking, not an actual payment or completed purchase. Do not send an invoice for a zero-value request line.
- Theme Editor settings control the **interface**, not live customer database entries.

## Important functional limits

- Customer self-service management requires login **before submitting**; guest submissions remain valid but are not automatically claimed by an account created later. Guests need to contact Philia using the reference number.
- No SMTP means no email notifications.
- Shopify app-proxy verification plus ID matching prevents customers from reading another customer's request.
- The merchant-facing operations happen in Shopify Admin. This is not an embedded, custom Shopify Admin app dashboard.
- Shopify rendering, permissions, app proxy, and live email delivery cannot be proven by offline unit tests. Perform the live acceptance steps above.
