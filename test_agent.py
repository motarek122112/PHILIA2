"""Offline contract tests: real backend code, fake Groq transport and Shopify fixture.
These are not claims of live Groq or real Shopify cart execution.
"""
import sys
import types
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

# Library is not installed in offline build environment. Inject a minimal
# transport module strictly for tests; Render uses real package in requirements.
if 'groq' not in sys.modules:
    fake_groq = types.ModuleType('groq')
    fake_groq.Groq = type('Groq', (), {})
    sys.modules['groq'] = fake_groq
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as m


CAT = {'products': [
    {'handle': 'velvet-money-envelope', 'title': 'Velvet Money Envelope', 'description': 'Elegant envelope',
     'available': True, 'price': '20.0 KWD', 'image': 'https://example.org/velvet.jpg', 'tags': ['gift'],
     'product_type': 'Gifts', 'variants': [{'id':'gid://shopify/ProductVariant/123', 'title':'Default Title',
                                        'available': True, 'price':'20.0 KWD','options':[]}]},
    {'handle': 'gold-ember-mabkhara', 'title': 'Gold Ember Mabkhara', 'description': 'Gold incense holder',
     'available': True, 'price': '32.0 KWD', 'image': 'https://example.org/mabkhara.jpg', 'tags': ['wedding'],
     'product_type': 'Gifts', 'variants': [{'id':'gid://shopify/ProductVariant/987', 'title':'Default Title',
                                        'available': True, 'price':'32.0 KWD','options':[]}]}
], 'collections': [{'handle':'money-envelopes','title':'Money Envelopes'},
                  {'handle':'mabakhir','title':'Mabakhir'}]}


def payload(*messages, context=None):
    return m.ChatPayload(messages=[m.Message(role=('user' if i%2==0 else 'assistant'), content=text)
                                  for i,text in enumerate(messages)], context=context or {})


def user(message, context=None, history=None):
    all_messages = [m.Message(role=r, content=c) for r,c in (history or [])] + [m.Message(role='user',content=message)]
    return m.ChatPayload(messages=all_messages, context=context or {})


def test_alfs_style_contract():
    p = user('هلا')
    conversation = m._conversation(p, CAT, [])
    assert conversation[0]['role']=='system'
    assert conversation[-1]['content']=='هلا'
    assert 'PHILIA AI' in conversation[0]['content']
    assert 'ALF Uniforms' not in conversation[0]['content']
    assert m.PRIMARY_MODEL in ('openai/gpt-oss-20b','openai/gpt-oss-120b')


def test_no_catalog_wait_for_greeting():
    assert not m._needs_catalog('هلا', {})
    assert not m._needs_catalog('عامل ايه', {})
    assert m._needs_catalog('عايز ورد', {})


def test_product_context_across_short_followup():
    p=user('وريني',history=[('user','عايز ورد'),('assistant','لأي مناسبة؟')])
    content=m._site_context(CAT, [], p)
    # Direct retrieval hint uses previous relevant user messages.
    assert 'velvet-money-envelope' in content


def test_real_handle_cards_only():
    p=user('وريني')
    raw={'reply':'هذي اختياراتنا','actions':[],'products':[{'handle':'velvet-money-envelope'},
                                 {'handle':'made-up-product'}], 'context':{'recommendations':['made-up-product']}}
    v=m._sanitize_result(raw,CAT,p)
    assert [x['handle'] for x in v['products']]==['velvet-money-envelope']
    assert v['context']['recommendations']==['velvet-money-envelope']
    assert v['products'][0]['price']=='20.0 KWD'


def test_unrequested_cart_action_downgraded():
    p=user('حلوة الفيلفيت موني دي')
    raw={'reply':'تمت إضافة Velvet Money Envelope للسلة','actions':[],
         'auto_action':{'type':'add_to_cart','handle':'velvet-money-envelope','quantity':1},'products':[]}
    got=m._sanitize_result(raw,CAT,p)
    assert got['actions'][0]['auto'] is False
    assert 'تمت إضافة' not in got['reply']


