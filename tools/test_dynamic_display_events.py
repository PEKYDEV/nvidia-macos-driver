#!/usr/bin/env python3
"""Execute real callback, kick, worker and boot enumeration against an NVKMS boundary fake.
Break caught: discarding event handle=1 when getDisplays only lists physical handles.
No kernel/driver operation is performed by this userspace fixture.
"""
import argparse,ast,json,pathlib,subprocess,tempfile
pa=argparse.ArgumentParser();pa.add_argument('--source',type=pathlib.Path,required=True);pa.add_argument('--vendor',type=pathlib.Path,required=True);pa.add_argument('--output',type=pathlib.Path,required=True);pa.add_argument('--case');a=pa.parse_args()
s=a.source.read_text()
def method(text,marker):
 start=text.index(marker);opening=text.index('{',start);depth=0
 for pos in range(opening,len(text)):
  if text[pos]=='{':depth+=1
  elif text[pos]=='}':
   depth-=1
   if depth==0:return text[start:pos+1]
 raise AssertionError(marker)
tree=ast.parse((pathlib.Path(__file__).parent/'test_hotplug_diagnostics.py').read_text())
fixture=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='fixture' for t in n.targets))
fixture='#include <functional>\n'+fixture
fixture=fixture.replace('static std::vector<std::string> ops, logs;', 'static std::function<void()> onAllocate;static bool pending=false;static std::vector<std::string> ops, logs;')
fixture=fixture.replace('return allocation?std::malloc(n):nullptr;', 'if(onAllocate){auto once=std::move(onAllocate);onAllocate=nullptr;once();}return allocation?std::malloc(n):nullptr;')
fixture=fixture.replace('op("schedule:"+std::to_string(d));return false;', 'op("schedule:"+std::to_string(d));pending=true;return false;')
fixture=fixture.replace(' bool getDynamicDisplayInfo(', ' std::function<void()> onDynamic;\n bool getDynamicDisplayInfo(')
fixture=fixture.replace('  op("dynamic:"', '  if(onDynamic){auto once=std::move(onDynamic);onDynamic=nullptr;once();} op("dynamic:"')
fixture=fixture.replace('static void hotplugKick();','static void hotplugKick(NvKmsKapiDisplay);' if 'hotplugKick(NvKmsKapiDisplay' in s else 'static void hotplugKick();')
fixture=fixture.replace('bool listOK=true;unsigned required=0;','bool listOK=true;unsigned required=0; bool connectorOK=true,connectorValid=true;NvU32 dynamicMask=1;')
fixture=fixture.replace(' bool getDisplays(',''' std::function<bool(void*,NvKmsKapiConnector,NvKmsKapiConnectorInfo*)> getConnectorInfo=[this](void*,NvKmsKapiConnector h,NvKmsKapiConnectorInfo*c){op("connector-info:"+std::to_string(h));if(!connectorOK)return false;c->dynamicDpyIdListValid=connectorValid;c->dynamicDpyIdList=nvNvU32ToDpyIdList(dynamicMask);return true;};
 bool getDisplays(''')
fixture=fixture.replace(' IOService*getProvider()', ' void setProperty(const char*,unsigned long long,unsigned){}\n IOService*getProvider()')
helpers=''
if '// Dynamic display event hints' in s:
 helpers=s[s.index('// Dynamic display event hints'):s.index('// How many displays the boot enumeration found.')]
