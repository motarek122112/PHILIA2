import os, re, hmac, hashlib, secrets, smtplib, json, csv, io, html
from datetime import datetime, timezone, timedelta, date
from email.message import EmailMessage
from typing import Optional, Dict, Any, List
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

try:
    from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Date, Boolean, Numeric, select, or_, func
    from sqlalchemy.orm import declarative_base, sessionmaker
    SQLALCHEMY_OK = True
except Exception:
    SQLALCHEMY_OK = False

router = APIRouter()
DATABASE_URL = os.getenv('DATABASE_URL','').strip()
SHOPIFY_API_SECRET = os.getenv('SHOPIFY_API_SECRET','').strip()
SHOPIFY_STORE_DOMAIN = os.getenv('SHOPIFY_STORE_DOMAIN','').strip().replace('https://','').strip('/')
SHOPIFY_ADMIN_TOKEN = os.getenv('SHOPIFY_ADMIN_TOKEN','').strip()
SHOPIFY_ADMIN_API_VERSION = os.getenv('SHOPIFY_ADMIN_API_VERSION','2026-10').strip()
PHILIA_NOTIFICATION_EMAIL = os.getenv('PHILIA_NOTIFICATION_EMAIL','').strip()
SMTP_HOST = os.getenv('SMTP_HOST','').strip()
SMTP_PORT = int(os.getenv('SMTP_PORT','587') or 587)
SMTP_USER = os.getenv('SMTP_USER','').strip()
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD','').strip()
SMTP_FROM = os.getenv('SMTP_FROM_EMAIL','').strip() or SMTP_USER or PHILIA_NOTIFICATION_EMAIL
ADMIN_DASHBOARD_USER = os.getenv('ADMIN_DASHBOARD_USER','philia').strip() or 'philia'
ADMIN_DASHBOARD_PASSWORD = os.getenv('ADMIN_DASHBOARD_PASSWORD','').strip()
ADMIN_SESSION_SECRET = os.getenv('ADMIN_SESSION_SECRET','').strip() or SHOPIFY_API_SECRET or secrets.token_hex(32)
CRON_SECRET = os.getenv('CRON_SECRET','').strip()
ALLOW_UNSIGNED_PROXY = os.getenv('ALLOW_UNSIGNED_PROXY','false').lower() in {'1','true','yes'}

Base = declarative_base() if SQLALCHEMY_OK else object
_engine = None
SessionLocal = None
DB_ERROR = None

if SQLALCHEMY_OK and DATABASE_URL:
    try:
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
        SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)
    except Exception as e:
        DB_ERROR = repr(e)
else:
    DB_ERROR = 'DATABASE_URL missing' if not DATABASE_URL else 'SQLAlchemy unavailable'

if SQLALCHEMY_OK:
    class Brief(Base):
        __tablename__ = 'philia_briefs'
        id = Column(Integer, primary_key=True)
        reference = Column(String(40), unique=True, nullable=False, index=True)
        request_type = Column(String(32), nullable=False, index=True)
        status = Column(String(24), nullable=False, default='submitted', index=True)
        customer_id = Column(String(64), nullable=True, index=True)
        customer_email = Column(String(320), nullable=False, index=True)
        customer_name = Column(String(180), nullable=False)
        phone = Column(String(80), nullable=True)
        event_date = Column(Date, nullable=True, index=True)
        guest_count = Column(Integer, nullable=True)
        venue = Column(String(300), nullable=True)
        budget = Column(String(180), nullable=True)
        occasion = Column(String(240), nullable=True)
        colours = Column(String(300), nullable=True)
        company = Column(String(240), nullable=True)
        quantity_scope = Column(String(300), nullable=True)
        details = Column(Text, nullable=False)
        quote_amount_kwd = Column(Numeric(12,3), nullable=True)
        internal_note = Column(Text, nullable=True)
        cancellation_reason = Column(Text, nullable=True)
        manage_token_hash = Column(String(64), nullable=False)
        shopify_draft_order_id = Column(String(120), nullable=True)
        shopify_draft_order_name = Column(String(80), nullable=True)
        created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
        updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
        cancelled_at = Column(DateTime(timezone=True), nullable=True)
        last_customer_edit_at = Column(DateTime(timezone=True), nullable=True)

    class BriefAudit(Base):
        __tablename__ = 'philia_brief_audit'
        id = Column(Integer, primary_key=True)
        brief_id = Column(Integer, nullable=False, index=True)
        reference = Column(String(40), nullable=False, index=True)
        actor = Column(String(80), nullable=False)
        action = Column(String(80), nullable=False)
        payload_json = Column(Text, nullable=True)
        created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

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

