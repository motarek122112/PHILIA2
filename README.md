# Philia AI — ALF V4.3 engine, Philia-specific information

Built by copying the **ALF V4.3 orchestration**: identical `/api/chat` contract; model fallback sequence; 40-message history; JSON response format; 85-second deadline; warm-up and frontend retry strategy. Only business knowledge, form patch schema and safe Shopify-specific action validation are adapted.

## Render
Python runtime. Build `pip install -r requirements.txt`. Start `python -m uvicorn main:app --host 0.0.0.0 --port $PORT`. Configure `GROQ_API_KEY`, `GROQ_MODEL` (20b to match ALF).

## Shopify
Use accompanying V120 theme. Theme uses the adapted ALF V7 frontend agent and the same JSON API schema.

## Behavior limits
Cannot guarantee same token usage or milliseconds on a different website. Groq and Shopify live tests must occur after deployment. Fallback model retries may hit shared Groq quota. All carts are validated against actual Shopify `/products/handle.js` and `/cart/add.js` in the browser.
