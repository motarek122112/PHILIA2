// Bounded retrieval over REAL Shopify data. This ranks factual store records;
// it never routes a conversation, generates replies or decides site actions.
const MAX_INDEX = 8;
const MAX_DETAILS = 2;
const firstMoney = value => {
  const match = String(value || '').match(/\d+(?:\.\d+)?/);
  return match ? Number(match[0]) : NaN;
};
const safeArray = (value, max) => (Array.isArray(value) ? value : []).slice(0, max);
const normalize = value => String(value || '').normalize('NFKC').toLocaleLowerCase()
  .replace(/[أإآٱ]/g, 'ا').replace(/ى/g, 'ي').replace(/ة/g, 'ه')
  .replace(/[\u064B-\u065F\u0670ـ]/g, '');
const words = value => new Set(normalize(value).match(/[\p{L}\p{N}]{2,}/gu) || []);
// Cross-script aliases are retrieval vocabulary only, NOT chatbot answer rules.
// The LLM remains responsible for meaning, conversation and choosing actions.
const retrievalAliases = [
  [/(?:قرقيعان|قرقاعون|قرقيان|گرگيعان)/u, ['gergean', 'gerga', 'girgian', 'treat', 'ramadan']],
  [/(?:ورد|زهور|ورود|بوكيه|بوكي)/u, ['flowers', 'flower', 'bouquet', 'roses', 'rose', 'floral']],
  [/(?:هديه|هدايا)/u, ['gift', 'gifting', 'present']],
  [/(?:امي|امك|والدتي|ماما)/u, ['mother', 'mom', 'mothers']],
  [/(?:تخرج)/u, ['graduation', 'graduate']],
  [/(?:عيد ميلاد)/u, ['birthday']]
];
function expandedTokens(text) {
  const query = words(text);
  const normalized = normalize(text);
  for (const [pattern, additions] of retrievalAliases) {
    if (pattern.test(normalized)) for (const term of additions) query.add(term);
  }
  return query;
}
export function requestCatalogContext(catalog, history = [], memory = {}, options = {}) {
  const limit = Math.min(18, Math.max(3, Number(options.maxIndex || MAX_INDEX)));
  const products = Array.isArray(catalog?.products) ? catalog.products : [];
  const pinned = new Set([memory.selected_product, ...safeArray(memory.recommendations, 6),
    ...safeArray(options.lastSuggestedHandles, 6), ...safeArray(options.cartHandles, 10)].filter(Boolean));
  const recentUsers = history.filter(m => m.role === 'user').slice(-5);
  const latestTokens = expandedTokens(recentUsers.at(-1)?.content || '');
  const earlierTokens = expandedTokens([recentUsers.slice(0, -1).map(m => m.content).join(' '),
    memory.occasion, memory.recipient, memory.preferences, ...safeArray(memory.preferred_colors, 8)].join(' '));
  const budget = Number.isFinite(memory.budget) ? memory.budget : null;
  const ranked = products.map((p, idx) => {
    const all = words([p.title, p.handle.replaceAll('-', ' '), p.description, p.product_type,
      ...safeArray(p.tags, 12)].join(' '));
    let score = 0;
    for (const token of latestTokens) if (all.has(token)) score += 12;
    for (const token of earlierTokens) if (all.has(token)) score += 2;
    if (pinned.has(p.handle)) score += 60;
    if (budget !== null) {
      const price = firstMoney(p.price);
      if (Number.isFinite(price) && price <= budget) score += 3;
    }
    if (!p.available) score -= 100;
    return { product: p, idx, score };
  }).sort((a, b) => b.score - a.score || a.idx - b.idx);
  // Retrieval only: the LLM always decides meaning and reply, not this ranking.
  // When no product matches the current conversation, provide only a tiny real
  // store index without bulky descriptions/variants. This saves quota on hi.
  const relevant = ranked.some(row => row.score > 0);
  const selected = ranked.slice(0, Math.max(relevant ? limit : 3, pinned.size));
  const available = selected.map(({ product: p }) => p);
  const index = available.map(p => [p.handle, p.title, p.price || '?', p.available ? 1 : 0]);
  const details = (relevant ? available.slice(0, MAX_DETAILS) : []).map(p => [p.handle,
    String(p.description || '').slice(0, 110), safeArray(p.tags, 3),
    safeArray(p.variants, 4).map(v => [v.id, v.title, v.price, v.available ? 1 : 0,
      safeArray(v.options, 2).map(o => [o.name, o.value])])]);
  const payload = { currency: 'KWD', products_in_store: products.length, shown_in_prompt: available.length,
    catalog_complete: Boolean(catalog?.complete),
    index_columns: ['handle', 'title', 'price', 'available'], index,
    detail_columns: ['handle', 'description', 'tags', 'variants'], details,
    variant_columns: ['shopify_gid', 'title', 'price', 'available', 'options'],
    collections: safeArray(catalog?.collections, 12).map(c => [c.handle, c.title]),
    guidance: 'PARTIAL real Shopify list. Recommend only listed handles. Server checks variants and cart availability.' };
  return { text: JSON.stringify(payload), indexed: available.length, detailed: details.length, total: products.length };
}
