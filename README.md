# Philia AI Backend V32.2 — ALF Engine + Verified Shopify Actions

This backend keeps the ALF V4.3 Python/FastAPI/Groq conversation architecture and JSON action contract, with Philia-specific website content.

## What changed in V32.2
- Accepts the live Philia Shopify product snapshot through the same ALF request envelope (`enquiry`).
- Treats that snapshot as `storefront_products` inside model context.
- Product add/navigation actions are validated against real handles supplied by the theme.
- Product discovery is instructed to return useful real product actions instead of a text-only catalogue.
- A simple "yes" can confirm add-to-cart only when the immediately previous assistant message explicitly asked to add the selected product.
- Compliments never auto-add products.
- Unverified "added to cart" claims are rewritten before the browser executes the real Shopify action.
- Browser remains the authority on whether cart/form/navigation actions actually succeeded.

## Render
Build: `pip install -r requirements.txt`
Start: `python -m uvicorn main:app --host 0.0.0.0 --port $PORT`

Set `GROQ_API_KEY`. The ALF default model remains `openai/gpt-oss-20b` unless `GROQ_MODEL` overrides it.
