#!/usr/bin/env python3
"""Execute the two real production methods; compare every non-log action/state.
Breaks caught: missing correlation logs, altered super arguments, changed rc or
fServerFresh, extra apply/refresh/notify, unsafe failed-output dereference.
"""
import argparse,pathlib,subprocess,tempfile,json,re,hashlib
p=argparse.ArgumentParser();p.add_argument('--source',type=pathlib.Path,required=True);p.add_argument('--baseline',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--smoke',action='store_true');a=p.parse_args()
markers=['IOReturn NVRMNVDAFramebuffer::newUserClient(','IOReturn NVRMNVDAFramebuffer::enableController(']
def method(s,m):
 start=s.index(m);opening=s.index('{',start);depth=0
 for i in range(opening,len(s)):
  if s[i]=='{':depth+=1
  elif s[i]=='}':
   depth-=1
   if not depth:return s[start:i+1]
 raise AssertionError(m)
def outside(s):
 for m in markers:s=s.replace(method(s,m),'/* method */',1)
 return s
source=a.source.read_text();baseline=a.baseline.read_text();assert outside(source)==outside(baseline),'unexpected change outside the two methods'
fixture=r'''
#include <cassert>
#include <cstdint>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
using UInt32=unsigned;using IOReturn=int;using task_t=void*;
constexpr IOReturn kIOReturnSuccess=0,kIOReturnError=(int)0xe00002bc;
constexpr UInt32 kIOFBServerConnectType=0;
struct IOUserClient{};static IOUserClient clientA,clientB;
static std::vector<std::string>ops,logs,timeline;
static void record(const std::string&s){ops.push_back(s);timeline.push_back(s);}
static void fblog(const char*fmt,...) __attribute__((format(printf,1,2)));
static void fblog(const char*fmt,...){char b[512];va_list v;va_start(v,fmt);vsnprintf(b,sizeof b,fmt,v);va_end(v);logs.emplace_back(b);timeline.push_back(std::string("LOG ")+b);}
#define FBLOG(...) fblog(__VA_ARGS__)
struct NVRMNVDAFramebuffer;
struct Base{
 IOReturn configuredRC=0;IOUserClient*configuredClient=nullptr;bool writes=false,nested=false;
 task_t wantTask=nullptr;void*wantSecurity=nullptr;UInt32 wantType=0;IOUserClient**wantHandler=nullptr;
 IOReturn newUserClient(task_t,void*,UInt32,IOUserClient**);
};
struct NVRMNVDAFramebuffer:Base{
 using super=Base;unsigned fIndex=0;int fServerFresh=0;bool applyOK=true,fHotplugBorn=false,fConnectFired=false;
 bool applyMode(){record("apply");return applyOK;}
 void refreshDisplayAudioProperties(){record("refresh");}
 void notifyConnectionChanged(unsigned ms){record("notify:"+std::to_string(ms));}
 IOReturn newUserClient(task_t,void*,UInt32,IOUserClient**);IOReturn enableController();
};
IOReturn Base::newUserClient(task_t task,void*security,UInt32 type,IOUserClient**handler){
 assert(task==wantTask&&security==wantSecurity&&type==wantType&&handler==wantHandler);
 record("super-enter");if(nested){auto*fb=static_cast<NVRMNVDAFramebuffer*>(this);auto rc=fb->enableController();record("nested-rc:"+std::to_string((unsigned)rc));}
 if(writes){assert(handler);*handler=configuredClient;record(configuredClient?"output:client":"output:null");}
 record("super-return:"+std::to_string((unsigned)configuredRC));return configuredRC;
}
'''
main=r'''
int main(int argc,char**argv){assert(argc==7);std::string mode=argv[1];NVRMNVDAFramebuffer fb;fb.fIndex=std::stoul(argv[2]);unsigned x=std::stoul(argv[3]),y=std::stoul(argv[4]),z=std::stoul(argv[5]),fresh=std::stoul(argv[6]);fb.fServerFresh=fresh;
 IOReturn result;IOUserClient*slot=&clientA;
 if(mode=="enable"){
  fb.applyOK=x;fb.fHotplugBorn=y;fb.fConnectFired=z;result=fb.enableController();
 }else{
  fb.wantTask=reinterpret_cast<void*>(uintptr_t(0x123));fb.wantSecurity=reinterpret_cast<void*>(uintptr_t(0x456));fb.wantType=x;
  fb.configuredRC=y==0?0:y==1?kIOReturnError:(int)0xdeadbeef;
  fb.configuredClient=z==0?nullptr:&clientB;fb.writes=z<=1||z==4;fb.nested=z==5;
  // z2: null output argument, z3: deliberately invalid output address on error.
  // Error paths must not read the output slot or initialize the caller's value.
  fb.wantHandler=z==2?nullptr:z==3?reinterpret_cast<IOUserClient**>(uintptr_t(1)):&slot;
  assert(!(z==3&&y==0));result=fb.newUserClient(fb.wantTask,fb.wantSecurity,x,fb.wantHandler);
 }
 for(auto&s:ops)printf("OP %s\n",s.c_str());
 printf("STATE rc=%u fresh=%d slot=%d\n",(unsigned)result,fb.fServerFresh,slot==&clientA?1:slot==&clientB?2:0);
 for(auto&s:logs)printf("LOG %s\n",s.c_str());
 for(auto&s:timeline)printf("TIME %s\n",s.c_str());
}
'''
cases=[]
for idx in [0,1,15]:
 for ok in [0,1]:
  for hot in [0,1]:
   for fired in [0,1]:cases.append(('enable',idx,ok,hot,fired,9))
for idx in [0,1]:
 for typ in [0,1,99]:
  for rc in [0,1,2]:
   for output in ([0,1,2,4,5] if rc==0 else [0,1,2,3,4,5]):cases.append(('client',idx,typ,rc,output,9))
if a.smoke:cases=[('enable',1,1,1,0,9),('client',1,0,0,1,9)]
results=[]
with tempfile.TemporaryDirectory(prefix='p16-activation-fixture-') as td:
 td=pathlib.Path(td);bins={}
 for name,s in [('baseline',baseline),('candidate',source)]:
  cpp=td/(name+'.cpp');cpp.write_text(fixture+'\n'+'\n'.join(method(s,m) for m in markers)+'\n'+main);binary=td/name
  c=subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined','-g','-Wall','-Wextra','-Werror=format',str(cpp),'-o',str(binary)],capture_output=True,text=True)
  if c.returncode:print(c.stderr);raise SystemExit(c.returncode)
  bins[name]=binary
 for case in cases:
  outputs={name:subprocess.run([str(binary),*[str(v) for v in case]],capture_output=True,text=True) for name,binary in bins.items()}
  for r in outputs.values():assert r.returncode==0,r.stderr
  state=lambda text:[l for l in text.splitlines() if l.startswith(('OP ','STATE '))]
  equal=state(outputs['baseline'].stdout)==state(outputs['candidate'].stdout)
  lines=outputs['candidate'].stdout.splitlines();logs=[l[4:] for l in lines if l.startswith('LOG P16ACT ')];idx=case[1]
  expected=[]
  if case[0]=='enable' or case[4]==5:
   rc=0 if case[0]!='enable' or case[2] else 0xe00002bc
   expected += [f'P16ACT enableController enter fb={idx}',f'P16ACT enableController exit fb={idx} rc=0x{rc:08x}']
  if case[0]=='client':
   typ,rc_case,output=case[2:5];rc=[0,0xe00002bc,0xdeadbeef][rc_case]
   present='unavailable' if rc or output==2 else '1' if output in [1,4,5] else '0'
   expected += [f'P16ACT newUserClient enter fb={idx} type={typ}',f'P16ACT newUserClient super-return fb={idx} type={typ} rc=0x{rc:08x} client={present}']
  # Exact generated log records make both field values and omission visible.
  fields=sorted(logs)==sorted(expected)
  ordered=logs==expected if case[0]=="enable" else True
  if case[0]=='client':
   stream=outputs['candidate'].stdout
   timeline=[l[5:] for l in lines if l.startswith('TIME ')]
   enter=next((i for i,v in enumerate(timeline) if v.startswith('LOG P16ACT newUserClient enter ')),-1)
   exit_=next((i for i,v in enumerate(timeline) if v.startswith('LOG P16ACT newUserClient super-return ')),-1)
   super_enter=timeline.index('super-enter');super_exit=next(i for i,v in enumerate(timeline) if v.startswith('super-return:'))
   # Output lists preserve log order; nested logs must lie between the two client records.
   ordered=0<=enter<super_enter<super_exit<exit_ and bool(logs) and logs[0].startswith('P16ACT newUserClient enter ') and logs[-1].startswith('P16ACT newUserClient super-return ')
  timeline=[l[5:] for l in lines if l.startswith('TIME ')]
  if case[0]=='enable' or case[4]==5:
   e=next((i for i,v in enumerate(timeline) if v.startswith('LOG P16ACT enableController enter ')),-1)
   x=next((i for i,v in enumerate(timeline) if v.startswith('LOG P16ACT enableController exit ')),-1)
   original_ops=[i for i,v in enumerate(timeline) if v in ['apply','refresh'] or v.startswith('notify:')]
   ordered=ordered and bool(original_ops) and 0<=e<min(original_ops)<=max(original_ops)<x
  passed=equal and fields and ordered
  results.append(dict(case=case,behavior_identical=equal,required_fields=fields,log_order=ordered,pass_=passed,logs=logs))
  if not passed:print('FAIL',case,'behavior_equal',equal,'expected_logs',expected,'actual_logs',logs)
a.output.write_text(json.dumps(dict(cases=results,case_count=len(results),all_pass=all(r['pass_'] for r in results),outside_two_methods_identical=True,baseline_sha256=hashlib.sha256(baseline.encode()).hexdigest(),source_sha256=hashlib.sha256(source.encode()).hexdigest()),indent=2)+'\n')
if all(r['pass_'] for r in results):print('PASS:',len(results),'cases; identical original operations/state; all correlation logs; null/error/poisoned output and nested calls covered')
raise SystemExit(not all(r['pass_'] for r in results))
