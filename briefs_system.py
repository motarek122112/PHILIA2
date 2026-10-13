import os, re, hmac, hashlib, secrets, smtplib, json, html, time, threading
from datetime import datetime, timezone, date
from email.message import EmailMessage
from typing import Optional, Dict, Any, List

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

router = APIRouter()

# Shopify-native request storage. No external database is used.
SHOPIFY_SHOP = os.getenv('SHOPIFY_SHOP', '').strip().replace('https://', '').replace('.myshopify.com', '').strip('/')
SHOPIFY_CLIENT_ID = os.getenv('SHOPIFY_CLIENT_ID', '').strip()
SHOPIFY_CLIENT_SECRET = os.getenv('SHOPIFY_CLIENT_SECRET', '').strip()
# Backwards-compatible names from V33, if they still exist in Render.
SHOPIFY_API_SECRET = os.getenv('SHOPIFY_API_SECRET', '').strip() or SHOPIFY_CLIENT_SECRET
SHOPIFY_ADMIN_TOKEN = os.getenv('SHOPIFY_ADMIN_TOKEN', '').strip()
SHOPIFY_STORE_DOMAIN = os.getenv('SHOPIFY_STORE_DOMAIN', '').strip().replace('https://', '').strip('/')
SHOPIFY_ADMIN_API_VERSION = os.getenv('SHOPIFY_ADMIN_API_VERSION', '2026-10').strip() or '2026-10'

PHILIA_NOTIFICATION_EMAIL = os.getenv('PHILIA_NOTIFICATION_EMAIL', '').strip()
SMTP_HOST = os.getenv('SMTP_HOST', '').strip()
SMTP_PORT = int(os.getenv('SMTP_PORT', '587') or 587)
SMTP_USER = os.getenv('SMTP_USER', '').strip()
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '').strip()
SMTP_FROM = os.getenv('SMTP_FROM_EMAIL', '').strip() or SMTP_USER or PHILIA_NOTIFICATION_EMAIL

ALLOW_UNSIGNED_PROXY = os.getenv('ALLOW_UNSIGNED_PROXY', 'false').lower() in {'1', 'true', 'yes'}
METAOBJECT_TYPE = 'philia_request'
VALID_TYPES = {'event', 'bespoke', 'corporate'}
VALID_STATUSES = {'submitted', 'in_review', 'quoted', 'confirmed', 'completed', 'cancelled'}

_token_lock = threading.Lock()
_token_cache: Dict[str, Any] = {'token': None, 'expires_at': 0.0}
_definition_lock = threading.Lock()
_definition_ready = False
_create_lock = threading.Lock()
_recent_creates: Dict[str, List[float]] = {}


class BriefCreate(BaseModel):
    request_type: str
    name: str
    email: str
    phone: Optional[str] = None
    event_date: Optional[str] = None
    guest_count: Optional[int] = None
    venue: Optional[str] = None
    budget: Optional[str] = None
    occasion: Optional[str] = None
    colours: Optional[str] = None
    company: Optional[str] = None
    quantity_scope: Optional[str] = None
    details: str
    locale: Optional[str] = 'en'


class BriefUpdate(BaseModel):
    phone: Optional[str] = None
    event_date: Optional[str] = None
    guest_count: Optional[int] = None
    venue: Optional[str] = None
    budget: Optional[str] = None
    occasion: Optional[str] = None
    colours: Optional[str] = None
    company: Optional[str] = None
    quantity_scope: Optional[str] = None
    details: Optional[str] = None


class CancelPayload(BaseModel):
    reason: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _clean(v, n=1200):
    if v is None:
        return ''
    return str(v).strip()[:n]


def _shop_domain() -> str:
    # V34.1: explicit SHOPIFY_SHOP wins over legacy SHOPIFY_STORE_DOMAIN on Render.
    if SHOPIFY_SHOP:
        return f'{SHOPIFY_SHOP}.myshopify.com'
    if SHOPIFY_STORE_DOMAIN:
        return SHOPIFY_STORE_DOMAIN
    return ''


def _require_shopify_config():
    if not _shop_domain():
        raise HTTPException(503, 'SHOPIFY_SHOP is not configured on the Philia backend.')
    if not SHOPIFY_ADMIN_TOKEN and not (SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET):
        raise HTTPException(503, 'Shopify app credentials are not configured on the Philia backend.')


