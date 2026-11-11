#!/usr/bin/env python3
"""Execute extracted production methods; compare all non-log operations to the enumeration baseline."""
import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import tempfile

parser=argparse.ArgumentParser()
parser.add_argument('--source',type=pathlib.Path,required=True)
parser.add_argument('--baseline',type=pathlib.Path,required=True)
parser.add_argument('--vendor',type=pathlib.Path,required=True)
parser.add_argument('--output',type=pathlib.Path,required=True)
args=parser.parse_args()

def method(source,marker):
    start=source.index(marker);opening=source.index('{',start);depth=0
    for pos in range(opening,len(source)):
        if source[pos]=='{':depth+=1
        elif source[pos]=='}':
            depth-=1
            if depth==0:return source[start:pos+1]
    raise AssertionError(marker)

fixture=r'''
#include <nvkms.h>
#include <cassert>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <map>
#include <cstdint>
using thread_call_param_t=void*; using thread_call_t=void*; using UInt32=unsigned;
#include "nvrm-fb-safety.h"   // v2.9: kNvrmBootRetries, nvrmBootRetryDelayMs, nvrmPickNubParent (real definitions)
static std::vector<std::string> ops, logs;
static void op(const std::string&s){ops.push_back(s);}
static void fblog(const char*fmt,...) __attribute__((format(printf,1,2)));
static void fblog(const char*fmt,...){char b[1024];va_list a;va_start(a,fmt);vsnprintf(b,sizeof b,fmt,a);va_end(a);logs.emplace_back(b);}
#define FBLOG(...) fblog(__VA_ARGS__)
static unsigned sFlipLatched[8]={};
static unsigned OSIncrementAtomic(unsigned*p){op("flip-latched");return ++*p;}
static int OSAddAtomic(int,volatile int*p){op("read-stopping");return *p;}
static int kMillisecondScale=1, kIOServiceAsynchronous=1, gIOServicePlane=1;
static void clock_interval_to_deadline(unsigned ms,int,std::uint64_t*d){op("deadline:"+std::to_string(ms));*d=ms;}
static bool thread_call_enter_delayed(thread_call_t,std::uint64_t d){op("schedule:"+std::to_string(d));return false;}
struct IORecursiveLock{};static IORecursiveLock lockObject;static bool gate=true, allocation=true, iterator=true;
static IORecursiveLock*startLock(){op("start-lock");return gate?&lockObject:nullptr;}
static unsigned depth=0;
static void IORecursiveLockLock(IORecursiveLock*){op("lock");++depth;}
static void IORecursiveLockUnlock(IORecursiveLock*){op("unlock");--depth;}
static void*IOMalloc(std::size_t n){op("allocate");return allocation?std::malloc(n):nullptr;}
static void IOFree(void*p,std::size_t){op("free");std::free(p);}
static void nvu_zero(void*p,std::size_t n){std::memset(p,0,n);}
static void nvu_copy(void*d,const void*s,std::size_t n){std::memcpy(d,s,n);}
struct OSObject {virtual ~OSObject()=default;};
struct OSNumber:OSObject {unsigned value=0;unsigned unsigned32BitValue(){return value;}};
struct OSIterator:OSObject {std::vector<OSObject*>values;unsigned pos=0;OSObject*getNextObject(){return pos<values.size()?values[pos++]:nullptr;}void release(){op("iterator-release");}};
struct IOService:OSObject {
 IOService*parent=nullptr;bool hasIndex=false,client=false;OSNumber number;OSIterator children;
 IOService*getProvider(){return parent;}
 OSIterator*getChildIterator(int){op("get-iterator");return iterator?&children:nullptr;}
 OSObject*getProperty(const char*){return hasIndex?&number:nullptr;}
 IOService*getClient(){return client?this:nullptr;}
 void registerService(int){op("register:"+std::to_string(number.value));}
};
#define OSDynamicCast(type,value) dynamic_cast<type*>(value)
struct DpyCfg {bool dynamicOK=true,connected=true,staticOK=true;unsigned edid=128,seed=1;};
struct Api {
 std::vector<NvKmsKapiDisplay> listed;std::map<NvKmsKapiDisplay,DpyCfg> cfg;bool listOK=true;unsigned required=0;
 bool getDisplays(void*,NvU32*n,NvKmsKapiDisplay*out){
  op("getDisplays:"+std::to_string(*n));if(!listOK)return false;
  unsigned count=required?required:listed.size();if(*n>=count)for(unsigned i=0;i<listed.size();++i)out[i]=listed[i];*n=count;return true;
 }
 bool getDynamicDisplayInfo(void*,NvKmsKapiDynamicDisplayParams*d){
  op("dynamic:"+std::to_string(d->handle));auto c=cfg.find(d->handle);DpyCfg v=c==cfg.end()?DpyCfg{true,false,true,0,1}:c->second;
  if(!v.dynamicOK)return false;d->connected=v.connected;d->edid.bufferSize=v.edid;
  assert(v.edid<=sizeof d->edid.buffer);for(unsigned i=0;i<v.edid;++i)d->edid.buffer[i]=(unsigned char)v.seed;return true;
 }
 bool getStaticDisplayInfo(void*,NvKmsKapiDisplay h,NvKmsKapiStaticDisplayInfo*s){
  op("static:"+std::to_string(h));if(!cfg[h].staticOK)return false;
  s->connectorHandle=42;s->headMask=3;s->isDpMST=NV_TRUE;s->internal=NV_FALSE;return true;
 }
};
struct NVRMNVDAFramebuffer:IOService {
 Api*fKms=nullptr;void*fDev=nullptr;NvKmsKapiDisplay fDisplay=0;unsigned fIndex=0,fHead=0;
 bool fDpyLost=false,fHeadSlept=false,fEdidSwapped=false,fRelightAudioValid=false;volatile int fStopping=0;int fReflipRc=0;
 NvU32 fEdidSize=0;NvU8 fEdid[NVKMS_KAPI_EDID_BUFFER_SIZE]={};std::uint64_t fBlackLutDeadline=0;int refs=0;
 static void eventCallback(const NvKmsKapiEvent*);static void hotplugKick();static void hotplugFire(void*,void*);
 static void surroundCheck(){op("surround-check");}   // v2.9: no surround group configured
 static void flipWake(unsigned h){op("flip-wake:"+std::to_string(h));}
 void retain(){++refs;op("retain:"+std::to_string(fIndex));}void release(){--refs;op("release:"+std::to_string(fIndex));}
 void takeEdid(const NvU8*p,NvU32 n){fEdidSize=n;std::memcpy(fEdid,p,n);op("take-edid:"+std::to_string(fIndex));}
 void clearDisplayAudioProperties(){op("clear-audio:"+std::to_string(fIndex));}
 void publishDisplayAudioProperties(){op("publish-audio:"+std::to_string(fIndex));}
 void notifyConnectionChanged(unsigned n){assert(depth==0);op("notify:"+std::to_string(fIndex)+":"+std::to_string(n));}
 bool reflip(){assert(depth==0);op("reflip:"+std::to_string(fIndex));return true;}
 void adoptSwappedDisplay(){op("adopt:"+std::to_string(fIndex));}
};
struct nvrm_dpy_rec {NvKmsKapiDisplay handle=0;NvKmsKapiConnector connector=0;NvU32 headMask=0;NvBool internal=0;NvU32 hdaConnectorType=0;NvBool mst=0,connected=0,vrr=0;NvU32 edidSize=0;NvU8 edid[NVKMS_KAPI_EDID_BUFFER_SIZE]={};};
static NVRMNVDAFramebuffer*gFB=nullptr;static NVRMNVDAFramebuffer*gFBs[16]={};
static nvrm_dpy_rec gDpy[NVKMS_KAPI_MAX_CONNECTORS*2];static int gNDpy=0;static thread_call_t gHotplug=nullptr;
// v2.9 stubs: the EDID-override wrapper with no override file present is the plain query; boot-arg reads answer "not set"
static NvBool nvrmDynamicDisplayInfo(Api*k,void*d,NvKmsKapiDynamicDisplayParams*p){return k->getDynamicDisplayInfo(d,p);}
static IOService*gNubParent=nullptr;static unsigned gBootRetry=kNvrmBootRetries;
static bool PE_parse_boot_argn(const char*,void*,int){op("boot-arg");return false;}
static NvU32 nvrmQueryHdaConnectorType(Api*,void*,NvKmsKapiConnector c){op("connector:"+std::to_string(c));return 0x400;}
'''

