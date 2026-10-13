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


## V34.2: Shopify store domain alias fix

Shopify can report the original myshopifyDomain and its newer branded primary domain differently.
Set `SHOPIFY_SHOP` to the verified original Shopify `myshopifyDomain` prefix (not the branded domain),
`SHOPIFY_STORE_DOMAIN` to the store's current branded primary domain if needed, and optional
`SHOPIFY_PROXY_ALLOWED_SHOPS` to an explicit comma-separated list of verified aliases.
The app-proxy HMAC is still checked first. Customer ownership rules are unchanged.
If a mismatch remains, Render Logs now contain `[PHILIA PROXY] signed shop mismatch` with
public domain values for diagnosis, but no secrets or customer information.