def _access_token(force=False) -> str:
    _require_shopify_config()
    if SHOPIFY_ADMIN_TOKEN:
        return SHOPIFY_ADMIN_TOKEN
    now = time.monotonic()
    if not force and _token_cache.get('token') and float(_token_cache.get('expires_at') or 0) > now + 60:
        return str(_token_cache['token'])
    with _token_lock:
        now = time.monotonic()
        if not force and _token_cache.get('token') and float(_token_cache.get('expires_at') or 0) > now + 60:
            return str(_token_cache['token'])
        url = f'https://{_shop_domain()}/admin/oauth/access_token'
        try:
            with httpx.Client(timeout=18) as client:
                r = client.post(url, data={
                    'grant_type': 'client_credentials',
                    'client_id': SHOPIFY_CLIENT_ID,
                    'client_secret': SHOPIFY_CLIENT_SECRET,
                })
            if r.status_code >= 400:
                raise HTTPException(502, f'Shopify authentication failed ({r.status_code}).')
            data = r.json()
            token = data.get('access_token')
            if not token:
                raise HTTPException(502, 'Shopify did not return an access token.')
            expires = int(data.get('expires_in') or 86399)
            _token_cache['token'] = token
            _token_cache['expires_at'] = time.monotonic() + max(300, expires - 300)
            return token
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(502, f'Could not authenticate with Shopify: {str(e)[:180]}')


def _graphql(query: str, variables: Optional[Dict[str, Any]] = None, retry=True) -> Dict[str, Any]:
    token = _access_token()
    url = f'https://{_shop_domain()}/admin/api/{SHOPIFY_ADMIN_API_VERSION}/graphql.json'
    try:
        with httpx.Client(timeout=22) as client:
            r = client.post(url, headers={
                'X-Shopify-Access-Token': token,
                'Content-Type': 'application/json',
            }, json={'query': query, 'variables': variables or {}})
        if r.status_code == 401 and retry and not SHOPIFY_ADMIN_TOKEN:
            _access_token(force=True)
            return _graphql(query, variables, retry=False)
        if r.status_code >= 400:
            raise HTTPException(502, f'Shopify Admin API returned HTTP {r.status_code}.')
        payload = r.json()
        if payload.get('errors'):
            msg = '; '.join(str(x.get('message') or x) for x in payload['errors'][:4])
            raise HTTPException(502, f'Shopify GraphQL error: {msg[:500]}')
        return payload.get('data') or {}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f'Shopify request failed: {str(e)[:220]}')


def _user_errors(block: Dict[str, Any], operation: str):
    errors = (block or {}).get('userErrors') or []
    if errors:
        msg = '; '.join(str(e.get('message') or e) for e in errors[:5])
        raise HTTPException(422, f'{operation}: {msg[:600]}')


def _proxy_signature_ok(request: Request) -> bool:
    if ALLOW_UNSIGNED_PROXY:
        return True
    secret = SHOPIFY_CLIENT_SECRET or SHOPIFY_API_SECRET
    if not secret:
        return False
    supplied = request.query_params.get('signature', '')
    if not supplied:
        return False
    # Reject stale proxy signatures to reduce request replay. Shopify adds the timestamp.
    try:
        sent_at = int(request.query_params.get('timestamp',''))
        if abs(time.time() - sent_at) > 300:
            return False
    except (ValueError, TypeError):
        return False
    grouped: Dict[str, List[str]] = {}
    for k, v in request.query_params.multi_items():
        if k == 'signature':
            continue
        grouped.setdefault(k, []).append(v)
    canonical = ''.join(sorted(f"{k}={','.join(values)}" for k, values in grouped.items()))
    digest = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, supplied)


