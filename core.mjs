import { PHILIA_FORMS, PHILIA_SITE_MAP, sanitizeFormFields } from './agent-site.mjs';
export const SITE_PATHS = PHILIA_SITE_MAP.routes;

export function boundedHistory(messages = [], maxMessages = 40, maxChars = 24000) {
  const result = [];
  let remaining = maxChars;
  for (const message of (Array.isArray(messages) ? messages : []).slice(-maxMessages).reverse()) {
    if (!['user', 'assistant'].includes(message?.role)) continue;
    const products = Array.isArray(message.products)
      ? message.products.slice(0, 6).map(p => ({ handle: String(p.handle || ''), title: String(p.title || '') })) : [];
    const annotation = products.length ? '\n[Displayed product cards, in order: ' + JSON.stringify(products) + ']' : '';
    const content = String(message.content || '').slice(0, Math.min(3500, Math.max(0, remaining - annotation.length)));
    if (!content && !annotation) continue;
    if (annotation.length > remaining) break;
    result.unshift({ role: message.role, content: content + annotation });
    remaining -= content.length + annotation.length;
    if (remaining <= 0) break;
  }
  return result;
}

export class TTLCache {
  constructor(load, ttlMs, staleMs = ttlMs * 6) {
    this.load = load;
    this.ttlMs = ttlMs;
    this.staleMs = staleMs;
    this.value = null;
    this.at = 0;
    this.pending = null;
    this.lastFailure = 0;
  }
  refresh() {
    if (this.pending) return this.pending;
    if (this.lastFailure && Date.now() - this.lastFailure < 10000) {
      return Promise.reject(new Error('CATALOG_TEMPORARILY_UNAVAILABLE'));
    }
    this.pending = Promise.resolve().then(this.load).then(value => {
      this.value = value;
      this.at = Date.now();
      this.lastFailure = 0;
      return value;
    }).catch(error => {
      this.lastFailure = Date.now();
      throw error;
    }).finally(() => { this.pending = null; });
    return this.pending;
  }
  async get() {
    const age = Date.now() - this.at;
    if (this.value && age < this.ttlMs) return { value: this.value, status: 'hit', ageMs: age };
    if (this.value && age < this.staleMs) {
      this.refresh().catch(() => {});
      return { value: this.value, status: 'stale', ageMs: age };
    }
    try { return { value: await this.refresh(), status: 'miss', ageMs: 0 }; }
    catch { return { value: { products: [], collections: [], complete: false }, status: 'unavailable', ageMs: null }; }
  }
}

function field(raw, wanted) {
  let depth = 0;
  for (let i = 0; i < raw.length; i++) {
    const c = raw[i];
    if (c === '{' || c === '[') { depth++; continue; }
    if (c === '}' || c === ']') { depth--; continue; }
    if (c !== '"') continue;
    const start = i++;
    let escaped = false;
    for (; i < raw.length; i++) {
      if (escaped) { escaped = false; continue; }
      if (raw[i] === '\\') { escaped = true; continue; }
      if (raw[i] === '"') break;
    }
    if (i >= raw.length) return null;
    let key;
    try { key = JSON.parse(raw.slice(start, i + 1)); } catch { continue; }
    if (depth !== 1 || key !== wanted) continue;
    let j = i + 1;
    while (/\s/.test(raw[j] || '') && j < raw.length) j++;
    if (raw[j] !== ':') continue;
    j++;
    while (/\s/.test(raw[j] || '') && j < raw.length) j++;
    const valueStart = j;
    let level = 0, inString = false, escape = false;
    for (; j < raw.length; j++) {
      const x = raw[j];
      if (inString) {
        if (escape) escape = false;
        else if (x === '\\') escape = true;
        else if (x === '"') {
          inString = false;
          if (level === 0) return { valueStart, end: j + 1, complete: true };
        }
      } else if (x === '"') inString = true;
      else if (x === '[' || x === '{') level++;
      else if (x === ']' || x === '}') {
        if (level === 0) return { valueStart, end: j, complete: true };
        level--;
        if (level === 0) return { valueStart, end: j + 1, complete: true };
      } else if (x === ',' && level === 0) return { valueStart, end: j, complete: true };
    }
    return { valueStart, end: raw.length, complete: false };
  }
  return null;
}

