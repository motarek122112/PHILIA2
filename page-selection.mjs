// Page summaries are factual knowledge, not assistant replies or intent routes.
// IMPORTANT: old backend transmitted EVERY cached page body on EVERY request.
const normalize = value => String(value || '').normalize('NFKC').toLocaleLowerCase().replace(/[أإآٱ]/g, 'ا').replace(/ى/g,'ي');
const tokens = value => new Set(normalize(value).match(/[\p{L}\p{N}]{2,}/gu) || []);
export function requestPageContext(pages = [], history = [], options = {}) {
  const list = Array.isArray(pages) ? pages : [];
  const lastUser = history.filter(x => x.role === 'user').slice(-2).map(x => x.content).join(' ');
  const query = tokens(lastUser);
  const aliases = [
    [/(?:فيليا|عنكم|عنكم|مين انتو|من انتم)/u, ['about', 'philia']],
    [/(?:توصيل|شحن|تسليم)/u, ['delivery', 'shipping']],
    [/(?:عرس|زواج|مناسبه|حفله)/u, ['wedding', 'events']],
    [/(?:تواصل|اتصل|رقمكم)/u, ['contact']],
    [/(?:هديه|اهداء)/u, ['gifting', 'gift']]
  ];
  for (const [pattern, alias] of aliases) if (pattern.test(normalize(lastUser))) for (const term of alias) query.add(term);
  const scored = list.map((p, idx) => {
    let score = 0;
    for (const token of tokens([p.handle, p.title, p.summary].join(' '))) if (query.has(token)) score += 3;
    // A short official brand summary is useful on informational turns.
    if (/\babout\b/i.test(p.handle)) score += 1;
    return { p, idx, score };
  }).sort((a,b) => b.score - a.score || a.idx - b.idx);
  const count = Math.min(Math.max(1, Number(options.maxDetails || 1)), 3);
  const detail = scored.slice(0, count).filter(x => x.score > 0).map(({p}) =>
    [p.handle, String(p.summary || '').slice(0, 220)]);
  const index = list.slice(0, 12).map(p => [p.handle, p.title]);
  return { text: JSON.stringify({pages_in_store:list.length, index_columns:['handle','title'],index,
    excerpts_columns:['handle','summary'],excerpts:detail,
    note:'These are excerpts, not complete policies. Do not invent guarantees, delivery times or services.'}),
    indexed:index.length, detailed:detail.length, total:list.length };
}