main=r'''
int main(int argc,char**argv){
 assert(argc==2);std::string scenario=argv[1];Api api;NVRMNVDAFramebuffer fb;IOService nub,gpu,missingIndex,busy,outside,idle;
 int device=1;fb.fKms=&api;fb.fDev=&device;fb.fDisplay=256;gFB=&fb;gFBs[0]=&fb;
 fb.fIndex=0;nub.parent=&gpu;fb.parent=&nub;
 api.listed={256};api.cfg[256]=DpyCfg{};
 busy.hasIndex=true;busy.client=true;outside.hasIndex=true;outside.number.value=99;idle.hasIndex=true;idle.number.value=0;
 gpu.children.values={&missingIndex,&busy,&outside,&idle};gHotplug=&device;
 if(scenario=="event-dpy"||scenario=="event-dynamic"||scenario=="event-flip"||scenario=="event-other"){
  NvKmsKapiEvent e={};
  if(scenario=="event-dpy"){e.type=NVKMS_EVENT_TYPE_DPY_CHANGED;e.u.displayChanged.display=256;}
  else if(scenario=="event-dynamic"){e.type=NVKMS_EVENT_TYPE_DYNAMIC_DPY_CONNECTED;e.u.dynamicDisplayConnected.display=257;}
  else if(scenario=="event-flip"){e.type=NVKMS_EVENT_TYPE_FLIP_OCCURRED;e.u.flipOccurred.head=1;e.u.flipOccurred.layer=NVKMS_KAPI_LAYER_PRIMARY_IDX;}
  else e.type=NVKMS_EVENT_TYPE_DPY_ATTRIBUTE_CHANGED;
  for(unsigned i=0;i<(scenario=="event-flip"?1000u:1u);++i)NVRMNVDAFramebuffer::eventCallback(&e);
 }else if(scenario=="kick-missing"){gHotplug=nullptr;NVRMNVDAFramebuffer::hotplugKick();}
 else {
  if(scenario=="no-fb")gFB=nullptr;
  else if(scenario=="no-api")fb.fKms=nullptr;
  else if(scenario=="no-device")fb.fDev=nullptr;
  else if(scenario=="not-enumerated")gNDpy=-1;
  else if(scenario=="list-failed")api.listOK=false;
  else if(scenario=="overflow")api.required=33;
  else if(scenario=="capacity"){api.listed.clear();for(unsigned i=0;i<32;++i){api.listed.push_back(256+i);api.cfg[256+i]=DpyCfg{};}}
  else if(scenario=="allocate-failed")allocation=false;
  else if(scenario=="empty")api.listed.clear();
  else if(scenario=="new-dynamic-failed")api.cfg[256].dynamicOK=false;
  else if(scenario=="new-disconnected")api.cfg[256].connected=false;
  else if(scenario=="new-static-failed")api.cfg[256].staticOK=false;
  else if(scenario=="table-full"){gNDpy=32;for(unsigned i=0;i<32;++i)gDpy[i].handle=512+i;}
  else if(scenario=="no-gate")gate=false;
  else if(scenario=="no-provider")fb.parent=nullptr;
  else if(scenario=="no-gpu")nub.parent=nullptr;
  else if(scenario=="no-iterator")iterator=false;
  else if(scenario=="empty-iterator")gpu.children.values.clear();
  if(scenario.rfind("known-",0)==0||scenario.rfind("omitted-",0)==0){
   gNDpy=1;gDpy[0].handle=256;gDpy[0].connector=42;gDpy[0].headMask=3;gDpy[0].hdaConnectorType=0x400;
   gDpy[0].edidSize=128;std::memset(gDpy[0].edid,1,128);
   if(scenario=="known-dynamic-failed")api.cfg[256].dynamicOK=false;
   if(scenario=="known-disconnected"||scenario=="known-already-lost")api.cfg[256].connected=false;
   if(scenario=="known-already-lost"||scenario.rfind("known-reconnect",0)==0)fb.fDpyLost=true;
   if(scenario=="known-reconnect-stopping")fb.fStopping=1;
   if(scenario=="known-reconnect-slept")fb.fHeadSlept=true;
   if(scenario=="known-reconnect-no-edid")api.cfg[256].edid=0;
   if(scenario=="known-swapped")api.cfg[256].seed=2;
   if(scenario=="known-no-fb")gFBs[0]=nullptr;
   if(scenario=="known-other-fb")fb.fDisplay=300;
   if(scenario.rfind("omitted-",0)==0){api.listed.clear();if(scenario=="omitted-failed")api.cfg[256].dynamicOK=false;if(scenario=="omitted-disconnected")api.cfg[256].connected=false;}
  }
  NVRMNVDAFramebuffer::hotplugFire(nullptr,nullptr);
 }
 for(const auto&s:ops)printf("OP %s\n",s.c_str());
 printf("STATE count=%d lost=%u edid=%u swapped=%u refs=%d deadline=%llu\n",gNDpy,fb.fDpyLost,fb.fEdidSize,fb.fEdidSwapped,fb.refs,(unsigned long long)fb.fBlackLutDeadline);
 for(int i=0;i<gNDpy;++i)printf("STATE dpy=%u connected=%u connector=%u mask=%u mst=%u edid=%u first=%u\n",gDpy[i].handle,(unsigned)gDpy[i].connected,gDpy[i].connector,gDpy[i].headMask,(unsigned)gDpy[i].mst,gDpy[i].edidSize,(unsigned)gDpy[i].edid[0]);
 for(const auto&s:logs)printf("LOG %s\n",s.c_str());
}
'''