def _proxy_identity(request: Request):
    if not _proxy_signature_ok(request):
        raise HTTPException(401, 'Invalid Shopify app proxy signature.')
    incoming_shop = request.query_params.get('shop', '').strip().lower().rstrip('.')
    expected = _shop_domain().lower().rstrip('.')
    # Shopify keeps an original myshopifyDomain and may also have a branded
    # primary .myshopify.com domain. Both can refer to this same shop.
    # Accept only explicitly configured identities, after verifying the signed
    # app-proxy request above. Never disable signature or customer-ID checks.
    aliases = {expected} if expected else set()
    if SHOPIFY_STORE_DOMAIN:
        aliases.add(SHOPIFY_STORE_DOMAIN.lower().rstrip('.'))
    if SHOPIFY_SHOP:
        aliases.add(f'{SHOPIFY_SHOP.lower()}.myshopify.com')
    aliases.update(
        item.strip().lower().rstrip('.')
        for item in os.getenv('SHOPIFY_PROXY_ALLOWED_SHOPS', '').split(',')
        if item.strip()
    )
    if not incoming_shop or (aliases and incoming_shop not in aliases):
        # Only public domain names are logged. Never log the signed query,
        # Shopify app secret, tokens, or customer details.
        print(f'[PHILIA PROXY] signed shop mismatch: incoming={incoming_shop!r}, '
              f'allowed={sorted(aliases)!r}', flush=True)
        raise HTTPException(403, 'Wrong Shopify store. Check Render Logs for PHILIA PROXY signed shop mismatch.')
    cid = request.query_params.get('logged_in_customer_id', '').strip() or None
    return cid, incoming_shop


def _rate_limit_create(request: Request):
    """Best-effort per-worker abuse control. Not a substitute for edge WAF.
    Limit: five created requests per IP per two minutes.
    """
    forwarded = request.headers.get('x-forwarded-for', '')
    addr = (forwarded.split(',')[0].strip() if forwarded else '') or (request.client.host if request.client else 'unknown')
    key = hashlib.sha256(addr.encode()).hexdigest()[:24]
    now = time.monotonic()
    with _create_lock:
        for k in list(_recent_creates):
            _recent_creates[k] = [t for t in _recent_creates[k] if now - t < 120]
            if not _recent_creates[k]: del _recent_creates[k]
        attempts = _recent_creates.setdefault(key, [])
        if len(attempts) >= 5:
            raise HTTPException(429, 'Too many requests. Please wait two minutes before trying again.')
        attempts.append(now)


def _validated_date(value: Optional[str]) -> str:
    if not value: return ''
    try: return date.fromisoformat(str(value)).isoformat()
    except (ValueError, TypeError): raise HTTPException(422, 'Invalid event date.')


def _field_def(name: str, key: str, multi=False, required=False):
    return {
        'name': name,
        'key': key,
        'type': 'multi_line_text_field' if multi else 'single_line_text_field',
        'required': required,
    }


FIELD_DEFINITIONS = [
    _field_def('Reference', 'reference', required=True),
    _field_def('Request type', 'request_type', required=True),
    _field_def('Status', 'status', required=True),
    _field_def('Customer ID', 'customer_id'),
    _field_def('Customer name', 'customer_name', required=True),
    _field_def('Customer email', 'customer_email', required=True),
    _field_def('Phone', 'phone'),
    _field_def('Event / required date', 'event_date'),
    _field_def('Guest count', 'guest_count'),
    _field_def('Venue', 'venue'),
    _field_def('Budget', 'budget'),
    _field_def('Occasion', 'occasion'),
    _field_def('Preferred colours', 'colours'),
    _field_def('Company', 'company'),
    _field_def('Quantity / scope', 'quantity_scope'),
    _field_def('Customer details', 'details', multi=True, required=True),
    _field_def('Quote amount KWD', 'quote_amount_kwd'),
    _field_def('Internal note', 'internal_note', multi=True),
    _field_def('Cancellation reason', 'cancellation_reason', multi=True),
    _field_def('Timeline / audit JSON', 'audit_history', multi=True),
    _field_def('Draft order ID', 'draft_order_id'),
    _field_def('Draft order name', 'draft_order_name'),
    _field_def('Locale', 'locale'),
    _field_def('Created at', 'created_at'),
    _field_def('Updated at', 'updated_at'),
    _field_def('Cancelled at', 'cancelled_at'),
]