class AdminLogin(BaseModel):
    username: str
    password: str

class AdminUpdate(BaseModel):
    status: Optional[str] = None
    quote_amount_kwd: Optional[float] = None
    internal_note: Optional[str] = None

VALID_TYPES = {'event','bespoke','corporate'}
VALID_STATUSES = {'submitted','in_review','quoted','confirmed','completed','cancelled'}


def init_brief_db():
    global DB_ERROR
    if not _engine or not SQLALCHEMY_OK:
        return
    try:
        Base.metadata.create_all(bind=_engine)
        DB_ERROR = None
    except Exception as e:
        DB_ERROR = repr(e)
        print('[PHILIA BRIEFS] DB init failed', DB_ERROR, flush=True)


def _require_db():
    if not SessionLocal:
        raise HTTPException(503, 'Event brief database is not configured yet.')


def _now(): return datetime.now(timezone.utc)

def _date(v: Optional[str]):
    if not v: return None
    try: return date.fromisoformat(v[:10])
    except Exception: raise HTTPException(422, 'Invalid date')

def _clean(v, n=500):
    if v is None: return None
    return str(v).strip()[:n]

def _hash_token(token: str): return hashlib.sha256(token.encode()).hexdigest()

def _reference(kind: str):
    prefix = {'event':'EV','bespoke':'BQ','corporate':'CO'}.get(kind,'RQ')
    return f"PH-{prefix}-{datetime.now().strftime('%y%m%d')}-{secrets.token_hex(2).upper()}"


def _audit(db, brief, actor, action, payload=None):
    db.add(BriefAudit(brief_id=brief.id, reference=brief.reference, actor=actor, action=action,
                      payload_json=json.dumps(payload or {}, ensure_ascii=False, default=str)[:12000]))


def _serialize(b, admin=False):
    data = {
        'reference':b.reference,'request_type':b.request_type,'status':b.status,
        'name':b.customer_name,'email':b.customer_email,'phone':b.phone,
        'event_date':b.event_date.isoformat() if b.event_date else None,'guest_count':b.guest_count,
        'venue':b.venue,'budget':b.budget,'occasion':b.occasion,'colours':b.colours,
        'company':b.company,'quantity_scope':b.quantity_scope,'details':b.details,
        'quote_amount_kwd':float(b.quote_amount_kwd) if b.quote_amount_kwd is not None else None,
        'created_at':b.created_at.isoformat() if b.created_at else None,
        'updated_at':b.updated_at.isoformat() if b.updated_at else None,
        'cancelled_at':b.cancelled_at.isoformat() if b.cancelled_at else None,
        'shopify_draft_order_name':b.shopify_draft_order_name,
    }
    if admin:
        data.update({'customer_id':b.customer_id,'internal_note':b.internal_note,'cancellation_reason':b.cancellation_reason,
                     'shopify_draft_order_id':b.shopify_draft_order_id})
    return data


def _proxy_signature_ok(request: Request) -> bool:
    if ALLOW_UNSIGNED_PROXY: return True
    if not SHOPIFY_API_SECRET: return False
    supplied = request.query_params.get('signature','')
    if not supplied: return False
    # Shopify App Proxy canonicalization: group repeated keys with comma-separated
    # values, build key=value entries, sort the entries, then concatenate them.
    grouped: Dict[str, List[str]] = {}
    for k,v in request.query_params.multi_items():
        if k == 'signature': continue
        grouped.setdefault(k, []).append(v)
    canonical = ''.join(sorted(f"{k}={','.join(values)}" for k,values in grouped.items()))
    digest = hmac.new(SHOPIFY_API_SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, supplied)


def _proxy_identity(request: Request):
    if not _proxy_signature_ok(request):
        raise HTTPException(401, 'Invalid Shopify app proxy signature')
    shop = request.query_params.get('shop','').strip()
    if SHOPIFY_STORE_DOMAIN and shop and shop != SHOPIFY_STORE_DOMAIN:
        raise HTTPException(403, 'Wrong Shopify store')
    cid = request.query_params.get('logged_in_customer_id','').strip() or None
    return cid, shop


def _shopify_graphql(query: str, variables: Dict[str,Any]):
    if not (SHOPIFY_STORE_DOMAIN and SHOPIFY_ADMIN_TOKEN): return None
    url=f'https://{SHOPIFY_STORE_DOMAIN}/admin/api/{SHOPIFY_ADMIN_API_VERSION}/graphql.json'
    with httpx.Client(timeout=18) as c:
        r=c.post(url,headers={'X-Shopify-Access-Token':SHOPIFY_ADMIN_TOKEN,'Content-Type':'application/json'},json={'query':query,'variables':variables})
        r.raise_for_status(); data=r.json()
        if data.get('errors'): raise RuntimeError(str(data['errors']))
        return data.get('data')


