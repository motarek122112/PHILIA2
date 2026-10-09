// Verified from Philia V114 Liquid templates. This is a capability allowlist,
// not an intent router or a source of invented Shopify catalog data.
export const PHILIA_FORMS = Object.freeze({
  contact: { path:'/pages/contact', fields:{name:'contact[name]',email:'contact[email]',body:'contact[body]'} },
  bespoke: { path:'/pages/bespoke-orders', fields:{occasion:'contact[Occasion]',budget:'contact[Budget]',required_date:'contact[Required date]',colours:'contact[Colours]',body:'contact[body]'} },
  events: { path:'/pages/events-weddings', fields:{event_date:'contact[Event date]',guest_count:'contact[Guest count]',venue:'contact[Venue]',budget:'contact[Budget]',body:'contact[body]'} },
  corporate: { path:'/pages/corporate-events', fields:{company:'contact[Company]',quantity:'contact[Quantity]',body:'contact[body]'} }
});
export const PHILIA_SITE_MAP = Object.freeze({
  routes: ['/', '/collections','/collections/all','/cart','/pages/about-philia','/pages/delivery-care','/pages/contact','/pages/gifting','/pages/bespoke-orders','/pages/events-weddings','/pages/corporate-events'],
  forms: PHILIA_FORMS,
  sections: {events: '#event-brief'},
  actions: ['navigate','scroll','open_cart','add_to_cart','update_cart','remove_from_cart','form_patch','search','open_whatsapp','open_account']
});
export function sanitizeFormFields(form, raw) {
  const definition = PHILIA_FORMS[form];
  if (!definition || !raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  const fields = {};
  for (const field of Object.keys(definition.fields)) {
    const value = raw[field];
    if (value === undefined || value === null) continue;
    if (typeof value !== 'string' && typeof value !== 'number') continue;
    const clean = String(value).trim().slice(0, field === 'body' ? 1800 : 180);
    if (!clean) continue;
    if ((field === 'event_date' || field === 'required_date') && !/^\d{4}-\d{2}-\d{2}$/.test(clean)) continue;
    if (field === 'guest_count' && (!/^\d+$/.test(clean) || Number(clean) < 1 || Number(clean) > 100000)) continue;
    if (field === 'email' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clean)) continue;
    fields[field] = clean;
  }
  return fields;
}