helpers=helpers.replace('static int gNDpy = -1;','')
# Fake boundary objects remain single-threaded here; a separate test exercises atomic hints concurrently.
callback=method(s,'static void eventCallback(').replace('static void eventCallback(','void NVRMNVDAFramebuffer::eventCallback(',1)
code=fixture+'\n'+helpers+'\n'+callback+'\n'+method(s,'void NVRMNVDAFramebuffer::hotplugKick(')+'\n'+method(s,'void NVRMNVDAFramebuffer::hotplugFire(')
boot=method(s[s.index('bool NVRMNVDAFramebuffer::kapiInit()'):],'if (gNDpy < 0)')
code+='\nstatic void fbGuardCleared(const char*){}\nstatic bool boot(Api*fKms,void*fDev){unsigned fNumHeads=4,fNumConnectors=1;NvKmsKapiConnector bootConnectors[NVKMS_KAPI_MAX_CONNECTORS]={42};unsigned bootConnectorCount=1;auto getProvider=[]()->IOService*{return nullptr;};\n'+boot+'\nreturn true;}\n'
start_method=s[s.index('bool NVRMNVDAFramebuffer::start(IOService *provider)'):]
ready=start_method[start_method.index('    IORecursiveLockUnlock(sl);',start_method.index('bool kapiOk = kapiInit();'))+len('    IORecursiveLockUnlock(sl);'):start_method.index('    if (!kapiOk) {',start_method.index('bool kapiOk = kapiInit();'))]
code+='\nstatic void ready(){unsigned fIndex=0;'+ready.replace('hotplugKick(', 'NVRMNVDAFramebuffer::hotplugKick(')+'\n}\n'
code+=r"""
static void event(unsigned handle,bool changed=false){NvKmsKapiEvent e={};e.type=changed?NVKMS_EVENT_TYPE_DPY_CHANGED:NVKMS_EVENT_TYPE_DYNAMIC_DPY_CONNECTED;if(changed)e.u.displayChanged.display=handle;else e.u.dynamicDisplayConnected.display=handle;NVRMNVDAFramebuffer::eventCallback(&e);}
static bool has(unsigned h){for(int k=0;k<gNDpy;++k)if(gDpy[k].handle==h)return true;return false;}
static unsigned calls(unsigned h){unsigned n=0;for(auto&o:ops)if(o=="dynamic:"+std::to_string(h))++n;return n;}
#define REQUIRE(c,msg) do{if(!(c)){fprintf(stderr,"FAIL %s: %s\n",scenario.c_str(),msg);return 1;}}while(0)
int main(int argc,char**argv){assert(argc==2);std::string scenario=argv[1];Api api;int device=1;NVRMNVDAFramebuffer fb;gFB=&fb;fb.fKms=&api;fb.fDev=&device;gHotplug=&device;
 api.listed={256,512,1024,2048,4096,8192};api.cfg[1]=DpyCfg{};
 if(scenario=="flip-only"){
  NvKmsKapiEvent e={};e.type=NVKMS_EVENT_TYPE_FLIP_OCCURRED;e.u.flipOccurred.head=1;e.u.flipOccurred.layer=NVKMS_KAPI_LAYER_PRIMARY_IDX;
  for(unsigned i=0;i<1000;++i)NVRMNVDAFramebuffer::eventCallback(&e);
  REQUIRE(logs.empty()&&!pending&&gNDpy==0,"flip events must not log or schedule display work");puts("PASS flip-only");return 0;
 }
 if(scenario.rfind("boot-",0)==0){gNDpy=-1;
  if(scenario=="boot-event-after-snapshot"){api.connectorValid=false;onAllocate=[](){event(1);pending=false;NVRMNVDAFramebuffer::hotplugFire(nullptr,nullptr);};}
  if(scenario=="boot-all32"){api.dynamicMask=0xffffffffu;for(unsigned i=0;i<32;++i)api.cfg[1u<<i]=DpyCfg{};}
  if(scenario=="boot-null-query")api.getConnectorInfo=nullptr;
  if(scenario=="boot-duplicate"){api.listed.push_back(1);event(1);}
  if(scenario=="boot-invalid")api.connectorValid=false;
  if(scenario=="boot-query-failed")api.connectorOK=false;
  if(scenario=="boot-list-failed")api.listOK=false;
  if(scenario=="boot-overflow")api.required=33;
  if(scenario=="boot-static-failed")api.cfg[1].staticOK=false;
  if(scenario=="boot-disconnected")api.cfg[1].connected=false;
  if(scenario=="boot-event-before-interest"){api.connectorValid=false;event(1);}
  bool ok=boot(&api,&device);(void)ok;
  if(scenario=="boot-event-after-snapshot"){ready();REQUIRE(pending,"startup must schedule a retained late event after enumeration");pending=false;NVRMNVDAFramebuffer::hotplugFire(nullptr,nullptr);}
  if(scenario=="boot-null-query"||scenario=="boot-invalid"||scenario=="boot-query-failed"||scenario=="boot-static-failed"||scenario=="boot-disconnected")REQUIRE(!has(1),"invalid/failed/disconnected boot handle must not be added");
  else REQUIRE(has(1),"boot must discover connected dynamic handle1 absent from getDisplays");
  if(scenario=="boot-duplicate")REQUIRE(calls(1)==1,"boot event/list/connector overlap must deduplicate");
  if(scenario=="boot-all32")REQUIRE(gNDpy==32,"boot dynamic mask must fit32 handles");
 }else{
  event(1);
  REQUIRE(calls(1)==0,"callback must not query NVKMS");
  if(scenario=="event-during-worker"){api.cfg[2]=DpyCfg{};api.onDynamic=[](){event(2);};}
  if(scenario=="no-worker-yet"){gHotplug=nullptr;event(2);gHotplug=&device;api.cfg[2]=DpyCfg{};}
  if(scenario=="duplicate")for(unsigned i=0;i<100;++i)event(1);
  if(scenario=="changed-only"){event(2,true);api.cfg[2]=DpyCfg{};}
  if(scenario=="listed-duplicate")api.listed.push_back(1);
  if(scenario=="list-failed")api.listOK=false;
  if(scenario=="list-overflow")api.required=33;
  if(scenario=="dynamic-failed")api.cfg[1].dynamicOK=false;
  if(scenario=="static-failed")api.cfg[1].staticOK=false;
  if(scenario=="already-disconnected")api.cfg[1].connected=false;
  if(scenario=="early-return")gNDpy=-1;
  if(scenario=="allocation-failed")allocation=false;
  if(scenario=="gate-failed")gate=false;
  if(scenario=="all32"){api.listed.clear();for(unsigned i=0;i<32;++i){unsigned h=1u<<i;event(h);api.cfg[h]=DpyCfg{};}}
  if(scenario=="invalid-event"){event(0);event(3);}
  NVRMNVDAFramebuffer::hotplugFire(nullptr,nullptr);
  if(scenario=="early-return"||scenario=="allocation-failed"||scenario=="gate-failed"){gNDpy=0;allocation=true;gate=true;NVRMNVDAFramebuffer::hotplugFire(nullptr,nullptr);}
  if(scenario=="event-during-worker")NVRMNVDAFramebuffer::hotplugFire(nullptr,nullptr);
  if(scenario=="event-during-worker"||scenario=="no-worker-yet")REQUIRE(has(2),"overlapping/early event2 must survive");
  if(scenario=="dynamic-failed"||scenario=="static-failed"||scenario=="already-disconnected"){
   REQUIRE(!has(1),"query failure/disconnected must not add display");api.cfg[1]=DpyCfg{};NVRMNVDAFramebuffer::hotplugFire(nullptr,nullptr);REQUIRE(has(1),"failed hint must survive until next display work");
  }else REQUIRE(has(1),"event handle1 missing from worker display table (physical list only256..8192)");
  if(scenario=="duplicate"||scenario=="listed-duplicate")REQUIRE(calls(1)==1,"duplicate handle must be queried only once per pass");
  if(scenario=="changed-only")REQUIRE(has(2),"DPY_CHANGED handle absent from physical list also must survive");
  if(scenario=="all32")REQUIRE(gNDpy==32,"all32 one-hot IDs must fit without overflow");
  if(scenario=="invalid-event")REQUIRE(calls(0)==0&&calls(3)==0,"invalid zero/multi-bit IDs must not reach NVKMS");
  if(scenario=="disconnect"||scenario=="disconnect-query-failed"||scenario=="reconnect"){
   fb.fDisplay=1;fb.fEdidSize=128;gFBs[0]=&fb;api.cfg[1].connected=false;
   if(scenario=="disconnect-query-failed")api.cfg[1].dynamicOK=false;
   event(1,true);NVRMNVDAFramebuffer::hotplugFire(nullptr,nullptr);
   REQUIRE(fb.fDpyLost==(scenario!="disconnect-query-failed"),"disconnect requires successful latest dynamic query");
   if(scenario=="reconnect"){api.cfg[1].connected=true;event(1);NVRMNVDAFramebuffer::hotplugFire(nullptr,nullptr);REQUIRE(!fb.fDpyLost,"same dynamic handle must reconnect");REQUIRE(gNDpy==1,"reconnect must reuse record");}
  }
 }
 REQUIRE(depth==0,"display gate leaked");puts(("PASS "+scenario).c_str());return 0;
}
"""
cases=['event1','duplicate','listed-duplicate','changed-only','disconnect','disconnect-query-failed','reconnect','list-failed','list-overflow','dynamic-failed','static-failed','already-disconnected','early-return','allocation-failed','all32','invalid-event','boot-connected','boot-invalid','boot-query-failed','boot-list-failed','boot-overflow','boot-static-failed','boot-disconnected','boot-event-before-interest','event-during-worker','no-worker-yet','gate-failed','boot-duplicate','boot-null-query','boot-all32','boot-event-after-snapshot','flip-only']
inc=['src/nvidia-modeset/os-interface/include','src/nvidia-modeset/kapi/interface','src/nvidia-modeset/interface','src/common/sdk/nvidia/inc','src/common/unix/common/inc','src/common/inc','src/nvidia/arch/nvalloc/unix/include']
results=[]
with tempfile.TemporaryDirectory(prefix='p16-dynamic-regression-') as td:
 td=pathlib.Path(td);cpp=td/'test.cpp';cpp.write_text(code);binary=td/'test'
 cp=subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined','-g','-Werror=format','-Wno-unused-parameter',*['-I'+str(a.vendor/p) for p in inc],str(cpp),'-o',str(binary)],capture_output=True,text=True)
 if cp.returncode:print(cp.stderr);raise SystemExit(cp.returncode)
 for case in ([a.case] if a.case else cases):
  r=subprocess.run([str(binary),case],capture_output=True,text=True);results.append(dict(case=case,exit=r.returncode,stdout=r.stdout,stderr=r.stderr));print(r.stdout+r.stderr,end='')
a.output.write_text(json.dumps(results,indent=2)+'\n');raise SystemExit(any(r['exit'] for r in results))