scenarios=['event-dpy','event-dynamic','event-flip','event-other','kick-missing',
 'no-fb','no-api','no-device','not-enumerated','list-failed','overflow','capacity','allocate-failed','empty',
 'new-dynamic-failed','new-disconnected','new-static-failed','new','table-full','no-gate',
 'no-provider','no-gpu','no-iterator','empty-iterator','known-connected','known-dynamic-failed',
 'known-disconnected','known-already-lost','known-reconnect','known-reconnect-stopping','known-reconnect-slept','known-reconnect-no-edid','known-swapped','known-no-fb',
 'known-other-fb','omitted-failed','omitted-connected','omitted-disconnected']
required={
 'event-dpy':['event type=0 handle=256'], 'event-dynamic':['event type=1 handle=257'],
 'kick-missing':['kick skip=no-worker-call'], 'no-fb':['worker enter','worker return=no-framebuffer'],
 'no-api':['worker return=no-kms'], 'no-device':['worker return=no-device'],
 'not-enumerated':['worker return=not-enumerated'], 'list-failed':['getDisplays ok=0','worker return=getDisplays-failed'],
 'overflow':['getDisplays ok=1 count=33','worker return=capacity-exceeded'],
 'capacity':['getDisplays ok=1 count=32','getDisplays handle[31]=287'],
 'allocate-failed':['worker return=no-dynamic-storage'], 'empty':['getDisplays ok=1 count=0','worker return=no-added-displays'],
 'new-dynamic-failed':['known=0 dyn_ok=0','add skip=dynamic-query-failed'],
 'new-disconnected':['known=0 dyn_ok=1 connected=0 edid_len=128','add skip=disconnected'],
 'new-static-failed':['static ok=0','add skip=static-query-failed'],
 'new':['getDisplays handle[0]=256','static ok=1 connector=42 mst=1 headMask=3','add index=0',
        'match skip=no-fb-index','match skip=has-client','match skip=index-out-of-range','match register index=0'],
 'table-full':['add skip=display-table-full'], 'no-provider':['match skip=no-provider'],
 'no-gpu':['match skip=no-gpu-provider'], 'no-iterator':['match skip=no-child-iterator'],
 'empty-iterator':['match skip=no-eligible-idle-nub'],
 'known-dynamic-failed':['known skip=dynamic-query-failed'],
 'known-reconnect-stopping':['relight skip=stopping'],
 'known-reconnect-slept':['relight skip=head-asleep'],
 'known-reconnect-no-edid':['known=1 dyn_ok=1 connected=1 edid_len=0','reflip ok=1'],
 'known-no-fb':['known fb-matches=0'], 'known-other-fb':['known fb-matches=0'],
 'omitted-failed':['listed=0 dyn_ok=0','omitted skip=dynamic-query-failed'],
 'omitted-connected':['listed=0 dyn_ok=1 connected=1','omitted skip=still-connected'],
 'omitted-disconnected':['listed=0 dyn_ok=1 connected=0'],
}
results=[]
source=args.source.read_text();baseline=args.baseline.read_text()
markers=['static void eventCallback(','void NVRMNVDAFramebuffer::hotplugKick(','void NVRMNVDAFramebuffer::hotplugFire(']
outside=lambda text:__import__('functools').reduce(lambda value,marker:value.replace(method(value,marker),'/* METHOD */',1),markers,text)
assert outside(source)==outside(baseline),'Change outside the three diagnostic methods'
for query in ['getDisplays(', 'getDynamicDisplayInfo(', 'getStaticDisplayInfo(']:
    assert sum(method(source,m).count(query) for m in markers)==sum(method(baseline,m).count(query) for m in markers),query
