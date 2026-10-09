// Store each field name once rather than repeating it for every product/variant.
// The full Shopify records remain unchanged for cards and action validation.
const prompts = new WeakMap();

export function compactCatalog(catalog) {
  return {
    complete: catalog.complete,
    collections: catalog.collections,
    product_columns: ['handle', 'title', 'description', 'tags', 'product_type', 'available', 'price', 'variants'],
    variant_columns: ['id', 'title', 'available', 'price', 'options'],
    option_columns: ['name', 'value'],
    products: catalog.products.map(p => [p.handle, p.title, p.description || '', p.tags || [],
      p.product_type || '', p.available, p.price,
      p.variants.map(v => [v.id, v.title, v.available, v.price,
        (v.options || []).map(o => [o.name, o.value])])])
  };
}

export function catalogPrompt(catalog) {
  if (!prompts.has(catalog)) prompts.set(catalog, JSON.stringify(compactCatalog(catalog)));
  return prompts.get(catalog);
}