def _ensure_definition() -> bool:
    global _definition_ready
    if _definition_ready:
        return True
    with _definition_lock:
        if _definition_ready:
            return True
        _require_shopify_config()
        q = '''query PhiliaDefinitions { metaobjectDefinitions(first: 100) { nodes { id name type fieldDefinitions { key } } } }'''
        data = _graphql(q)
        nodes = ((data.get('metaobjectDefinitions') or {}).get('nodes') or [])
        existing = next((x for x in nodes if x.get('type') == METAOBJECT_TYPE), None)
        if existing:
            # Add any fields introduced by a later Philia version without deleting merchant data.
            have = {f.get('key') for f in existing.get('fieldDefinitions') or []}
            missing = [f for f in FIELD_DEFINITIONS if f['key'] not in have]
            if missing:
                mutation = '''mutation UpdatePhiliaDefinition($id: ID!, $definition: MetaobjectDefinitionUpdateInput!) {
                  metaobjectDefinitionUpdate(id:$id, definition:$definition) {
                    metaobjectDefinition { id type }
                    userErrors { field message code }
                  }
                }'''
                ops = [{'create': f} for f in missing]
                out = _graphql(mutation, {'id': existing['id'], 'definition': {'fieldDefinitions': ops}})
                _user_errors(out.get('metaobjectDefinitionUpdate') or {}, 'Could not update Philia Requests definition')
            _definition_ready = True
            return True
        mutation = '''mutation CreatePhiliaDefinition($definition: MetaobjectDefinitionCreateInput!) {
          metaobjectDefinitionCreate(definition:$definition) {
            metaobjectDefinition { id name type displayNameKey }
            userErrors { field message code }
          }
        }'''
        definition = {
            'name': 'Philia Requests',
            'type': METAOBJECT_TYPE,
            'description': 'Event, wedding, bespoke and corporate requests submitted through the Philia storefront.',
            'displayNameKey': 'reference',
            'fieldDefinitions': FIELD_DEFINITIONS,
        }
        out = _graphql(mutation, {'definition': definition})
        block = out.get('metaobjectDefinitionCreate') or {}
        _user_errors(block, 'Could not create Philia Requests definition')
        _definition_ready = True
        return True


def init_brief_db():
    """Backwards-compatible startup hook name from V33. Now initializes Shopify Metaobjects, not a DB."""
    try:
        _ensure_definition()
        print('[PHILIA REQUESTS] Shopify-native Metaobject storage ready', flush=True)
    except Exception as e:
        # Do not take the AI service down if Shopify is temporarily unavailable at startup.
        print('[PHILIA REQUESTS] startup initialization deferred:', repr(e), flush=True)


def _reference(kind: str) -> str:
    prefix = {'event': 'EV', 'bespoke': 'BQ', 'corporate': 'CO'}.get(kind, 'RQ')
    return f"PH-{prefix}-{datetime.now().strftime('%y%m%d')}-{secrets.token_hex(2).upper()}"


def _handle(reference: str) -> str:
    return re.sub(r'[^a-z0-9-]+', '-', reference.lower()).strip('-')[:80]


def _audit_event(action: str, actor: str, payload: Optional[Dict[str, Any]] = None):
    return {'at': _now_iso(), 'action': action, 'actor': actor, 'payload': payload or {}}


def _decode_fields(node: Dict[str, Any]) -> Dict[str, str]:
    return {f.get('key'): (f.get('value') or '') for f in (node.get('fields') or []) if f.get('key')}


def _serialize_node(node: Dict[str, Any], admin=False) -> Dict[str, Any]:
    f = _decode_fields(node)
    def int_or_none(v):
        try: return int(v) if str(v).strip() else None
        except Exception: return None
    def float_or_none(v):
        try: return float(v) if str(v).strip() else None
        except Exception: return None
    data = {
        'reference': f.get('reference') or (node.get('handle') or '').upper(),
        'request_type': f.get('request_type') or '',
        'status': f.get('status') or 'submitted',
        'name': f.get('customer_name') or '',
        'email': f.get('customer_email') or '',
        'phone': f.get('phone') or None,
        'event_date': f.get('event_date') or None,
        'guest_count': int_or_none(f.get('guest_count')),
        'venue': f.get('venue') or None,
        'budget': f.get('budget') or None,
        'occasion': f.get('occasion') or None,
        'colours': f.get('colours') or None,
        'company': f.get('company') or None,
        'quantity_scope': f.get('quantity_scope') or None,
        'details': f.get('details') or '',
        'quote_amount_kwd': float_or_none(f.get('quote_amount_kwd')),
        'created_at': f.get('created_at') or node.get('createdAt'),
        'updated_at': f.get('updated_at') or node.get('updatedAt'),
        'cancelled_at': f.get('cancelled_at') or None,
        'shopify_draft_order_name': f.get('draft_order_name') or None,
    }
    if admin:
        data.update({
            'id': node.get('id'),
            'customer_id': f.get('customer_id') or None,
            'internal_note': f.get('internal_note') or None,
            'cancellation_reason': f.get('cancellation_reason') or None,
            'shopify_draft_order_id': f.get('draft_order_id') or None,
            'audit_history': f.get('audit_history') or '[]',
        })
    return data


