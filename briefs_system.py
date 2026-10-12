import os, re, hmac, hashlib, secrets, smtplib, json, html, time
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional, Dict, Any, List

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

router = APIRouter()

SHOPIFY_SHOP = os.getenv('SHOPIFY_SHOP','').strip().replace('https://','').replace('.myshopify.com','').strip('/')
SHOPIFY_CLIENT_ID = os.getenv('SHOPIFY_CLIENT_ID','').strip()
SHOPIFY_CLIENT_SECRET = os.getenv('SHOPIFY_CLIENT_SECRET','').strip()
SHOPIFY_ADMIN_API_VERSION = os.getenv('SHOPIFY_ADMIN_API_VERSION','2026-10').strip()
PHILIA_NOTIFICATION_EMAIL = os.getenv('PHILIA_NOTIFICATION_EMAIL','').strip()
SMTP_HOST = os.getenv('SMTP_HOST','').strip()
SMTP_PORT = int(os.getenv('SMTP_PORT','587') or 587)
SMTP_USER = os.getenv('SMTP_USER','').strip()
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD','').strip()
SMTP_FROM = os.getenv('SMTP_FROM_EMAIL','').strip() or SMTP_USER or PHILIA_NOTIFICATION_EMAIL
ADMIN_DASHBOARD_USER = os.getenv('ADMIN_DASHBOARD_USER','philia').strip() or 'philia'
ADMIN_DASHBOARD_PASSWORD = os.getenv('ADMIN_DASHBOARD_PASSWORD','').strip()
ADMIN_SESSION_SECRET = os.getenv('ADMIN_SESSION_SECRET','').strip() or SHOPIFY_CLIENT_SECRET or secrets.token_hex(32)
ALLOW_UNSIGNED_PROXY = os.getenv('ALLOW_UNSIGNED_PROXY','false').lower() in {'1','true','yes'}

META_TYPE = '$app:philia_request'
_token_cache = {'token':'','expires_at':0.0}
_definition_ready = False

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

VALID_TYPES = {'event','bespoke','corporate'}
EDITABLE_STATUSES = {'submitted','in_review','quoted','confirmed'}

FIELD_DEFS = [
    ('Reference','reference','single_line_text_field'),
    ('Request type','request_type','single_line_text_field'),
    ('Status','status','single_line_text_field'),
    ('Customer ID','customer_id','single_line_text_field'),
    ('Customer email','customer_email','single_line_text_field'),
    ('Customer name','customer_name','single_line_text_field'),
    ('Phone','phone','single_line_text_field'),
    ('Event date','event_date','date'),
    ('Guest count','guest_count','number_integer'),
    ('Venue','venue','single_line_text_field'),
    ('Budget','budget','single_line_text_field'),
    ('Occasion','occasion','single_line_text_field'),
    ('Colours','colours','single_line_text_field'),
    ('Company','company','single_line_text_field'),
    ('Quantity / scope','quantity_scope','single_line_text_field'),
    ('Details','details','multi_line_text_field'),
    ('Quote amount KWD','quote_amount_kwd','number_decimal'),
    ('Internal note','internal_note','multi_line_text_field'),
    ('Cancellation reason','cancellation_reason','multi_line_text_field'),
    ('Draft order ID','shopify_draft_order_id','single_line_text_field'),
    ('Draft order name','shopify_draft_order_name','single_line_text_field'),
    ('Created at','created_at','date_time'),
    ('Updated at','updated_at','date_time'),
    ('Cancelled at','cancelled_at','date_time'),
    ('Last customer edit at','last_customer_edit_at','date_time'),
    ('Audit history','audit_history','json'),
]


def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')

def _clean(v, n=500):
    if v is None: return None
    s=str(v).strip()
    return s[:n] if s else None