def test_explicit_add_is_auto_but_never_claim_success():
    p=user('ضيفها')
    raw={'reply':'تمت إضافة Velvet Money Envelope للسلة', 'actions':[],
         'auto_action':{'type':'add_to_cart','handle':'velvet-money-envelope','quantity':1}}
    got=m._sanitize_result(raw,CAT,p)
    assert got['actions'][0]['auto'] is True
    assert 'تمت إضافة' not in got['reply']
    assert got['actions'][0]['handle']=='velvet-money-envelope'


def test_vague_execute_order_does_not_grant_consent():
    p=user('تنفيذ الطلب')
    got=m._sanitize_result({'reply':'تمام', 'auto_action':{'type':'add_to_cart','handle':'velvet-money-envelope'}},CAT,p)
    assert got['auto_action']['auto'] is False


def test_auto_route_verified():
    p=user('وديني للمنتجات')
    x=m._sanitize_result({'reply':'تفضل', 'auto_action':{'type':'navigate','value':'/collections/all'}},CAT,p)
    assert x['actions'][0]['url']=='/collections/all'
    bad=m._sanitize_result({'reply':'تمام','auto_action':{'type':'navigate','value':'https://evil.example'}},CAT,p)
    assert bad['actions']==[]


def test_real_variants_and_cart_keys_only():
    p=user('ضيفه')
    raw={'reply':'أختار لك', 'auto_action':{'type':'add_to_cart','handle':'velvet-money-envelope',
                                       'variant_id':'gid://shopify/ProductVariant/999'}}
    assert m._sanitize_result(raw,CAT,p)['actions']==[]
    assert m._sanitize_result({'reply':'x','actions':[{'type':'remove_from_cart','line_key':'fake'}]},CAT,p)['actions']==[]


def test_form_map_exact_and_no_autosubmit():
    p=user('جهزلي بيانات زفافي')
    raw={'reply':'نقدر نعبّي البيانات', 'auto_action':{'type':'form_patch','form':'events','fields':
                {'event_date':'2026-12-02','guest_count':'100','bad':'x','budget':'300'}}, 'actions':[]}
    v=m._sanitize_result(raw,CAT,p)
    assert v['actions'][0]['auto'] is False
    assert v['actions'][0]['fields']=={'event_date':'2026-12-02','guest_count':'100','budget':'300'}


def test_english_and_arabic_memory():
    p=user('اسمي أحمد')
    v=m._sanitize_result({'reply':'تشرفت يا أحمد','context':{'user_name':'أحمد','sneaky_key':'bad'}}, CAT, p)
    assert v['context']=={'user_name':'أحمد'}
    assert m._extract_json('```json\n{"reply":"Hello","actions":[]}\n```')['reply']=='Hello'


def test_cache_hit_single_refresh():
    x=m.TTLCache(lambda: {'products':[1]}, ttl=300)
    x.value={'products':[2]}; x.at=m.time.monotonic()
    data,status=x.get(wait=True)
    assert data['products']==[2] and status=='hit'


def test_single_llm_for_normal_message(monkeypatch):
    monkeypatch.setattr(m,'GROQ_API_KEY','test-key')
    monkeypatch.setattr(m.CATALOG,'value',CAT)
    monkeypatch.setattr(m.CATALOG,'at',m.time.monotonic())
    monkeypatch.setattr(m.PAGES,'value',[])
    monkeypatch.setattr(m.PAGES,'at',m.time.monotonic())
    calls=[]
    class Client:
        def __init__(self,**_kwargs):
            self.chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def create(self,**kwargs):
            calls.append(kwargs)
            response=json.dumps({'reply':'أهلين!','actions':[],'auto_action':None,'context':{},'products':[]})
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=response))],usage=None)
    monkeypatch.setattr(m,'Groq',Client)
    result=m._chat_sync(user('هلا'))
    assert result['reply']=='أهلين!'
    assert len(calls)==1
    assert calls[0]['response_format']=={'type':'json_object'}
    assert calls[0]['model']=='openai/gpt-oss-20b'