def _node_by_reference(reference: str) -> Optional[Dict[str, Any]]:
    _ensure_definition()
    query = '''query PhiliaRequestByHandle($handle: MetaobjectHandleInput!) {
      metaobjectByHandle(handle:$handle) { id handle type createdAt updatedAt fields { key value } }
    }'''
    data = _graphql(query, {'handle': {'type': METAOBJECT_TYPE, 'handle': _handle(reference)}})
    return data.get('metaobjectByHandle')


def _all_nodes(max_pages=12) -> List[Dict[str, Any]]:
    _ensure_definition()
    query = '''query PhiliaRequests($type:String!, $cursor:String) {
      metaobjects(type:$type, first:100, after:$cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { id handle type createdAt updatedAt fields { key value } }
      }
    }'''
    nodes, cursor = [], None
    for _ in range(max_pages):
        data = _graphql(query, {'type': METAOBJECT_TYPE, 'cursor': cursor})
        conn = data.get('metaobjects') or {}
        nodes.extend(conn.get('nodes') or [])
        page = conn.get('pageInfo') or {}
        if not page.get('hasNextPage'):
            break
        cursor = page.get('endCursor')
        if not cursor:
            break
    return nodes


def _fields_payload(values: Dict[str, Any]) -> List[Dict[str, str]]:
    allowed = {x['key'] for x in FIELD_DEFINITIONS}
    out = []
    for key, value in values.items():
        if key not in allowed or value is None:
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        out.append({'key': key, 'value': _clean(value, 18000 if key in {'details','internal_note','cancellation_reason','audit_history'} else 1200)})
    return out