with tempfile.TemporaryDirectory(prefix='p16-hotplug-fixture-') as td:
    td=pathlib.Path(td);binaries={}
    for name,path in [('baseline',args.baseline),('diagnostic',args.source)]:
        source=path.read_text()
        event=method(source,'static void eventCallback(').replace('static void eventCallback(', 'void NVRMNVDAFramebuffer::eventCallback(',1)
        code=fixture+'\n'+event+'\n'+method(source,'void NVRMNVDAFramebuffer::hotplugKick(')+'\n'+method(source,'void NVRMNVDAFramebuffer::hotplugFire(')+'\n'+main
        cpp=td/(name+'.cpp');cpp.write_text(code);binary=td/name
        inc=['src/nvidia-modeset/os-interface/include','src/nvidia-modeset/kapi/interface','src/nvidia-modeset/interface','src/common/sdk/nvidia/inc','src/common/unix/common/inc','src/common/inc','src/nvidia/arch/nvalloc/unix/include']
        command=['clang++','-std=c++17','-fsanitize=address,undefined','-g','-Wall','-Wextra','-Werror=format','-Wno-unused-parameter',*['-I'+str(args.vendor/p) for p in inc],str(cpp),'-o',str(binary)]
        subprocess.run(command,check=True);binaries[name]=binary
    for scenario in scenarios:
        outputs={name:subprocess.run([str(binary),scenario],capture_output=True,text=True,check=True).stdout.splitlines() for name,binary in binaries.items()}
        state=lambda lines:[s for s in lines if s.startswith(('OP ','STATE '))]
        assert state(outputs['baseline'])==state(outputs['diagnostic']),f'Behavior or query sequence changed: {scenario}'
        logs='\n'.join(s for s in outputs['diagnostic'] if s.startswith('LOG P16HP '))
        if scenario in ['event-flip','event-other']:assert not logs,scenario+' must not add logs'
        if scenario in ['overflow','list-failed']:assert 'getDisplays handle[' not in logs,'Invalid handle array was logged'
        for fragment in required.get(scenario,[]):assert fragment in logs,(scenario,'missing log',fragment,logs)
        results.append({'scenario':scenario,'operations_and_state_identical':True,'diagnostic_logs':logs.splitlines()})
args.output.write_text(json.dumps(results,indent=2)+'\n')
print(f'PASS: {len(results)} scenarios; API/side-effect order and final state identical; required logs present; 1000 flip events silent.')