def test_second_llm_only_on_form_autofill(monkeypatch):
    monkeypatch.setattr(m,'GROQ_API_KEY','test-key')
    monkeypatch.setattr(m.CATALOG,'value',CAT); monkeypatch.setattr(m.CATALOG,'at',m.time.monotonic())
    monkeypatch.setattr(m.PAGES,'value',[]); monkeypatch.setattr(m.PAGES,'at',m.time.monotonic())
    calls=[]
    class Client:
        def __init__(self,**_kwargs):self.chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def create(self,**kwargs):
            calls.append(kwargs)
            value=({'reply':'حضّرت لك النموذج','actions':[{'type':'form_patch','form':'events',
                    'fields':{'event_date':'2026-12-02'}}], 'context':{}}
                   if len(calls)==1 else {'fields':{'guest_count':'100'}})
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)))],usage=None)
    monkeypatch.setattr(m,'Groq',Client)
    result=m._chat_sync(user('جهزلي نموذج الزفاف'))
    assert len(calls)==2
    assert result['actions'][0]['fields']=={'event_date':'2026-12-02','guest_count':'100'}


def test_fail_429_is_not_retried(monkeypatch):
    monkeypatch.setattr(m,'GROQ_API_KEY','test-key')
    monkeypatch.setattr(m.CATALOG,'value',CAT); monkeypatch.setattr(m.CATALOG,'at',m.time.monotonic())
    monkeypatch.setattr(m.PAGES,'value',[]); monkeypatch.setattr(m.PAGES,'at',m.time.monotonic())
    called=[]
    class Throttle(Exception):status_code=429
    class Client:
        def __init__(self,**_kw):self.chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def create(self,**kwargs): called.append(1); raise Throttle()
    monkeypatch.setattr(m,'Groq',Client)
    with pytest.raises(Throttle):m._chat_sync(user('هلا'))
    assert len(called)==1


def test_official_price_repair():
    assert m._repair_price_claims('Gold Ember Mabkhara — 30 KWD', CAT) == 'Gold Ember Mabkhara — 32.0 KWD'
    assert m._repair_price_claims('Gold Ember Mabkhara — 32.0 KWD', CAT) == 'Gold Ember Mabkhara — 32.0 KWD'


def test_exact_routes_and_form_fields():
    assert m.FORMS['contact']['fields']==['name','email','body']
    assert m.FORMS['bespoke']['fields']==['occasion','budget','required_date','colours','body']
    assert '/pages/events-weddings' in m.ROUTES
    assert '/pages/bespoke-orders' in m.ROUTES


def test_http_health_and_json_chat(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(m,'GROQ_API_KEY','test-key')
    monkeypatch.setattr(m.CATALOG,'value',CAT); monkeypatch.setattr(m.CATALOG,'at',m.time.monotonic())
    monkeypatch.setattr(m.PAGES,'value',[]); monkeypatch.setattr(m.PAGES,'at',m.time.monotonic())
    class Client:
        def __init__(self,**_kwargs):self.chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def create(self,**kwargs):
            value={'reply':'هلا والله','actions':[],'auto_action':None,'context':{'user_name':'أحمد'},'products':[]}
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)))],usage=None)
    monkeypatch.setattr(m,'Groq',Client)
    with TestClient(m.app) as app:
        h=app.get('/health')
        assert h.status_code==200 and h.json()['response_format']=='ALF-style-JSON'
        response=app.post('/api/chat',json={'messages':[{'role':'user','content':'هلا'}], 'context':{}})
        assert response.status_code==200
        data=response.json()
        assert data['reply']=='هلا والله'
        assert data['context']=={'user_name':'أحمد'}
        assert isinstance(data['actions'],list)
        assert response.headers['content-type'].startswith('application/json')


def test_http_error_exposes_no_keys(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(m,'GROQ_API_KEY','test-secret-key')
    class ConnectionBroken(Exception):pass
    monkeypatch.setattr(m,'_chat_sync',lambda payload: (_ for _ in ()).throw(ConnectionBroken('test-secret-key')))
    with TestClient(m.app) as app:
        response=app.post('/api/chat',json={'messages':[{'role':'user','content':'hello'}]})
        assert response.status_code==503
        assert response.json()['code']=='AI_CONNECTION_FAILED'
        assert 'test-secret-key' not in response.text