def _customer_email(customer_id: Optional[str]) -> Optional[str]:
    if not customer_id: return None
    try:
        d=_shopify_graphql('query($id:ID!){customer(id:$id){email firstName lastName}}', {'id':f'gid://shopify/Customer/{customer_id}'})
        return ((d or {}).get('customer') or {}).get('email')
    except Exception as e:
        print('[PHILIA BRIEFS] customer lookup failed',repr(e),flush=True); return None


def _draft_attrs(b):
    pairs={
      'Philia Request Reference':b.reference,'Request Type':b.request_type,'Status':b.status,
      'Event / Required Date':b.event_date.isoformat() if b.event_date else '', 'Guest Count':b.guest_count or '',
      'Venue':b.venue or '', 'Budget':b.budget or '', 'Occasion':b.occasion or '', 'Colours':b.colours or '',
      'Company':b.company or '', 'Quantity / Scope':b.quantity_scope or '', 'Phone':b.phone or ''
    }
    return [{'key':str(k),'value':str(v)} for k,v in pairs.items() if str(v).strip()]


def _sync_draft_order(b):
    if not (SHOPIFY_STORE_DOMAIN and SHOPIFY_ADMIN_TOKEN): return
    try:
        title={'event':'Event Brief','bespoke':'Bespoke Quote','corporate':'Corporate Request'}.get(b.request_type,'Philia Request')
        tags=['PHILIA_REQUEST',f'TYPE_{b.request_type.upper()}',f'STATUS_{b.status.upper()}']
        inp={'email':b.customer_email,'note':b.details[:5000],'tags':tags,'customAttributes':_draft_attrs(b),
             'lineItems':[{'title':f'{title} — {b.reference}','quantity':1,'originalUnitPrice':'0.00'}]}
        if b.customer_id: inp['purchasingEntity']={'customerId':f'gid://shopify/Customer/{b.customer_id}'}
        if b.shopify_draft_order_id:
            q='mutation($id:ID!,$input:DraftOrderInput!){draftOrderUpdate(id:$id,input:$input){draftOrder{id name} userErrors{field message}}}'
            d=_shopify_graphql(q,{'id':b.shopify_draft_order_id,'input':inp}) or {}
            node=((d.get('draftOrderUpdate') or {}).get('draftOrder') or {})
        else:
            q='mutation($input:DraftOrderInput!){draftOrderCreate(input:$input){draftOrder{id name} userErrors{field message}}}'
            d=_shopify_graphql(q,{'input':inp}) or {}
            node=((d.get('draftOrderCreate') or {}).get('draftOrder') or {})
        if node:
            b.shopify_draft_order_id=node.get('id'); b.shopify_draft_order_name=node.get('name')
    except Exception as e:
        print('[PHILIA BRIEFS] draft order sync failed',repr(e),flush=True)


def _mail(to_email: str, subject: str, body: str):
    if not (SMTP_HOST and SMTP_FROM and to_email):
        print('[PHILIA BRIEFS] email skipped (SMTP not configured):',subject,flush=True); return
    try:
        msg=EmailMessage(); msg['From']=SMTP_FROM; msg['To']=to_email; msg['Subject']=subject
        msg.set_content(re.sub('<[^>]+>','',body)); msg.add_alternative(body,subtype='html')
        with smtplib.SMTP(SMTP_HOST,SMTP_PORT,timeout=20) as s:
            s.starttls()
            if SMTP_USER: s.login(SMTP_USER,SMTP_PASSWORD)
            s.send_message(msg)
    except Exception as e: print('[PHILIA BRIEFS] email failed',repr(e),flush=True)


def _brief_email_html(b, heading):
    fields=[('Reference',b.reference),('Type',b.request_type),('Status',b.status),('Name',b.customer_name),('Email',b.customer_email),('Phone',b.phone),('Date',b.event_date),('Guests',b.guest_count),('Venue',b.venue),('Budget',b.budget),('Occasion',b.occasion),('Colours',b.colours),('Company',b.company),('Quantity / scope',b.quantity_scope)]
    rows=''.join(f'<tr><td style="padding:6px 12px;color:#607074">{html.escape(str(k))}</td><td style="padding:6px 12px"><b>{html.escape(str(v))}</b></td></tr>' for k,v in fields if v not in (None,''))
    return f'<div style="font-family:Arial,sans-serif;color:#142326"><h2>{html.escape(heading)}</h2><table>{rows}</table><h3>Details</h3><p>{html.escape(b.details or "")}</p></div>'