function decodePartialString(value, complete) {
  let fragment = value.slice(1, complete ? -1 : undefined);
  if (!complete) {
    let backslashes = 0;
    for (let i = fragment.length - 1; i >= 0 && fragment[i] === '\\'; i--) backslashes++;
    if (backslashes % 2) fragment = fragment.slice(0, -1);
    const match = fragment.match(/(?<!\\)(?:\\\\)*\\u[0-9a-f]{0,3}$/i);
    if (match) fragment = fragment.slice(0, fragment.length - match[0].length);
  }
  let decoded;
  try { decoded = JSON.parse('"' + fragment + '"'); } catch { return null; }
  if (!complete && /[\uD800-\uDBFF]$/.test(decoded)) decoded = decoded.slice(0, -1);
  return decoded;
}

export class ReplyStream {
  constructor(onDelta) { this.raw = ''; this.emitted = ''; this.onDelta = onDelta; this.actions = null; }
  push(delta) {
    this.raw += delta;
    if (this.raw.length > 100000) throw new Error('OUTPUT_TOO_LARGE');
    if (this.actions === null) {
      const a = field(this.raw, 'actions');
      if (a?.complete) {
        try { this.actions = JSON.parse(this.raw.slice(a.valueStart, a.end)); } catch {}
      }
    }
    if (!Array.isArray(this.actions) || this.actions.some(a => a?.auto === true)) return;
    const r = field(this.raw, 'reply');
    if (!r || this.raw[r.valueStart] !== '"') return;
    const text = decodePartialString(this.raw.slice(r.valueStart, r.end), r.complete);
    if (text === null || !text.startsWith(this.emitted)) return;
    const next = text.slice(this.emitted.length);
    this.emitted = text;
    if (next) this.onDelta(next);
  }
  finish() {
    let envelope;
    try { envelope = JSON.parse(this.raw); } catch { throw new Error('INVALID_AI_ENVELOPE'); }
    if (!envelope || typeof envelope.reply !== 'string' || !Array.isArray(envelope.actions)) {
      throw new Error('INVALID_AI_ENVELOPE');
    }
    if (!envelope.actions.some(a => a?.auto === true)) {
      const rest = envelope.reply.slice(this.emitted.length);
      if (rest) this.onDelta(rest);
    }
    return envelope;
  }
}

export function cleanMemory(raw = {}, products = []) {
  const handles = new Set(products.map(p => p.handle));
  const output = {};
  for (const key of ['user_name', 'occasion', 'recipient', 'delivery_intent', 'preferences', 'company', 'customer_type', 'venue', 'request_details', 'contact_email', 'contact_phone', 'required_date', 'event_date', 'delivery_date', 'message_card', 'branding', 'size', 'service', 'category']) {
    if (raw[key] === null) output[key] = null;
    else if (typeof raw[key] === 'string') output[key] = raw[key].slice(0, 400);
  }
  if (raw.budget === null) output.budget = null;
  else if (Number.isFinite(raw.budget) && raw.budget >= 0 && raw.budget < 1000000) output.budget = raw.budget;
  if (raw.order_quantity === null) output.order_quantity = null;
  else if (Number.isInteger(raw.order_quantity) && raw.order_quantity >= 1 && raw.order_quantity <= 100000) output.order_quantity = raw.order_quantity;
  if (raw.guest_count === null) output.guest_count = null;
  else if (Number.isInteger(raw.guest_count) && raw.guest_count >= 1 && raw.guest_count <= 100000) output.guest_count = raw.guest_count;
  if (raw.quantity === null) output.quantity = null;
  else if (Number.isInteger(raw.quantity) && raw.quantity >= 1 && raw.quantity <= 99) output.quantity = raw.quantity;
  if (raw.notes === null) output.notes = null;
  else if (typeof raw.notes === 'string') output.notes = raw.notes.slice(0, 1600);
  if (raw.preferred_colors === null) output.preferred_colors = null;
  else if (Array.isArray(raw.preferred_colors)) output.preferred_colors = raw.preferred_colors.filter(x => typeof x === 'string').slice(0, 8).map(x => x.slice(0, 60));
  if (raw.selected_product === null) output.selected_product = null;
  else if (handles.has(raw.selected_product)) output.selected_product = raw.selected_product;
  if (raw.selected_variant === null) output.selected_variant = null;
  else if (typeof raw.selected_variant === 'string' && products.some(p => p.variants.some(v => v.id === raw.selected_variant))) output.selected_variant = raw.selected_variant;
  if (raw.recommendations === null) output.recommendations = null;
  else if (Array.isArray(raw.recommendations)) output.recommendations = raw.recommendations.filter(h => handles.has(h)).slice(0, 6);
  if (raw.response_language === null) output.response_language = null;
  else if (['ar', 'en'].includes(raw.response_language)) output.response_language = raw.response_language;
  if (raw.response_dialect === null) output.response_dialect = null;
  else if (typeof raw.response_dialect === 'string') output.response_dialect = raw.response_dialect.slice(0, 80);
  return output;
}