def _create_metaobject(values: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_definition()
    mutation = '''mutation CreatePhiliaRequest($metaobject: MetaobjectCreateInput!) {
      metaobjectCreate(metaobject:$metaobject) {
        metaobject { id handle type createdAt updatedAt fields { key value } }
        userErrors { field message code }
      }
    }'''
    ref = values['reference']
    out = _graphql(mutation, {'metaobject': {
        'type': METAOBJECT_TYPE,
        'handle': _handle(ref),
        'fields': _fields_payload(values),
    }})
    block = out.get('metaobjectCreate') or {}
    _user_errors(block, 'Could not save request in Shopify')
    node = block.get('metaobject')
    if not node:
        raise HTTPException(502, 'Shopify did not return the saved request.')
    return node


def _update_metaobject(node_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    mutation = '''mutation UpdatePhiliaRequest($id:ID!, $metaobject:MetaobjectUpdateInput!) {
      metaobjectUpdate(id:$id, metaobject:$metaobject) {
        metaobject { id handle type createdAt updatedAt fields { key value } }
        userErrors { field message code }
      }
    }'''
    out = _graphql(mutation, {'id': node_id, 'metaobject': {'fields': _fields_payload(patch)}})
    block = out.get('metaobjectUpdate') or {}
    _user_errors(block, 'Could not update request in Shopify')
    node = block.get('metaobject')
    if not node:
        raise HTTPException(502, 'Shopify did not return the updated request.')
    return node


def _draft_attrs(values: Dict[str, Any]) -> List[Dict[str, str]]:
    keys = ['reference','request_type','status','customer_id','event_date','guest_count','venue','budget','occasion','company','quantity_scope']
    return [{'key': k.replace('_',' ').title(), 'value': _clean(values.get(k), 240)} for k in keys if _clean(values.get(k),240)]


def _draft_note(values: Dict[str, Any]) -> str:
    lines = [
        f"Philia request: {values.get('reference','')}",
        f"Status: {values.get('status','submitted')}",
        f"Type: {values.get('request_type','')}",
        f"Customer: {values.get('customer_name','')} <{values.get('customer_email','')}>",
    ]
    for label, key in [('Phone','phone'),('Date','event_date'),('Guests','guest_count'),('Venue','venue'),('Budget','budget'),('Occasion','occasion'),('Company','company'),('Quantity / scope','quantity_scope')]:
        if _clean(values.get(key), 1000):
            lines.append(f"{label}: {_clean(values.get(key),1000)}")
    lines.append('')
    lines.append('Customer brief:')
    lines.append(_clean(values.get('details'), 5000))
    if _clean(values.get('cancellation_reason'), 2000):
        lines.extend(['', f"Cancellation reason: {_clean(values.get('cancellation_reason'),2000)}"])
    return '\n'.join(lines)[:10000]


def _create_draft(values: Dict[str, Any]) -> Dict[str, Any]:
    mutation = '''mutation CreatePhiliaDraft($input:DraftOrderInput!) {
      draftOrderCreate(input:$input) {
        draftOrder { id name }
        userErrors { field message }
      }
    }'''
    kind = {'event':'Event brief','bespoke':'Bespoke quote request','corporate':'Corporate request'}.get(values.get('request_type'),'Philia request')
    input_data = {
        'email': _clean(values.get('customer_email'), 320) or None,
        'phone': _clean(values.get('phone'), 80) or None,
        'note': _draft_note(values),
        'tags': ['philia-request', f"philia-{values.get('request_type','request')}", f"philia-{values.get('status','submitted')}", _clean(values.get('reference'),80)],
        'customAttributes': _draft_attrs(values),
        'lineItems': [{'title': f"{kind} — {_clean(values.get('reference'),80)}", 'quantity': 1, 'originalUnitPrice': '0.00'}],
    }
    input_data = {k:v for k,v in input_data.items() if v not in (None,'')}
    try:
        out = _graphql(mutation, {'input': input_data})
        block = out.get('draftOrderCreate') or {}
        _user_errors(block, 'Could not create Shopify draft order')
        return block.get('draftOrder') or {}
    except Exception as e:
        print('[PHILIA REQUESTS] draft create warning:', repr(e), flush=True)
        return {}


def _update_draft(draft_id: str, values: Dict[str, Any]):
    if not draft_id:
        return
    mutation = '''mutation UpdatePhiliaDraft($id:ID!, $input:DraftOrderInput!) {
      draftOrderUpdate(id:$id, input:$input) { draftOrder { id name } userErrors { field message } }
    }'''
    input_data = {
        'email': _clean(values.get('customer_email'),320) or None,
        'phone': _clean(values.get('phone'),80) or None,
        'note': _draft_note(values),
        'tags': ['philia-request', f"philia-{values.get('request_type','request')}", f"philia-{values.get('status','submitted')}", _clean(values.get('reference'),80)],
        'customAttributes': _draft_attrs(values),
    }
    input_data = {k:v for k,v in input_data.items() if v not in (None,'')}
    try:
        out = _graphql(mutation, {'id': draft_id, 'input': input_data})
        _user_errors(out.get('draftOrderUpdate') or {}, 'Could not update Shopify draft order')
    except Exception as e:
        print('[PHILIA REQUESTS] draft update warning:', repr(e), flush=True)


def _send_mail(to: str, subject: str, body_html: str) -> bool:
    if not (to and SMTP_HOST and SMTP_FROM):
        return False
    try:
        msg = EmailMessage()
        msg['From'] = SMTP_FROM
        msg['To'] = to
        msg['Subject'] = subject
        msg.set_content(re.sub('<[^>]+>', '', body_html))
        msg.add_alternative(body_html, subtype='html')
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            if SMTP_USER:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print('[PHILIA REQUESTS] email warning:', repr(e), flush=True)
        return False


def _notify(kind: str, values: Dict[str, Any]) -> bool:
    if not PHILIA_NOTIFICATION_EMAIL:
        return False
    ref = html.escape(_clean(values.get('reference'),100))
    status = html.escape(_clean(values.get('status'),50))
    customer = html.escape(_clean(values.get('customer_name'),180))
    email = html.escape(_clean(values.get('customer_email'),320))
    details = html.escape(_clean(values.get('details'),5000)).replace('\n','<br>')
    subject_map = {'new':'New Philia request','edit':'Philia request updated','cancel':'Philia request cancelled'}
    subject = f"{subject_map.get(kind,'Philia request')} · {ref}"
    body = f"<h2>{subject}</h2><p><b>Status:</b> {status}<br><b>Customer:</b> {customer} · {email}</p><p>{details}</p>"
    if kind == 'cancel' and values.get('cancellation_reason'):
        body += f"<p><b>Cancellation reason:</b> {html.escape(_clean(values.get('cancellation_reason'),2000))}</p>"
    return _send_mail(PHILIA_NOTIFICATION_EMAIL, subject, body)


def _full_values(node: Dict[str, Any]) -> Dict[str, Any]:
    f = _decode_fields(node)
    f['customer_name'] = f.get('customer_name','')
    f['customer_email'] = f.get('customer_email','')
    return f


def _assert_owner(node: Dict[str, Any], customer_id: Optional[str]):
    if not customer_id:
        raise HTTPException(401, 'Please sign in to manage your Philia requests.')
    owner = _decode_fields(node).get('customer_id','').strip()
    if not owner or owner != str(customer_id):
        raise HTTPException(403, 'This request is not linked to your customer account.')


@router.get('/api/briefs/health')
@router.get('/api/briefs/health/')
def briefs_health(request: Request):
    _proxy_identity(request)
    _ensure_definition()
    return {'ok': True, 'storage': 'shopify_metaobjects', 'draft_orders': True, 'database_required': False}


@router.post('/api/briefs')
@router.post('/api/briefs/')
def create_brief(payload: BriefCreate, request: Request):
    customer_id, _ = _proxy_identity(request)
    kind = _clean(payload.request_type, 32).lower()
    if kind not in VALID_TYPES:
        raise HTTPException(422, 'Invalid request type.')
    name = _clean(payload.name, 180)
    email = _clean(payload.email, 320)
    details = _clean(payload.details, 12000)
    if not name or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email) or not details:
        raise HTTPException(422, 'Name, valid email and request details are required.')
    event_date = _validated_date(payload.event_date)
    if payload.guest_count is not None and not (1 <= payload.guest_count <= 100000):
        raise HTTPException(422, 'Guest count is out of range.')
    _rate_limit_create(request)
    reference = _reference(kind)
    now = _now_iso()
    audit = [_audit_event('submitted', 'customer' if customer_id else 'guest', {'request_type': kind})]
    values = {
        'reference': reference,
        'request_type': kind,
        'status': 'submitted',
        'customer_id': str(customer_id or ''),
        'customer_name': name,
        'customer_email': email,
        'phone': _clean(payload.phone, 80),
        'event_date': event_date,
        'guest_count': str(payload.guest_count or ''),
        'venue': _clean(payload.venue, 300),
        'budget': _clean(payload.budget, 180),
        'occasion': _clean(payload.occasion, 240),
        'colours': _clean(payload.colours, 300),
        'company': _clean(payload.company, 240),
        'quantity_scope': _clean(payload.quantity_scope, 300),
        'details': details,
        'quote_amount_kwd': '',
        'internal_note': '',
        'cancellation_reason': '',
        'audit_history': audit,
        'draft_order_id': '',
        'draft_order_name': '',
        'locale': _clean(payload.locale, 12) or 'en',
        'created_at': now,
        'updated_at': now,
        'cancelled_at': '',
    }
    node = _create_metaobject(values)
    draft = _create_draft(values)
    if draft.get('id'):
        values['draft_order_id'] = draft['id']
        values['draft_order_name'] = draft.get('name') or ''
        values['audit_history'] = audit + [_audit_event('draft_order_created', 'system', {'name': draft.get('name')})]
        node = _update_metaobject(node['id'], {
            'draft_order_id': values['draft_order_id'],
            'draft_order_name': values['draft_order_name'],
            'audit_history': values['audit_history'],
            'updated_at': _now_iso(),
        })
    notified = _notify('new', values)
    return {'ok': True, 'brief': _serialize_node(node), 'storage': 'shopify', 'notification_sent': notified}


@router.get('/api/briefs')
@router.get('/api/briefs/')
def list_briefs(request: Request):
    customer_id, _ = _proxy_identity(request)
    if not customer_id:
        raise HTTPException(401, 'Please sign in to see your Philia requests.')
    out = []
    for node in _all_nodes():
        f = _decode_fields(node)
        if f.get('customer_id','').strip() == str(customer_id):
            out.append(_serialize_node(node))
    out.sort(key=lambda x: x.get('created_at') or '', reverse=True)
    return {'ok': True, 'briefs': out, 'storage': 'shopify'}


@router.patch('/api/briefs/{reference}')
@router.patch('/api/briefs/{reference}/')
def update_brief(reference: str, payload: BriefUpdate, request: Request):
    customer_id, _ = _proxy_identity(request)
    node = _node_by_reference(reference)
    if not node:
        raise HTTPException(404, 'Request not found.')
    _assert_owner(node, customer_id)
    existing = _full_values(node)
    if existing.get('status') in {'cancelled', 'completed'}:
        raise HTTPException(409, 'This request can no longer be edited.')
    if payload.event_date is not None: _validated_date(payload.event_date)
    if payload.guest_count is not None and not (1 <= payload.guest_count <= 100000):
        raise HTTPException(422, 'Guest count is out of range.')
    patch = {}
    for key in ['phone','event_date','guest_count','venue','budget','occasion','colours','company','quantity_scope','details']:
        val = getattr(payload, key)
        if val is not None:
            patch[key] = str(val) if key == 'guest_count' else (_validated_date(val) if key == 'event_date' else _clean(val, 12000 if key == 'details' else 1000))
    try:
        audit = json.loads(existing.get('audit_history') or '[]')
        if not isinstance(audit, list): audit = []
    except Exception:
        audit = []
    audit = (audit + [_audit_event('customer_updated', 'customer', {'fields': sorted(patch.keys())})])[-60:]
    patch['audit_history'] = audit
    patch['updated_at'] = _now_iso()
    updated = _update_metaobject(node['id'], patch)
    merged = {**existing, **patch}
    _update_draft(existing.get('draft_order_id',''), merged)
    notified = _notify('edit', merged)
    return {'ok': True, 'brief': _serialize_node(updated), 'notification_sent': notified}


@router.post('/api/briefs/{reference}/cancel')
@router.post('/api/briefs/{reference}/cancel/')
def cancel_brief(reference: str, payload: CancelPayload, request: Request):
    customer_id, _ = _proxy_identity(request)
    node = _node_by_reference(reference)
    if not node:
        raise HTTPException(404, 'Request not found.')
    _assert_owner(node, customer_id)
    existing = _full_values(node)
    if existing.get('status') == 'completed':
        raise HTTPException(409, 'Completed requests cannot be cancelled online.')
    if existing.get('status') == 'cancelled':
        return {'ok': True, 'brief': _serialize_node(node), 'already_cancelled': True}
    try:
        audit = json.loads(existing.get('audit_history') or '[]')
        if not isinstance(audit, list): audit = []
    except Exception:
        audit = []
    reason = _clean(payload.reason, 3000)
    now = _now_iso()
    patch = {
        'status': 'cancelled',
        'cancellation_reason': reason,
        'cancelled_at': now,
        'updated_at': now,
        'audit_history': (audit + [_audit_event('cancelled', 'customer', {'reason': reason})])[-60:],
    }
    updated = _update_metaobject(node['id'], patch)
    merged = {**existing, **patch}
    _update_draft(existing.get('draft_order_id',''), merged)
    notified = _notify('cancel', merged)
    return {'ok': True, 'brief': _serialize_node(updated), 'notification_sent': notified}


@router.get('/admin', response_class=HTMLResponse)
def admin_info():
    # No customer data is exposed here. Merchant data is intentionally managed in Shopify Admin.
    return HTMLResponse('''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Philia Requests</title><style>body{margin:0;background:#082f38;color:#f7f3ea;font-family:Arial,sans-serif;display:grid;min-height:100vh;place-items:center}.c{max-width:720px;padding:34px;border:1px solid #bfb073;background:#0b3f4d}h1{font-weight:400}a{color:#e3d9b8}</style></head><body><div class="c"><h1>Philia Requests · Shopify Native</h1><p>The request database now lives inside Shopify. Open <b>Shopify Admin → Content → Metaobjects → Philia Requests</b> to manage requests, and <b>Orders → Drafts</b> for the mirrored commercial view.</p><p>No PostgreSQL database is required.</p></div></body></html>''')
