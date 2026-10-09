import os,sys,types,importlib.util,json
from pathlib import Path
os.environ['GROQ_API_KEY']='TEST_ONLY_FAKE_KEY'
class Response:
 def __init__(self,content):self.choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=json.dumps(content,ensure_ascii=False)))]
class FakeCompletions:
 calls=[]
 def create(self,**kwargs):
  FakeCompletions.calls.append(kwargs)
  if any(m['role']=='system' and 'Extract ONLY details' in m['content'] for m in kwargs['messages']):
   return Response({'patch':{'form':'events','event_date':'2026-12-05','guest_count':'120'}})
  last=next((m['content'] for m in kwargs['messages'][::-1] if m['role']=='user'),'')
  if 'وريني المنتجات' in last:
   return Response({'reply':'أكيد، دي اختيارات حقيقية من المتجر.','actions':[
    {'label':'Celebration Money Envelope','type':'navigate','value':'/products/celebration-money-envelope'},
    {'label':'Blush Garden Vase','type':'navigate','value':'/products/blush-garden-vase'}], 'auto_action':None,'context':{'recommendations':['celebration-money-envelope','blush-garden-vase']}})
  if 'مبروك' in last:return Response({'reply':'مبروك على الفرح!','actions':[{'label':'جهّز تفاصيل المناسبة','type':'quote-update','patch':{'form':'events','guest_count':'120'}}], 'auto_action':None,'context':{'occasion':'wedding'}})
  if 'حلو' in last:return Response({'reply':'تمت إضافة المنتج للسلة.','actions':[{'label':'أضف للسلة','type':'add','value':'velvet-rose-bouquet'}],'auto_action':{'type':'add','value':'velvet-rose-bouquet'},'context':{'selected_product':'velvet-rose-bouquet'}})
  if last.strip() in {'اه','ايوه','yes'}:
   return Response({'reply':'تمت إضافة المنتج للسلة.','actions':[],'auto_action':{'type':'add','value':'celebration-money-envelope'},'context':{'selected_product':'celebration-money-envelope'}})
  if 'ضيفها' in last:return Response({'reply':'تمت إضافة المنتج للسلة.','actions':[],'auto_action':{'type':'add','value':'celebration-money-envelope'},'context':{'selected_product':'celebration-money-envelope'}})
  if 'جهز' in last:return Response({'reply':'أقدر أجهز البريف للمراجعة.','actions':[],'auto_action':None,'context':{}})
  return Response({'reply':'هلا وغلا!','actions':[],'auto_action':None,'context':{}})
class FakeGroq:
 def __init__(self,**kw):self.chat=types.SimpleNamespace(completions=FakeCompletions())
sys.modules['groq']=types.SimpleNamespace(Groq=FakeGroq)
file=str(Path(__file__).with_name('main.py'))
spec=importlib.util.spec_from_file_location('philia_alf_main',file);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
from fastapi.testclient import TestClient
cli=TestClient(m.app)
passed=0
def check(ok,reason):
 global passed
 assert ok,reason
 passed+=1