def _admin_token(username):
    exp=int((_now()+timedelta(hours=12)).timestamp()); payload=f'{username}:{exp}'
    sig=hmac.new(ADMIN_SESSION_SECRET.encode(),payload.encode(),hashlib.sha256).hexdigest()
    return f'{payload}:{sig}'

def _admin_ok(request: Request):
    tok=request.cookies.get('philia_admin','')
    try:
        u,exp,sig=tok.rsplit(':',2); payload=f'{u}:{exp}'
        if u!=ADMIN_DASHBOARD_USER or int(exp)<int(_now().timestamp()): return False
        expected=hmac.new(ADMIN_SESSION_SECRET.encode(),payload.encode(),hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected,sig)
    except Exception:return False

def _require_admin(request):
    if not _admin_ok(request): raise HTTPException(401,'Admin login required')


@router.get('/briefs/health')
def briefs_health():
    return {'ok':DB_ERROR is None,'database': 'ready' if DB_ERROR is None else DB_ERROR,
            'shopify_sync':bool(SHOPIFY_STORE_DOMAIN and SHOPIFY_ADMIN_TOKEN),'smtp':bool(SMTP_HOST and SMTP_FROM),
            'proxy_verification':bool(SHOPIFY_API_SECRET)}

# These routes are mounted twice by main.py: direct /api/... and Shopify app-proxy /proxy/api/...
@router.post('/api/briefs')
def create_brief(payload: BriefCreate, request: Request):
    _require_db()
    customer_id=None
    # When called through app proxy, verify signed identity. Direct calls can only create a guest request.
    if request.url.path.startswith('/proxy/'):
        customer_id,_=_proxy_identity(request)
    kind=payload.request_type.strip().lower()
    if kind not in VALID_TYPES: raise HTTPException(422,'Unknown request type')
    email=_clean(payload.email,320)
    # When Shopify confirms a logged-in customer, prefer the verified customer
    # email over browser-submitted identity fields.
    if customer_id:
        verified_email=_customer_email(customer_id)
        if verified_email: email=verified_email
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$',email or ''): raise HTTPException(422,'Valid email required')
    token=secrets.token_urlsafe(32)
    with SessionLocal() as db:
        ref=_reference(kind)
        b=Brief(reference=ref,request_type=kind,status='submitted',customer_id=customer_id,
                customer_email=email,customer_name=_clean(payload.name,180) or 'Customer',phone=_clean(payload.phone,80),
                event_date=_date(payload.event_date),guest_count=payload.guest_count,venue=_clean(payload.venue,300),
                budget=_clean(payload.budget,180),occasion=_clean(payload.occasion,240),colours=_clean(payload.colours,300),
                company=_clean(payload.company,240),quantity_scope=_clean(payload.quantity_scope,300),
                details=_clean(payload.details,12000) or '', manage_token_hash=_hash_token(token),created_at=_now(),updated_at=_now())
        db.add(b); db.flush(); _audit(db,b,'customer','created',_serialize(b)); _sync_draft_order(b); db.commit(); db.refresh(b)
        merchant=PHILIA_NOTIFICATION_EMAIL
        if merchant: _mail(merchant,f'New Philia request {b.reference}',_brief_email_html(b,'New Philia request'))
        _mail(b.customer_email,f'We received your Philia request {b.reference}',_brief_email_html(b,'Your request has been received'))
        return {'ok':True,'brief':_serialize(b),'manage_token':token}


def _get_customer_records(request: Request, db):
    cid,_=_proxy_identity(request)
    if not cid: raise HTTPException(401,'Please sign in to manage your Philia requests.')
    email=_customer_email(cid)
    q=select(Brief).where(Brief.customer_id==cid)
    if email: q=select(Brief).where(or_(Brief.customer_id==cid,func.lower(Brief.customer_email)==email.lower()))
    rows=list(db.execute(q.order_by(Brief.created_at.desc())).scalars().all())
    if email:
        changed=False
        for b in rows:
            if not b.customer_id: b.customer_id=cid; changed=True
        if changed: db.commit()
    return cid,email,rows

@router.get('/api/briefs')
def list_briefs(request: Request):
    _require_db()
    if not request.url.path.startswith('/proxy/'):
        raise HTTPException(401,'Customer list requires Shopify app proxy.')
    with SessionLocal() as db:
        cid,email,rows=_get_customer_records(request,db)
        return {'ok':True,'customer_id':cid,'email':email,'briefs':[_serialize(x) for x in rows]}