def _reference(kind: str):
    prefix={'event':'EV','bespoke':'BQ','corporate':'CO'}.get(kind,'RQ')
    return f"PH-{prefix}-{datetime.now().strftime('%y%m%d')}-{secrets.token_hex(2).upper()}"

def _handle(ref:str):
    return re.sub(r'[^a-z0-9-]+','-',ref.lower()).strip('-')

def _shop_domain():
    if not SHOPIFY_SHOP: raise HTTPException(503,'SHOPIFY_SHOP is not configured.')
    return f'{SHOPIFY_SHOP}.myshopify.com'

def _access_token(force=False):
    now=time.time()
    if not force and _token_cache['token'] and now < _token_cache['expires_at']-90:
        return _token_cache['token']
    if not (SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET):
        raise HTTPException(503,'Shopify app credentials are not configured.')
    url=f'https://{_shop_domain()}/admin/oauth/access_token'
    try:
        with httpx.Client(timeout=20) as c:
            r=c.post(url,headers={'Content-Type':'application/x-www-form-urlencoded'},data={
                'grant_type':'client_credentials','client_id':SHOPIFY_CLIENT_ID,'client_secret':SHOPIFY_CLIENT_SECRET})
            r.raise_for_status(); data=r.json()
        token=data.get('access_token'); exp=int(data.get('expires_in') or 86399)
        if not token: raise RuntimeError('No access_token returned')
        _token_cache.update(token=token,expires_at=now+exp)
        return token
    except Exception as e:
        raise HTTPException(503,f'Shopify authentication failed: {str(e)[:180]}')

def _gql(query:str, variables:Optional[Dict[str,Any]]=None):
    url=f'https://{_shop_domain()}/admin/api/{SHOPIFY_ADMIN_API_VERSION}/graphql.json'
    def call(token):
        with httpx.Client(timeout=25) as c:
            return c.post(url,headers={'X-Shopify-Access-Token':token,'Content-Type':'application/json'},json={'query':query,'variables':variables or {}})
    r=call(_access_token())
    if r.status_code in (401,403):
        r=call(_access_token(True))
    try: data=r.json()
    except Exception: raise HTTPException(502,'Invalid response from Shopify Admin API.')
    if r.status_code>=400: raise HTTPException(502,f'Shopify API HTTP {r.status_code}: {str(data)[:500]}')
    if data.get('errors'): raise HTTPException(502,f"Shopify GraphQL error: {data['errors'][0].get('message','Unknown error')}")
    return data.get('data') or {}

def _user_errors(payload:Dict[str,Any], key:str):
    errs=((payload.get(key) or {}).get('userErrors') or [])
    if errs:
        msg='; '.join(str(e.get('message') or 'Shopify error') for e in errs[:3])
        raise HTTPException(422,msg)

def _ensure_definition():
    global _definition_ready
    if _definition_ready: return
    q='query($type:String!){metaobjectDefinitionByType(type:$type){id name type}}'
    d=_gql(q,{'type':META_TYPE})
    if d.get('metaobjectDefinitionByType'):
        _definition_ready=True; return
    mutation='''mutation($definition:MetaobjectDefinitionCreateInput!){metaobjectDefinitionCreate(definition:$definition){metaobjectDefinition{id type name} userErrors{field message code}}}'''
    definition={
        'name':'Philia Requests','type':META_TYPE,'displayNameKey':'reference',
        'access':{'admin':'MERCHANT_READ_WRITE','storefront':'NONE'},
        'fieldDefinitions':[{'name':n,'key':k,'type':t} for n,k,t in FIELD_DEFS]
    }
    d=_gql(mutation,{'definition':definition}); _user_errors(d,'metaobjectDefinitionCreate')
    _definition_ready=True

def init_brief_store():
    if not (SHOPIFY_SHOP and SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET):
        print('[PHILIA REQUESTS] Shopify credentials not complete yet.',flush=True); return
    try:
        _ensure_definition(); print('[PHILIA REQUESTS] Shopify Metaobject store ready.',flush=True)
    except Exception as e:
        print('[PHILIA REQUESTS] definition init deferred:',repr(e),flush=True)


