# Philia Flowers — AI Backend + Shopify-Native Requests V34.1

FastAPI Render backend preserving Philia AI endpoints from the supplied backend and adding Shopify Metaobjects-based request lifecycle. Does **not** require PostgreSQL.

## Source
- `main.py`: existing Philia assistant endpoints (unchanged except router mount carried over from uploaded V34).
- `briefs_system.py`: signed Shopify App Proxy, access token handling, request Metaobjects, Draft Order mirroring, optional SMTP notifications.
- `requirements.txt`, `render.yaml`, `Procfile`: hosting.
- `env.example`: environment variable names with no credentials.
- `PRODUCTION_SETUP.md`: deployment / acceptance checklist.

## Limitations
Guest submissions are not automatically associated with a later-created Shopify account; sign-in before submitting for online editing/cancellation. Email notices require configured SMTP. This backend cannot inject a custom admin app page into Shopify Admin; requests are managed in Shopify native Metaobjects and Draft Orders.

Read `PRODUCTION_SETUP.md` before publishing the paired Theme V130.
