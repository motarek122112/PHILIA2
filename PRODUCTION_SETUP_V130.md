# Philia V130 — Shopify-native request system

No PostgreSQL database is used.

Required Render environment variables:
- `SHOPIFY_SHOP` — store handle only, without `.myshopify.com`
- `SHOPIFY_CLIENT_ID` — from Philia Request System app
- `SHOPIFY_CLIENT_SECRET` — from Philia Request System app
- `SHOPIFY_ADMIN_API_VERSION=2026-10`

The installed Shopify app must include these scopes:
- `write_app_proxy`
- `write_draft_orders`
- `write_metaobject_definitions`
- `write_metaobjects`

App Proxy:
- Prefix: `apps`
- Subpath: `philia-briefs`
- Proxy URL: `https://philia2.onrender.com/proxy`

Optional merchant email notification settings:
- `PHILIA_NOTIFICATION_EMAIL`
- `SMTP_HOST`
- `SMTP_PORT=587`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL`

Optional request dashboard:
- `ADMIN_DASHBOARD_PASSWORD`
- `ADMIN_SESSION_SECRET`
- Open `https://philia2.onrender.com/admin`

Storage is Shopify Metaobjects (`Philia Requests`) and each request is mirrored into Shopify Draft Orders.