def _fields_to_dict(node:Dict[str,Any]):
    out={'id':node.get('id'),'handle':node.get('handle')}
    for f in node.get('fields') or []:
        out[f.get('key')]=f.get('value')
    for k in ('guest_count',):
        if out.get(k) not in (None,''):
            try: out[k]=int(float(out[k]))
            except Exception: pass
    if out.get('quote_amount_kwd') not in (None,''):
        try: out['quote_amount_kwd']=float(out['quote_amount_kwd'])
        except Exception: pass
    for k in ('audit_history',):
        try: out[k]=json.loads(out.get(k) or '[]')
        except Exception: out[k]=[]
    return out

def _serialize(d:Dict[str,Any], admin=False):
    keys=['reference','request_type','status','customer_email','customer_name','phone','event_date','guest_count','venue','budget','occasion','colours','company','quantity_scope','details','quote_amount_kwd','created_at','updated_at','cancelled_at','shopify_draft_order_name']
    out={k:d.get(k) for k in keys}
    out['name']=out.pop('customer_name',None); out['email']=out.pop('customer_email',None)
    if admin:
        out.update({k:d.get(k) for k in ['customer_id','internal_note','cancellation_reason','shopify_draft_order_id','audit_history']})
    return out

def _field_list(d:Dict[str,Any]):
    vals=[]
    types={k:t for _,k,t in FIELD_DEFS}
    typed_nonempty={'event_date','guest_count','quote_amount_kwd','created_at','updated_at','cancelled_at','last_customer_edit_at'}
    for _,key,_ in FIELD_DEFS:
        if key not in d: continue
        v=d.get(key)
        if key in typed_nonempty and v in (None,''):
            continue
        if v is None: v=''
        if key=='audit_history' and not isinstance(v,str): v=json.dumps(v,ensure_ascii=False,default=str)
        vals.append({'key':key,'value':str(v)})
    return vals

def _audit(record:Dict[str,Any], actor:str, action:str, payload=None):
    arr=list(record.get('audit_history') or [])[-49:]
    arr.append({'at':_now(),'actor':actor,'action':action,'payload':payload or {}})
    record['audit_history']=arr


def _proxy_signature_ok(request:Request):
    if ALLOW_UNSIGNED_PROXY: return True
    if not SHOPIFY_CLIENT_SECRET: return False
    supplied=request.query_params.get('signature','')
    if not supplied: return False
    grouped:Dict[str,List[str]]={}
    for k,v in request.query_params.multi_items():
        if k=='signature': continue
        grouped.setdefault(k,[]).append(v)
    canonical=''.join(sorted(f"{k}={','.join(vs)}" for k,vs in grouped.items()))
    digest=hmac.new(SHOPIFY_CLIENT_SECRET.encode(),canonical.encode(),hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest,supplied)

def _proxy_identity(request:Request):
    if not _proxy_signature_ok(request): raise HTTPException(401,'Invalid Shopify app proxy signature.')
    shop=request.query_params.get('shop','').strip()
    if shop and shop != _shop_domain(): raise HTTPException(403,'Wrong Shopify store.')
    return request.query_params.get('logged_in_customer_id','').strip() or None


def _get_by_handle(handle:str):
    _ensure_definition()
    q='''query($handle:MetaobjectHandleInput!){metaobjectByHandle(handle:$handle){id handle fields{key value}}}'''
    d=_gql(q,{'handle':{'type':META_TYPE,'handle':handle}})
    node=d.get('metaobjectByHandle')
    return _fields_to_dict(node) if node else None

def _get_by_reference(ref:str):
    return _get_by_handle(_handle(ref))