@router.patch('/api/briefs/{reference}')
def update_brief(reference: str, payload: BriefUpdate, request: Request):
    _require_db()
    with SessionLocal() as db:
        b=db.execute(select(Brief).where(Brief.reference==reference)).scalar_one_or_none()
        if not b: raise HTTPException(404,'Request not found')
        authorized=False; actor='customer'
        if request.url.path.startswith('/proxy/'):
            cid,email,_=_get_customer_records(request,db)
            authorized=(b.customer_id==cid or (email and b.customer_email.lower()==email.lower()))
        else:
            tok=request.headers.get('X-Philia-Manage-Token',''); authorized=bool(tok and hmac.compare_digest(_hash_token(tok),b.manage_token_hash))
        if not authorized: raise HTTPException(403,'Not allowed')
        if b.status in {'cancelled','completed'}: raise HTTPException(409,'This request can no longer be edited.')
        changes={}
        for key in ['phone','venue','budget','occasion','colours','company','quantity_scope','details']:
            val=getattr(payload,key)
            if val is not None:
                setattr(b,key,_clean(val,12000 if key=='details' else 300)); changes[key]=val
        if payload.event_date is not None: b.event_date=_date(payload.event_date); changes['event_date']=payload.event_date
        if payload.guest_count is not None: b.guest_count=max(1,payload.guest_count); changes['guest_count']=payload.guest_count
        b.updated_at=_now(); b.last_customer_edit_at=_now()
        if b.status=='quoted': b.status='in_review'
        _audit(db,b,actor,'customer_updated',changes); _sync_draft_order(b); db.commit(); db.refresh(b)
        if PHILIA_NOTIFICATION_EMAIL: _mail(PHILIA_NOTIFICATION_EMAIL,f'Customer updated {b.reference}',_brief_email_html(b,'Customer updated a Philia request'))
        return {'ok':True,'brief':_serialize(b)}

@router.post('/api/briefs/{reference}/cancel')
def cancel_brief(reference: str, payload: CancelPayload, request: Request):
    _require_db()
    with SessionLocal() as db:
        b=db.execute(select(Brief).where(Brief.reference==reference)).scalar_one_or_none()
        if not b: raise HTTPException(404,'Request not found')
        authorized=False
        if request.url.path.startswith('/proxy/'):
            cid,email,_=_get_customer_records(request,db); authorized=(b.customer_id==cid or (email and b.customer_email.lower()==email.lower()))
        else:
            tok=request.headers.get('X-Philia-Manage-Token',''); authorized=bool(tok and hmac.compare_digest(_hash_token(tok),b.manage_token_hash))
        if not authorized: raise HTTPException(403,'Not allowed')
        if b.status=='cancelled': return {'ok':True,'brief':_serialize(b)}
        b.status='cancelled'; b.cancellation_reason=_clean(payload.reason,1500); b.cancelled_at=_now(); b.updated_at=_now()
        _audit(db,b,'customer','cancelled',{'reason':b.cancellation_reason}); _sync_draft_order(b); db.commit(); db.refresh(b)
        body=_brief_email_html(b,'Customer cancelled a Philia request')+f'<p><b>Cancellation reason:</b> {html.escape(b.cancellation_reason or "Not provided")}</p>'
        if PHILIA_NOTIFICATION_EMAIL: _mail(PHILIA_NOTIFICATION_EMAIL,f'CANCELLED — {b.reference}',body)
        _mail(b.customer_email,f'Cancellation confirmed — {b.reference}',_brief_email_html(b,'Your cancellation is confirmed'))
        return {'ok':True,'brief':_serialize(b)}

# ---- Admin dashboard ----
@router.post('/admin/api/login')
def admin_login(payload: AdminLogin):
    if not ADMIN_DASHBOARD_PASSWORD: raise HTTPException(503,'ADMIN_DASHBOARD_PASSWORD is not configured')
    if not (hmac.compare_digest(payload.username,ADMIN_DASHBOARD_USER) and hmac.compare_digest(payload.password,ADMIN_DASHBOARD_PASSWORD)):
        raise HTTPException(401,'Invalid login')
    resp=JSONResponse({'ok':True}); resp.set_cookie('philia_admin',_admin_token(payload.username),httponly=True,secure=True,samesite='lax',max_age=43200,path='/')
    return resp

@router.post('/admin/api/logout')
def admin_logout():
    resp=JSONResponse({'ok':True}); resp.delete_cookie('philia_admin',path='/'); return resp

