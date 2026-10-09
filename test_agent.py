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
  if 'مبروك' in last:return Response({'reply':'مبروك على الفرح!','actions':[{'label':'جهّز تفاصيل المناسبة','type':'quote-update','patch':{'form':'events','guest_count':'120'}}], 'auto_action':None,'context':{'occasion':'wedding'}})
  if 'حلو' in last:return Response({'reply':'اختيار حلو!','actions':[{'label':'أضف للسلة','type':'add','value':'velvet-rose-bouquet'}],'auto_action':{'type':'add','value':'velvet-rose-bouquet'},'context':{}})
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
r=cli.get('/health');check(r.status_code==200,'health 200');check(r.json()['configured_model']=='openai/gpt-oss-20b','ALF default model')
check(m._models()[:2]==['openai/gpt-oss-20b','openai/gpt-oss-120b'],'ALF fallbacks')
msg=lambda v:{'role':'user','content':v}
r=cli.post('/api/chat',json={'messages':[msg('هلا')]});check(r.status_code==200,'chat status');check(r.json()['reply']=='هلا وغلا!','chat reply');check(len(FakeCompletions.calls)==1,'single Groq call');check(FakeCompletions.calls[-1]['max_completion_tokens']==1400,'ALF max tokens');check(FakeCompletions.calls[-1]['reasoning_effort']=='low','ALF reasoning')
FakeCompletions.calls.clear();r=cli.post('/api/chat',json={'messages':[msg('مبروك')], 'enquiry':[{'handle':'velvet-rose-bouquet','price_kwd':38}]});check(r.status_code==200,'wedding reply status');check(r.json()['context'].get('occasion')=='wedding','memory');check(len(FakeCompletions.calls)==2,'ALF second quote extraction model call');check(r.json()['actions'][0]['patch']['form']=='events','correct form selection');check(r.json()['actions'][0]['patch']['event_date']=='2026-12-05','confirmed events field extraction')
FakeCompletions.calls.clear();r=cli.post('/api/chat',json={'messages':[msg('حلوة دي')]});check(r.json()['auto_action'] is None,'compliment never auto cart');check(r.json()['actions'][0]['type']=='add','user can click add');check(len(FakeCompletions.calls)==1,'single call compliment')
check(m._sanitize_action({'type':'navigate','value':'javascript:alert(1)'}) is None,'malicious navigation rejected')
check(m._sanitize_action({'type':'navigate','value':'/pages/events-weddings'}) is not None,'valid route')
check(m._sanitize_action({'type':'navigate','value':'//evil.test'}) is None,'external blocked')
check(m._sanitize_action({'type':'add','value':'../../'} ) is None,'malicious product handle rejected')
check(m._sanitize_action({'type':'quote-update','patch':{'form':'events','guest_count':'120','custom_unknown':'leak'}})['patch']=={'form':'events','guest_count':'120'},'form allowlist')
check(m._sanitize_action({'type':'quote-update','patch':{'form':'events','custom_unknown':'anything'}}) is None,'no empty form patch')
check(m._sanitize_action({'type':'quote-update','patch':{'form':'uniforms','quantity':'80'}}) is None,'ALF-only quote form blocked')
print(f'BACKEND PASS: {passed}/{passed} assertions; ALF-equivalent model selection, completion parameters, history, action JSON, confirmed Philia forms, safe cart consent')