def _all_records(limit=1200):
    _ensure_definition(); out=[]; after=None
    q='''query($type:String!,$after:String){metaobjects(type:$type,first:100,after:$after){nodes{id handle fields{key value}} pageInfo{hasNextPage endCursor}}}'''
    while len(out)<limit:
        d=_gql(q,{'type':META_TYPE,'after':after}); conn=d.get('metaobjects') or {}
        out.extend(_fields_to_dict(n) for n in conn.get('nodes') or [])
        pi=conn.get('pageInfo') or {}
        if not pi.get('hasNextPage'): break
        after=pi.get('endCursor')
        if not after: break
    return out

def _create_meta(record:Dict[str,Any]):
    _ensure_definition()
    q='''mutation($metaobject:MetaobjectCreateInput!){metaobjectCreate(metaobject:$metaobject){metaobject{id handle fields{key value}} userErrors{field message code}}}'''
    inp={'type':META_TYPE,'handle':_handle(record['reference']),'fields':_field_list(record)}
    d=_gql(q,{'metaobject':inp}); _user_errors(d,'metaobjectCreate')
    node=((d.get('metaobjectCreate') or {}).get('metaobject'))
    if not node: raise HTTPException(502,'Shopify did not create the request record.')
    return _fields_to_dict(node)

def _update_meta(record:Dict[str,Any]):
    q='''mutation($id:ID!,$metaobject:MetaobjectUpdateInput!){metaobjectUpdate(id:$id,metaobject:$metaobject){metaobject{id handle fields{key value}} userErrors{field message code}}}'''
    d=_gql(q,{'id':record['id'],'metaobject':{'fields':_field_list(record)}}); _user_errors(d,'metaobjectUpdate')
    node=((d.get('metaobjectUpdate') or {}).get('metaobject'))
    return _fields_to_dict(node) if node else record


def _draft_input(record:Dict[str,Any]):
    ref=record.get('reference','Philia request'); status=record.get('status','submitted'); typ=record.get('request_type','request')
    attrs=[]
    mapping=[('Philia Reference','reference'),('Request Type','request_type'),('Request Status','status'),('Event Date','event_date'),('Venue','venue'),('Budget','budget'),('Guest Count','guest_count'),('Occasion','occasion'),('Company','company'),('Cancellation Reason','cancellation_reason')]
    for label,key in mapping:
        v=record.get(key)
        if v not in (None,''): attrs.append({'key':label,'value':str(v)[:255]})
    title=f"Philia {typ.title()} Request — {ref}"
    return {
        'email':record.get('customer_email') or None,
        'note':(record.get('details') or '')[:5000],
        'tags':['Philia Request',f'Philia:{typ}',f'Philia:{status}',ref],
        'customAttributes':attrs,
        'lineItems':[{'title':title[:255],'quantity':1,'originalUnitPrice':'0.00'}]
    }

def _sync_draft(record:Dict[str,Any]):
    try:
        inp=_draft_input(record)
        if record.get('shopify_draft_order_id'):
            q='''mutation($id:ID!,$input:DraftOrderInput!){draftOrderUpdate(id:$id,input:$input){draftOrder{id name} userErrors{field message}}}'''
            d=_gql(q,{'id':record['shopify_draft_order_id'],'input':inp}); _user_errors(d,'draftOrderUpdate'); node=((d.get('draftOrderUpdate') or {}).get('draftOrder') or {})
        else:
            q='''mutation($input:DraftOrderInput!){draftOrderCreate(input:$input){draftOrder{id name} userErrors{field message}}}'''
            d=_gql(q,{'input':inp}); _user_errors(d,'draftOrderCreate'); node=((d.get('draftOrderCreate') or {}).get('draftOrder') or {})
        if node:
            record['shopify_draft_order_id']=node.get('id'); record['shopify_draft_order_name']=node.get('name')
            return True
    except Exception as e:
        print('[PHILIA REQUESTS] Draft order sync failed:',repr(e),flush=True)
    return False