@router.get('/admin/api/briefs')
def admin_briefs(request: Request, status: Optional[str]=None, q: Optional[str]=None):
    _require_admin(request); _require_db()
    with SessionLocal() as db:
        stmt=select(Brief)
        if status and status in VALID_STATUSES: stmt=stmt.where(Brief.status==status)
        if q:
            like=f'%{q.strip()}%'; stmt=stmt.where(or_(Brief.reference.ilike(like),Brief.customer_email.ilike(like),Brief.customer_name.ilike(like),Brief.venue.ilike(like),Brief.company.ilike(like)))
        rows=list(db.execute(stmt.order_by(Brief.created_at.desc()).limit(500)).scalars().all())
        now=date.today(); stats={}
        for st in VALID_STATUSES: stats[st]=db.execute(select(func.count()).select_from(Brief).where(Brief.status==st)).scalar_one()
        needs=db.execute(select(func.count()).select_from(Brief).where(Brief.status.in_(['submitted','in_review']),Brief.created_at < _now()-timedelta(hours=24))).scalar_one()
        upcoming=db.execute(select(func.count()).select_from(Brief).where(Brief.event_date>=now,Brief.event_date<=now+timedelta(days=14),Brief.status!='cancelled')).scalar_one()
        return {'ok':True,'stats':stats,'needs_response':needs,'upcoming_14_days':upcoming,'briefs':[_serialize(x,True) for x in rows]}

@router.get('/admin/api/briefs/{reference}/audit')
def admin_audit(reference: str, request: Request):
    _require_admin(request); _require_db()
    with SessionLocal() as db:
        rows=list(db.execute(select(BriefAudit).where(BriefAudit.reference==reference).order_by(BriefAudit.created_at.desc())).scalars().all())
        return {'ok':True,'audit':[{'actor':x.actor,'action':x.action,'payload':json.loads(x.payload_json or '{}'),'created_at':x.created_at.isoformat()} for x in rows]}

@router.patch('/admin/api/briefs/{reference}')
def admin_update(reference: str,payload: AdminUpdate,request: Request):
    _require_admin(request); _require_db()
    with SessionLocal() as db:
        b=db.execute(select(Brief).where(Brief.reference==reference)).scalar_one_or_none()
        if not b: raise HTTPException(404,'Not found')
        changes={}
        if payload.status:
            if payload.status not in VALID_STATUSES: raise HTTPException(422,'Invalid status')
            b.status=payload.status; changes['status']=payload.status
            if payload.status=='cancelled' and not b.cancelled_at: b.cancelled_at=_now()
        if payload.quote_amount_kwd is not None: b.quote_amount_kwd=payload.quote_amount_kwd; changes['quote_amount_kwd']=payload.quote_amount_kwd
        if payload.internal_note is not None: b.internal_note=_clean(payload.internal_note,10000); changes['internal_note']=payload.internal_note
        b.updated_at=_now(); _audit(db,b,'merchant','admin_updated',changes); _sync_draft_order(b); db.commit(); db.refresh(b)
        if 'status' in changes or 'quote_amount_kwd' in changes:
            _mail(b.customer_email,f'Update on your Philia request {b.reference}',_brief_email_html(b,'Your Philia request has been updated'))
        return {'ok':True,'brief':_serialize(b,True)}