export function validateEnvelope(envelope, catalog, context = {}) {
  const map = new Map(catalog.products.map(p => [p.handle, p]));
  const allowedPaths = new Set([...SITE_PATHS,
    ...catalog.collections.map(c => '/collections/' + c.handle)]);
  const recommended = [];
  for (const candidate of Array.isArray(envelope.products) ? envelope.products.slice(0, 6) : []) {
    const handle = typeof candidate === 'string' ? candidate : candidate?.handle;
    const product = map.get(handle);
    if (!product?.available || recommended.some(p => p.handle === handle)) continue;
    recommended.push({ ...product, reason: String(candidate?.reason || '').slice(0, 240), url: '/products/' + handle });
  }
  const actions = [];
  for (const source of envelope.actions.slice(0, 5)) {
    if (!source || typeof source !== 'object') continue;
    const action = { action: source.action, auto: source.auto === true, label: String(source.label || '').slice(0, 160) };
    if (action.action === 'navigate') {
      const url = String(source.url || '');
      if (allowedPaths.has(url) || [...map.keys()].some(h => url === '/products/' + h)) actions.push({ ...action, url });
    } else if (action.action === 'open_cart') actions.push(action);
    else if (action.action === 'search') {
      const query = String(source.query || '').trim().slice(0, 100);
      if (query) actions.push({ ...action, query });
    } else if (action.action === 'open_whatsapp' && context.whatsapp_available === true) actions.push(action);
    else if (action.action === 'open_account' && context.account_available === true) actions.push(action);
    else if (action.action === 'form_patch') {
      const form = String(source.form || '');
      const fields = sanitizeFormFields(form, source.fields);
      if (PHILIA_FORMS[form] && Object.keys(fields).length) {
        actions.push({ ...action, form, path: PHILIA_FORMS[form].path, fields });
      }
    }
    else if (action.action === 'scroll') {
      if (/^#[a-zA-Z][\w-]{0,100}$/.test(source.selector || '') && (context.section_ids || []).includes(source.selector)) actions.push({ ...action, selector: source.selector });
    } else if (action.action === 'add_to_cart') {
      const product = map.get(source.handle);
      if (!product?.available) continue;
      let variant = product.variants.find(v => v.id === String(source.variant_id || '') && v.available);
      const available = product.variants.filter(v => v.available);
      if (!variant && available.length === 1) variant = available[0];
      const quantity = Number(source.quantity ?? 1);
      if (!Number.isInteger(quantity) || quantity < 1 || quantity > 99) continue;
      actions.push({ ...action, handle: product.handle, title: product.title, variant_id: variant?.id || null, quantity });
    } else if (['remove_from_cart', 'update_cart'].includes(action.action)) {
      const line = (context.cart?.items || []).find(i => i.key === source.line_key);
      const quantity = action.action === 'remove_from_cart' ? 0 : Number(source.quantity);
      if (line && Number.isInteger(quantity) && quantity >= 0 && quantity <= 99) actions.push({ ...action, line_key: line.key, quantity });
    }
  }
  const memory = cleanMemory(envelope.memory || {}, catalog.products);
  // Non-auto actions are context-specific button suggestions, not extra LLM calls.
  const seen = new Set();
  const distinctActions = actions.filter(a => {
    const key = JSON.stringify([a.action,a.url,a.handle,a.form,a.query,a.selector]);
    if(seen.has(key)) return false;
    seen.add(key); return true;
  });
  if (recommended.length) memory.recommendations = recommended.map(p => p.handle);
  return { reply: envelope.reply, products: recommended, actions: distinctActions.slice(0, 4), memory };
}