def _mail(to_email,subject,body):
    if not (SMTP_HOST and SMTP_FROM and to_email): return False
    try:
        msg=EmailMessage(); msg['From']=SMTP_FROM; msg['To']=to_email; msg['Subject']=subject
        msg.set_content(re.sub('<[^>]+>','',body)); msg.add_alternative(body,subtype='html')
        with smtplib.SMTP(SMTP_HOST,SMTP_PORT,timeout=20) as s:
            s.starttls()
            if SMTP_USER: s.login(SMTP_USER,SMTP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as e:
        print('[PHILIA REQUESTS] email failed',repr(e),flush=True); return False

def _email_html(r,heading):
    rows=''.join(f'<tr><td style="padding:6px 10px;color:#667">{html.escape(k)}</td><td style="padding:6px 10px"><b>{html.escape(str(r.get(v) or ""))}</b></td></tr>' for k,v in [('Reference','reference'),('Type','request_type'),('Status','status'),('Name','customer_name'),('Email','customer_email'),('Phone','phone'),('Date','event_date'),('Guests','guest_count'),('Venue','venue'),('Budget','budget')])
    return f'<div style="font-family:Arial;color:#142326"><h2>{html.escape(heading)}</h2><table>{rows}</table><h3>Details</h3><p>{html.escape(r.get("details") or "")}</p></div>'


@router.get('/briefs/health')
def briefs_health():
    ok=bool(SHOPIFY_SHOP and SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET)
    data={'ok':ok,'storage':'shopify_metaobjects','shop':_shop_domain() if SHOPIFY_SHOP else None,'smtp':bool(SMTP_HOST and SMTP_FROM),'proxy_verification':bool(SHOPIFY_CLIENT_SECRET)}
    if ok:
        try: _ensure_definition(); data['metaobject_definition']='ready'
        except Exception as e: data['ok']=False; data['metaobject_definition']=str(e)[:300]
    return JSONResponse(data,status_code=200 if data['ok'] else 503)

@router.post('/api/briefs')
def create_brief(payload:BriefCreate, request:Request):
    customer_id=None
    if request.url.path.startswith('/proxy/'):
        customer_id=_proxy_identity(request)
    kind=payload.request_type.strip().lower()
    if kind not in VALID_TYPES: raise HTTPException(422,'Unknown request type.')
    email=_clean(payload.email,320)
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$',email or ''): raise HTTPException(422,'Valid email required.')
    now=_now(); ref=_reference(kind)
    rec={
        'reference':ref,'request_type':kind,'status':'submitted','customer_id':customer_id or '',
        'customer_email':email,'customer_name':_clean(payload.name,180) or 'Customer','phone':_clean(payload.phone,80) or '',
        'event_date':_clean(payload.event_date,10) or '','guest_count':payload.guest_count or '', 'venue':_clean(payload.venue,300) or '',
        'budget':_clean(payload.budget,180) or '', 'occasion':_clean(payload.occasion,240) or '', 'colours':_clean(payload.colours,300) or '',
        'company':_clean(payload.company,240) or '', 'quantity_scope':_clean(payload.quantity_scope,300) or '', 'details':_clean(payload.details,12000) or '',
        'quote_amount_kwd':'','internal_note':'','cancellation_reason':'','shopify_draft_order_id':'','shopify_draft_order_name':'',
        'created_at':now,'updated_at':now,'cancelled_at':'','last_customer_edit_at':'','audit_history':[]
    }
    _audit(rec,'customer','created',{'request_type':kind})
    rec=_create_meta(rec)
    if _sync_draft(rec): rec=_update_meta(rec)
    if PHILIA_NOTIFICATION_EMAIL: _mail(PHILIA_NOTIFICATION_EMAIL,f'New Philia request {ref}',_email_html(rec,'New Philia request'))
    _mail(email,f'We received your Philia request {ref}',_email_html(rec,'Your request has been received'))
    return {'ok':True,'brief':_serialize(rec)}

@router.get('/api/briefs')
def list_briefs(request:Request):
    if not request.url.path.startswith('/proxy/'): raise HTTPException(401,'Customer list requires Shopify app proxy.')
    cid=_proxy_identity(request)
    if not cid: raise HTTPException(401,'Please sign in to manage your Philia requests.')
    rows=[r for r in _all_records() if str(r.get('customer_id') or '')==str(cid)]
    rows.sort(key=lambda x:x.get('created_at') or '',reverse=True)
    return {'ok':True,'customer_id':cid,'briefs':[_serialize(r) for r in rows]}

def _authorized_record(reference:str,request:Request):
    if not request.url.path.startswith('/proxy/'): raise HTTPException(401,'Shopify app proxy required.')
    cid=_proxy_identity(request)
    if not cid: raise HTTPException(401,'Please sign in to manage this request.')
    r=_get_by_reference(reference)
    if not r: raise HTTPException(404,'Request not found.')
    if str(r.get('customer_id') or '')!=str(cid): raise HTTPException(403,'Not allowed.')
    return r

@router.patch('/api/briefs/{reference}')
def update_brief(reference:str,payload:BriefUpdate,request:Request):
    r=_authorized_record(reference,request)
    if r.get('status') not in EDITABLE_STATUSES: raise HTTPException(409,'This request can no longer be edited.')
    changes={}
    for key in ['phone','venue','budget','occasion','colours','company','quantity_scope','details']:
        v=getattr(payload,key)
        if v is not None: r[key]=_clean(v,12000 if key=='details' else 300) or ''; changes[key]=r[key]
    if payload.event_date is not None: r['event_date']=_clean(payload.event_date,10) or ''; changes['event_date']=r['event_date']
    if payload.guest_count is not None: r['guest_count']=max(1,payload.guest_count); changes['guest_count']=r['guest_count']
    r['updated_at']=_now(); r['last_customer_edit_at']=r['updated_at']
    if r.get('status')=='quoted': r['status']='in_review'
    _audit(r,'customer','updated',changes)
    _sync_draft(r); r=_update_meta(r)
    if PHILIA_NOTIFICATION_EMAIL: _mail(PHILIA_NOTIFICATION_EMAIL,f'Customer updated {r["reference"]}',_email_html(r,'Customer updated a Philia request'))
    return {'ok':True,'brief':_serialize(r)}

@router.post('/api/briefs/{reference}/cancel')
def cancel_brief(reference:str,payload:CancelPayload,request:Request):
    r=_authorized_record(reference,request)
    if r.get('status')=='cancelled': return {'ok':True,'brief':_serialize(r)}
    r['status']='cancelled'; r['cancellation_reason']=_clean(payload.reason,1500) or ''; r['cancelled_at']=_now(); r['updated_at']=r['cancelled_at']
    _audit(r,'customer','cancelled',{'reason':r['cancellation_reason']})
    _sync_draft(r); r=_update_meta(r)
    sent=False
    if PHILIA_NOTIFICATION_EMAIL:
        sent=_mail(PHILIA_NOTIFICATION_EMAIL,f'CANCELLED — {r["reference"]}',_email_html(r,'Customer cancelled a Philia request')+f'<p><b>Reason:</b> {html.escape(r.get("cancellation_reason") or "Not provided")}</p>')
    _mail(r.get('customer_email'),f'Cancellation confirmed — {r["reference"]}',_email_html(r,'Your cancellation is confirmed'))
    return {'ok':True,'brief':_serialize(r),'merchant_email_sent':sent}


def _admin_ok(request:Request):
    token=request.cookies.get('philia_admin','')
    try:
        u,exp,sig=token.rsplit(':',2); payload=f'{u}:{exp}'
        if u!=ADMIN_DASHBOARD_USER or int(exp)<int(time.time()): return False
        want=hmac.new(ADMIN_SESSION_SECRET.encode(),payload.encode(),hashlib.sha256).hexdigest()
        return hmac.compare_digest(want,sig)
    except Exception:return False

def _admin_token():
    exp=int(time.time()+12*3600); payload=f'{ADMIN_DASHBOARD_USER}:{exp}'
    sig=hmac.new(ADMIN_SESSION_SECRET.encode(),payload.encode(),hashlib.sha256).hexdigest(); return f'{payload}:{sig}'

@router.get('/admin',response_class=HTMLResponse)
def admin_page(request:Request):
    if not ADMIN_DASHBOARD_PASSWORD:
        return HTMLResponse('<h2>Philia Request Center</h2><p>Set ADMIN_DASHBOARD_PASSWORD in Render to enable this dashboard.</p>',503)
    if not _admin_ok(request):
        return HTMLResponse('''<!doctype html><meta name="viewport" content="width=device-width"><style>body{font-family:Arial;background:#092e36;color:#fff;display:grid;place-items:center;height:100vh;margin:0}form{background:#f5efe3;color:#123;padding:32px;width:min(360px,80vw)}input,button{width:100%;padding:12px;margin-top:10px;box-sizing:border-box}</style><form method="post" action="/admin/login"><h2>Philia Request Center</h2><input name="password" type="password" placeholder="Dashboard password" required><button>Sign in</button></form>''')
    rows=_all_records(); rows.sort(key=lambda x:x.get('created_at') or '',reverse=True)
    cards=''.join(f'''<tr><td>{html.escape(r.get('reference') or '')}</td><td>{html.escape(r.get('request_type') or '')}</td><td><b>{html.escape(r.get('status') or '')}</b></td><td>{html.escape(r.get('customer_name') or '')}<br><small>{html.escape(r.get('customer_email') or '')}</small></td><td>{html.escape(r.get('event_date') or '')}</td><td>{html.escape(r.get('venue') or '')}</td><td>{html.escape(r.get('budget') or '')}</td><td>{html.escape(r.get('shopify_draft_order_name') or '')}</td></tr>''' for r in rows)
    counts={s:sum(1 for r in rows if r.get('status')==s) for s in ['submitted','in_review','quoted','confirmed','cancelled']}
    return HTMLResponse(f'''<!doctype html><meta name="viewport" content="width=device-width"><style>body{{font-family:Arial;margin:0;background:#f4efe6;color:#123}}header{{background:#072f38;color:#fff;padding:24px}}main{{padding:22px;overflow:auto}}.stats{{display:flex;gap:8px;flex-wrap:wrap}}.stat{{background:#fff;padding:14px;min-width:110px}}table{{width:100%;border-collapse:collapse;background:#fff;margin-top:18px;min-width:900px}}th,td{{padding:11px;border-bottom:1px solid #ddd;text-align:left;font-size:13px}}th{{background:#0d4551;color:#fff}}</style><header><h1>Philia Request Center</h1><p>Shopify-native request database · {len(rows)} total requests</p></header><main><div class="stats">{''.join(f'<div class="stat"><b>{counts[s]}</b><br>{s.replace("_"," ").title()}</div>' for s in counts)}</div><table><thead><tr><th>Reference</th><th>Type</th><th>Status</th><th>Customer</th><th>Date</th><th>Venue</th><th>Budget</th><th>Draft</th></tr></thead><tbody>{cards}</tbody></table></main>''')

@router.post('/admin/login')
async def admin_login(request:Request):
    form=await request.form(); pw=str(form.get('password') or '')
    if not hmac.compare_digest(pw,ADMIN_DASHBOARD_PASSWORD): raise HTTPException(401,'Wrong password')
    resp=HTMLResponse('<meta http-equiv="refresh" content="0;url=/admin">Signed in')
    resp.set_cookie('philia_admin',_admin_token(),httponly=True,secure=True,samesite='lax',max_age=43200)
    return resp