@router.get('/admin/api/export.csv')
def admin_export(request: Request):
    _require_admin(request); _require_db()
    with SessionLocal() as db:
        rows=list(db.execute(select(Brief).order_by(Brief.created_at.desc())).scalars().all())
        s=io.StringIO(); w=csv.writer(s); w.writerow(['reference','type','status','name','email','phone','date','guests','venue','budget','company','created_at','updated_at'])
        for b in rows: w.writerow([b.reference,b.request_type,b.status,b.customer_name,b.customer_email,b.phone,b.event_date,b.guest_count,b.venue,b.budget,b.company,b.created_at,b.updated_at])
        return StreamingResponse(iter([s.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=philia-requests.csv'})

@router.post('/cron/brief-summary')
def cron_summary(request: Request):
    if not CRON_SECRET or request.headers.get('X-Cron-Secret')!=CRON_SECRET: raise HTTPException(401,'Unauthorized')
    _require_db()
    with SessionLocal() as db:
        old=list(db.execute(select(Brief).where(Brief.status.in_(['submitted','in_review']),Brief.created_at<_now()-timedelta(hours=24))).scalars().all())
        upcoming=list(db.execute(select(Brief).where(Brief.event_date>=date.today(),Brief.event_date<=date.today()+timedelta(days=7),Brief.status!='cancelled')).scalars().all())
        if PHILIA_NOTIFICATION_EMAIL and (old or upcoming):
            body=f'<h2>Philia request summary</h2><p><b>{len(old)}</b> requests need a response.</p><p><b>{len(upcoming)}</b> events are within 7 days.</p>'
            _mail(PHILIA_NOTIFICATION_EMAIL,'Philia daily request summary',body)
        return {'ok':True,'needs_response':len(old),'upcoming_7_days':len(upcoming)}

ADMIN_HTML = r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Philia Request Command Center</title><style>
:root{--ink:#082f38;--ink2:#061f26;--gold:#bfae73;--cream:#f4eee5;--muted:#8aa0a4}*{box-sizing:border-box}body{margin:0;font-family:Inter,Arial,sans-serif;background:#071b20;color:var(--cream)}button,input,select,textarea{font:inherit}.login{min-height:100vh;display:grid;place-items:center}.box{width:min(420px,92vw);background:#0b3038;border:1px solid #234952;padding:28px}.box h1{margin-top:0}.box input,.toolbar input,.toolbar select,.drawer input,.drawer textarea,.drawer select{width:100%;padding:12px;background:#0a252b;border:1px solid #34515a;color:#fff}.btn{border:0;background:var(--gold);color:#10262b;padding:11px 15px;font-weight:700;cursor:pointer}.app{display:none}.top{position:sticky;top:0;z-index:5;background:rgba(7,27,32,.94);backdrop-filter:blur(16px);padding:18px 24px;border-bottom:1px solid #24434a;display:flex;align-items:center;justify-content:space-between}.top h1{font-size:18px;margin:0}.wrap{padding:24px;max-width:1500px;margin:auto}.stats{display:grid;grid-template-columns:repeat(6,minmax(130px,1fr));gap:10px;margin-bottom:18px}.stat{background:#0b2b32;border:1px solid #21434b;padding:16px}.stat b{font-size:25px;display:block;color:var(--gold)}.toolbar{display:grid;grid-template-columns:2fr 1fr auto;gap:9px;margin-bottom:14px}.table{background:#0a252b;border:1px solid #21434b;overflow:auto}.row{display:grid;grid-template-columns:150px 110px 130px 1.2fr 1.4fr 120px 130px;gap:10px;align-items:center;padding:13px 14px;border-bottom:1px solid #183941;min-width:1000px}.row.head{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em}.row.item{cursor:pointer}.row.item:hover{background:#0e343c}.status{display:inline-flex;padding:6px 9px;border:1px solid #456168;font-size:11px;text-transform:uppercase}.drawer{position:fixed;right:0;top:0;width:min(560px,100%);height:100vh;background:#09272e;border-left:1px solid #31515a;z-index:20;transform:translateX(100%);transition:.25s;padding:24px;overflow:auto}.drawer.open{transform:none}.drawer h2{margin:0 0 5px}.kv{display:grid;grid-template-columns:130px 1fr;gap:7px;border-bottom:1px solid #214149;padding:9px 0}.kv span{color:var(--muted)}.actions{display:grid;gap:10px;margin-top:18px}.audit{margin-top:20px}.audit div{border-left:2px solid var(--gold);padding:7px 10px;margin:8px 0;background:#0b3038;font-size:12px}.close{float:right;background:none;border:0;color:white;font-size:24px}@media(max-width:900px){.stats{grid-template-columns:repeat(2,1fr)}.toolbar{grid-template-columns:1fr}.wrap{padding:14px}}
</style></head><body><div class="login" id="login"><form class="box" id="loginForm"><h1>Philia Request Command Center</h1><p>Owner dashboard for event, bespoke and corporate requests.</p><input id="user" placeholder="Username" value="philia" required><br><br><input id="pass" type="password" placeholder="Password" required><br><br><button class="btn">Sign in</button><p id="loginMsg"></p></form></div><div class="app" id="app"><header class="top"><h1>PHILIA · Request Command Center</h1><div><a class="btn" href="/admin/api/export.csv" style="text-decoration:none">Export CSV</a> <button class="btn" id="logout">Logout</button></div></header><main class="wrap"><div class="stats" id="stats"></div><div class="toolbar"><input id="search" placeholder="Search reference, customer, email, venue, company"><select id="status"><option value="">All statuses</option><option>submitted</option><option>in_review</option><option>quoted</option><option>confirmed</option><option>completed</option><option>cancelled</option></select><button class="btn" id="refresh">Refresh</button></div><div class="table"><div class="row head"><div>Reference</div><div>Type</div><div>Status</div><div>Customer</div><div>Venue / company</div><div>Date</div><div>Created</div></div><div id="rows"></div></div></main></div><aside class="drawer" id="drawer"><button class="close" id="close">×</button><div id="detail"></div></aside><script>
const $=s=>document.querySelector(s);let data=[];async function api(u,o={}){const r=await fetch(u,{headers:{'Content-Type':'application/json'},...o});if(r.status===401){$('#login').style.display='grid';$('#app').style.display='none';throw Error('login')};const j=await r.json();if(!r.ok)throw Error(j.detail||'Request failed');return j}async function load(){let u='/admin/api/briefs?';if($('#status').value)u+='status='+encodeURIComponent($('#status').value)+'&';if($('#search').value)u+='q='+encodeURIComponent($('#search').value);const j=await api(u);data=j.briefs;$('#stats').innerHTML=[['Submitted',j.stats.submitted],['In review',j.stats.in_review],['Quoted',j.stats.quoted],['Confirmed',j.stats.confirmed],['Needs response',j.needs_response],['Next 14 days',j.upcoming_14_days]].map(x=>`<div class=stat><span>${x[0]}</span><b>${x[1]}</b></div>`).join('');$('#rows').innerHTML=data.map((b,i)=>`<div class="row item" data-i=${i}><div>${b.reference}</div><div>${b.request_type}</div><div><span class=status>${b.status}</span></div><div>${esc(b.name)}<br><small>${esc(b.email)}</small></div><div>${esc(b.venue||b.company||'—')}</div><div>${b.event_date||'—'}</div><div>${new Date(b.created_at).toLocaleDateString()}</div></div>`).join('');document.querySelectorAll('.row.item').forEach(x=>x.onclick=()=>openBrief(data[+x.dataset.i]))}function esc(v){return String(v||'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}async function openBrief(b){const aud=await api('/admin/api/briefs/'+b.reference+'/audit');$('#detail').innerHTML=`<h2>${b.reference}</h2><p>${b.request_type} · ${b.status}</p>${Object.entries({Name:b.name,Email:b.email,Phone:b.phone,Date:b.event_date,Guests:b.guest_count,Venue:b.venue,Budget:b.budget,Occasion:b.occasion,Colours:b.colours,Company:b.company,'Quantity / scope':b.quantity_scope,'Shopify draft':b.shopify_draft_order_name}).filter(x=>x[1]).map(x=>`<div class=kv><span>${x[0]}</span><b>${esc(x[1])}</b></div>`).join('')}<h3>Customer details</h3><p>${esc(b.details)}</p><div class=actions><label>Status<select id=editStatus>${['submitted','in_review','quoted','confirmed','completed','cancelled'].map(s=>`<option ${s==b.status?'selected':''}>${s}</option>`).join('')}</select></label><label>Quote amount KWD<input id=quote type=number step=.001 value="${b.quote_amount_kwd??''}"></label><label>Internal note<textarea id=note rows=5>${esc(b.internal_note||'')}</textarea></label><button class=btn id=save>Save update</button></div><div class=audit><h3>Timeline</h3>${aud.audit.map(a=>`<div><b>${a.action}</b> · ${a.actor}<br><small>${new Date(a.created_at).toLocaleString()}</small></div>`).join('')}</div>`;$('#drawer').classList.add('open');$('#save').onclick=async()=>{await api('/admin/api/briefs/'+b.reference,{method:'PATCH',body:JSON.stringify({status:$('#editStatus').value,quote_amount_kwd:$('#quote').value?+$('#quote').value:null,internal_note:$('#note').value})});await load();$('#drawer').classList.remove('open')}}$('#loginForm').onsubmit=async e=>{e.preventDefault();try{await api('/admin/api/login',{method:'POST',body:JSON.stringify({username:$('#user').value,password:$('#pass').value})});$('#login').style.display='none';$('#app').style.display='block';load()}catch(err){$('#loginMsg').textContent='Login failed'}};$('#refresh').onclick=load;$('#status').onchange=load;let t;$('#search').oninput=()=>{clearTimeout(t);t=setTimeout(load,350)};$('#close').onclick=()=>$('#drawer').classList.remove('open');$('#logout').onclick=async()=>{await api('/admin/api/logout',{method:'POST'});location.reload()};(async()=>{try{await load();$('#login').style.display='none';$('#app').style.display='block'}catch(e){}})();
</script></body></html>'''

@router.get('/admin',response_class=HTMLResponse)
def admin_page(): return HTMLResponse(ADMIN_HTML,headers={'Content-Security-Policy':"frame-ancestors https://admin.shopify.com https://*.myshopify.com"})
@router.get('/admin/briefs',response_class=HTMLResponse)
def admin_page2(): return HTMLResponse(ADMIN_HTML,headers={'Content-Security-Policy':"frame-ancestors https://admin.shopify.com https://*.myshopify.com"})