CAT=[
 {'name':'Velvet Rose Bouquet','handle':'velvet-rose-bouquet','price_kwd':38,'route':'/products/velvet-rose-bouquet','available':True},
 {'name':'Celebration Money Envelope','handle':'celebration-money-envelope','price_kwd':20,'route':'/products/celebration-money-envelope','available':True},
 {'name':'Blush Garden Vase','handle':'blush-garden-vase','price_kwd':35,'route':'/products/blush-garden-vase','available':True},
]
msg=lambda role,v:{'role':role,'content':v}
r=cli.get('/health');check(r.status_code==200,'health 200');check(r.json()['configured_model']=='openai/gpt-oss-20b','ALF default model')
check(m._models()[:2]==['openai/gpt-oss-20b','openai/gpt-oss-120b'],'ALF fallbacks')
FakeCompletions.calls.clear();r=cli.post('/api/chat',json={'messages':[msg('user','هلا')],'enquiry':CAT});check(r.status_code==200,'chat status');check(r.json()['reply']=='هلا وغلا!','chat reply');check(len(FakeCompletions.calls)==1,'single Groq call');check(FakeCompletions.calls[-1]['max_completion_tokens']==1400,'ALF max tokens');check(FakeCompletions.calls[-1]['reasoning_effort']=='low','ALF reasoning')
conversation=m._conversation(m.ChatPayload(messages=[m.Message(role='user',content='هلا')],enquiry=CAT));check('storefront_products' in conversation[1]['content'],'live product snapshot in ALF storefront state')
FakeCompletions.calls.clear();r=cli.post('/api/chat',json={'messages':[msg('user','وريني المنتجات')], 'enquiry':CAT});data=r.json();check(len(data['actions'])==2,'product browse returns real actions');check(data['actions'][0]['value']=='/products/celebration-money-envelope','real product route preserved')
FakeCompletions.calls.clear();r=cli.post('/api/chat',json={'messages':[msg('user','مبروك')], 'enquiry':CAT});check(r.status_code==200,'wedding reply status');check(r.json()['context'].get('occasion')=='wedding','memory');check(len(FakeCompletions.calls)==2,'ALF second quote extraction model call');check(r.json()['actions'][0]['patch']['form']=='events','correct form selection');check(r.json()['actions'][0]['patch']['event_date']=='2026-12-05','confirmed events field extraction')
FakeCompletions.calls.clear();r=cli.post('/api/chat',json={'messages':[msg('user','حلوة دي')],'enquiry':CAT,'locale':'ar'});data=r.json();check(data['auto_action'] is None,'compliment never auto cart');check(data['actions'][0]['type']=='add','compliment keeps clickable add');check('تمت إضافة' not in data['reply'],'false success claim removed');check(data['context'].get('selected_product')=='velvet-rose-bouquet','selected real product retained');check(len(FakeCompletions.calls)==1,'single call compliment')
# Yes only confirms add if previous assistant explicitly asked.
FakeCompletions.calls.clear();r=cli.post('/api/chat',json={'messages':[msg('assistant','تحب أضيف Celebration Money Envelope للسلة؟'),msg('user','اه')],'enquiry':CAT,'locale':'ar'});data=r.json();check(data['auto_action']['type']=='add','yes after explicit add question permits auto add');check('تمت إضافة' not in data['reply'],'pre-execution success rewritten');check('هضيفه' in data['reply'],'future-tense verified-action handoff')
FakeCompletions.calls.clear();r=cli.post('/api/chat',json={'messages':[msg('user','اه')],'enquiry':CAT,'locale':'ar'});check(r.json()['auto_action'] is None,'standalone yes cannot mutate cart')
FakeCompletions.calls.clear();r=cli.post('/api/chat',json={'messages':[msg('user','ضيفها')],'enquiry':CAT,'locale':'ar'});check(r.json()['auto_action']['value']=='celebration-money-envelope','explicit add preserved')
# Hallucinated product handle rejected even if model attempts it.
raw={'reply':'تمام','actions':[{'label':'Add fake','type':'add','value':'fake-product'}],'auto_action':{'type':'add','value':'fake-product'},'context':{'selected_product':'fake-product'}}
validated=m._finalize_result(m._sanitize_result(raw),m.ChatPayload(messages=[m.Message(role='user',content='ضيفها')],enquiry=CAT,locale='ar'))
check(validated['actions']==[],'unknown add handle rejected');check(validated['auto_action'] is None,'unknown auto add rejected');check('selected_product' not in validated['context'],'unknown selected product removed')
check(m._sanitize_action({'type':'navigate','value':'javascript:alert(1)'}) is None,'malicious navigation rejected')
check(m._sanitize_action({'type':'navigate','value':'/pages/events-weddings'}) is not None,'valid route')
check(m._sanitize_action({'type':'navigate','value':'//evil.test'}) is None,'external blocked')
check(m._sanitize_action({'type':'add','value':'../../'} ) is None,'malicious product handle rejected')
check(m._sanitize_action({'type':'quote-update','patch':{'form':'events','guest_count':'120','custom_unknown':'leak'}})['patch']=={'form':'events','guest_count':'120'},'form allowlist')
check(m._sanitize_action({'type':'quote-update','patch':{'form':'events','custom_unknown':'anything'}}) is None,'no empty form patch')
check(m._sanitize_action({'type':'quote-update','patch':{'form':'uniforms','quantity':'80'}}) is None,'ALF-only quote form blocked')
print(f'BACKEND PASS: {passed}/{passed} assertions; ALF engine + live Philia catalog + real cart consent/action contract')
