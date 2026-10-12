# Philia V33 — Production Request System Setup

This backend keeps the existing V32.2 AI engine unchanged and adds a separate request/account/admin subsystem.

## 1. Render PostgreSQL
Create a PostgreSQL database in Render and copy its **Internal Database URL** into `DATABASE_URL` on the Philia backend service.

## 2. Shopify app / App Proxy
The customer portal uses a signed Shopify App Proxy so a browser cannot impersonate another customer.

Create/install a Shopify app for the Philia store and configure:
- App proxy subpath: `philia-briefs`
- Prefix: `apps`
- Proxy URL: `https://YOUR-PHILIA-BACKEND.onrender.com/proxy`

The storefront then calls `/apps/philia-briefs/api/briefs` on the Philia domain. Shopify signs the request and includes the logged-in customer ID.

Set `SHOPIFY_API_SECRET` to the app client secret.

## 3. Shopify Admin API sync
Create an Admin API token with:
- `read_customers`
- `write_draft_orders`

Set `SHOPIFY_STORE_DOMAIN` and `SHOPIFY_ADMIN_TOKEN`.

Every Philia request is then mirrored into **Shopify Admin → Orders → Drafts** with its request reference, status, customer, date, venue, budget and details. Updates/cancellations change the Draft Order tags and custom attributes.

## 4. Email
Set SMTP values and `PHILIA_NOTIFICATION_EMAIL`. New, edited and cancelled requests notify Philia. Customer receives confirmation emails as well.

## 5. Smart merchant dashboard
Set `ADMIN_DASHBOARD_PASSWORD` and `ADMIN_SESSION_SECRET`.

Open:
`https://YOUR-PHILIA-BACKEND.onrender.com/admin`

Dashboard includes status totals, 24h response alerts, upcoming 14-day events, search/filter, quote amount, internal notes, audit timeline and CSV export.

## 6. Optional automated daily summary
Create a Render Cron Job that POSTs to `/cron/brief-summary` with header `X-Cron-Secret: <CRON_SECRET>` once daily.

## Important
A Shopify theme cannot directly create a new native page inside Shopify Admin. This build solves that in two production-safe ways:
1. Every request is automatically visible natively in Shopify Admin as a Draft Order.
2. The dedicated Philia Request Command Center provides the richer database/dashboard experience and is iframe-ready for a future embedded Shopify app shell.
