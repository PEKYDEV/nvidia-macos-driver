#!/usr/bin/env python3
"""Real NVAccel registration bodies; external family boundary is controlled.

Break caught: after refused/null/wrong-FB registration, a subsequent walk or
empty-count sweep must not bypass the failed slot and renumber a later head.
No live IOKit, scheduling, thread-safety or WindowServer claim is made.
"""
import argparse,hashlib,json,pathlib,subprocess,tempfile
p=argparse.ArgumentParser();p.add_argument('--source',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args();s=a.source.read_text()
def method(sig):
 start=s.index(sig);opening=s.index('{',start);depth=0
 for i in range(opening,len(s)):
  if s[i]=='{':depth+=1
  elif s[i]=='}':
   depth-=1
   if depth==0:return s[start:i+1]
 raise ValueError(sig)
fields=s[s.index('    IOService *fFB = nullptr;'):s.index('    static bool fbPublished(')]
fixture=r'''
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <cstdlib>
#include <vector>
using UInt32=unsigned;
#define ALOG(...) ((void)0)
struct IOLock{};struct OSObject{};
struct IOService{unsigned index;const char*getName(){return "fixture";}};
using IOFramebuffer=IOService;
constexpr unsigned kNvMaxFB=5;
static unsigned gNvHeadsPublished=0,gNvHeadsRegistered=0,gNvHeadsPiped=0;static int gNvIgpu=0;
struct Pipe{alignas(8) unsigned char bytes[0xa0]={};void set(IOService*fb){memcpy(bytes+0x98,&fb,sizeof fb);}};
struct DM{
 alignas(8) unsigned char bytes[0x200]={};
 enum Mode{Success,Refuse,NullPipe,WrongFB};Mode mode=Success;unsigned failIndex=1,calls=0,sweeps=0;IOService wrong{99};Pipe pipes[5];
 unsigned getFramebufferCount(){unsigned n;memcpy(&n,bytes+0x108,4);return n;}
 void count(unsigned n){memcpy(bytes+0x108,&n,4);}
 void found_framebuffer(IOFramebuffer*fb){
  ++calls;unsigned n=getFramebufferCount();if(n>=5)abort();
  for(unsigned j=0;j<n;++j){Pipe*old=nullptr;memcpy(&old,bytes+0x88+8*j,sizeof old);IOService*bound=nullptr;if(old)memcpy(&bound,old->bytes+0x98,sizeof bound);if(bound==fb)return;}
  if(mode==Refuse&&n>=1)return;
  const Mode chosen=fb->index==failIndex?mode:Success;

  Pipe*ptr=nullptr;
  if(chosen!=NullPipe){pipes[n].set(chosen==WrongFB?&wrong:fb);ptr=&pipes[n];}
  memcpy(bytes+0x88+8*n,&ptr,sizeof ptr);count(n+1);
 }
 void start(void*){++sweeps;}
};
struct NVAccel{
 alignas(8) unsigned char abi[0xdd8]={};
 DM*fDM=nullptr;void*fPCI=nullptr;unsigned modeChanges=0;
 void onCountGrewLocked(){++modeChanges;}
'''
main=r'''
};
static unsigned failures=0,cases=0;
static void check(bool ok,const char*msg){++cases;if(!ok){++failures;fprintf(stderr,"FAIL %s\n",msg);}else printf("PASS %s\n",msg);}
static void reset(){gNvHeadsPublished=gNvHeadsRegistered=gNvHeadsPiped=0;gNvIgpu=0;}
static void failureCase(DM::Mode mode,const char*name){
 reset();NVAccel a;DM dm;a.fDM=&dm;IOService fb0{0},fb1{1},fb2{2};a.fFB=&fb0;a.fFBs[0]=&fb0;gNvHeadsPublished=1;
 check(a.registerFramebufferLocked(1)&&dm.getFramebufferCount()==1&&gNvHeadsPiped==1,"head0 has verified pipe");
 dm.mode=mode;a.fFBs[1]=&fb1;gNvHeadsPublished=3;
 a.registerFramebufferLocked(1);
 check(!(gNvHeadsPiped&2),"failed head1 never marked piped");
 if(mode==DM::NullPipe)check(dm.getFramebufferCount()==1,"null pipe count rolled back before returning");
 const auto calls=dm.calls,changes=a.modeChanges,count=dm.getFramebufferCount();
 a.fFBs[2]=&fb2;gNvHeadsPublished=7;
 const bool got=a.registerFramebufferLocked(1);
 printf("scenario %s: original calls%u; after retry%u; count%u\n",name,calls,dm.calls,dm.getFramebufferCount());
 if(mode==DM::Refuse)check(!got&&dm.getFramebufferCount()==count&&a.modeChanges==changes,"capacity refusal preserves count and arming");
 else check(!got&&dm.calls==calls&&dm.getFramebufferCount()==count&&a.modeChanges==changes,"later head cannot bypass failed slot on next request");
 check(!(gNvHeadsPiped&4),"later head cannot claim failed pipe position");
}
int main(){
 failureCase(DM::Refuse,"refused");failureCase(DM::NullPipe,"null");failureCase(DM::WrongFB,"wrongFramebuffer");
 reset();{
 NVAccel a;DM dm;a.fDM=&dm;IOService fb0{0},fb1{1};a.fFB=&fb0;a.fFBs[0]=&fb0;a.fFBs[1]=&fb1;gNvHeadsPublished=3;
 check(a.registerFramebufferLocked(1)&&dm.calls==2&&dm.getFramebufferCount()==2&&gNvHeadsPiped==3&&a.modeChanges==1,"two successful heads preserve existing arming path");
 check(!a.registerFramebufferLocked(1)&&dm.calls==2&&a.modeChanges==1,"repeat successful request does not duplicate registration");
 }
 reset();{
 NVAccel a;DM dm;a.fDM=&dm;IOService fb0{0};a.fFB=&fb0;a.fFBs[0]=&fb0;gNvHeadsPublished=1;dm.mode=DM::NullPipe;dm.failIndex=0;
 check(!a.registerFramebufferLocked(1)&&dm.getFramebufferCount()==0&&a.modeChanges==0,"failed first head leaves zero count and does not arm");
 a.registerFramebufferLocked(2);check(dm.sweeps==0&&dm.getFramebufferCount()==0,"mode2 sweep cannot bypass prior first-head failure");
 }
 reset();{
 NVAccel a;DM dm;a.fDM=&dm;IOService fb0{0},fb1{1},fb2{2};a.fFB=&fb0;a.fFBs[0]=&fb0;a.fFBs[1]=&fb1;gNvHeadsPublished=3;dm.mode=DM::NullPipe;
 check(a.registerFramebufferLocked(1)&&dm.getFramebufferCount()==1&&gNvHeadsPiped==1&&a.modeChanges==1,"successful prefix before null failure keeps original behavior");
 unsigned calls=dm.calls;a.fFBs[2]=&fb2;gNvHeadsPublished=7;
 check(!a.registerFramebufferLocked(1)&&dm.calls==calls,"successful prefix cannot hide failure on a later walk");
 }
 reset();{
 NVAccel a;DM dm;a.fDM=&dm;IOService fb0{0},fb1{1};a.fFB=&fb0;a.fFBs[0]=&fb0;gNvHeadsPublished=1;dm.found_framebuffer(&fb0);
 check(!a.registerFramebufferLocked(1)&&dm.getFramebufferCount()==1,"already family-known framebuffer is not a failed creation");
 a.fFBs[1]=&fb1;gNvHeadsPublished=3;check(a.registerFramebufferLocked(1)&&dm.getFramebufferCount()==2&&gNvHeadsPiped==2,"family-known framebuffer does not prohibit later successful registration");
 }
 reset();{
 NVAccel a;DM dm;a.fDM=&dm;IOService fb0{0};a.fFB=&fb0;
 a.registerFramebufferLocked(2);check(dm.sweeps==1,"mode2 remains available before any failure");
 }
 printf("%u checks, %u failures\n",cases,failures);return failures?1:0;
}
'''
with tempfile.TemporaryDirectory(prefix='p16-failure-barrier-') as td:
 td=pathlib.Path(td);cpp=td/'test.cpp';cpp.write_text(fixture+fields+method('    unsigned registerPendingLocked(')+method('    bool registerFramebufferLocked(')+main)
 c=subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined','-g',str(cpp),'-o',str(td/'test')],capture_output=True,text=True)
 r=subprocess.run([str(td/'test')],capture_output=True,text=True) if c.returncode==0 else None
 result=dict(source=str(a.source),source_sha256=hashlib.sha256(s.encode()).hexdigest(),compile_exit=c.returncode,compile_stderr=c.stderr,run_exit=r.returncode if r else None,stdout=r.stdout if r else '',stderr=r.stderr if r else '',scope=__doc__)
 a.output.write_text(json.dumps(result,indent=2)+'\n');print(c.stderr+result['stdout']+result['stderr']);raise SystemExit(c.returncode or(r.returncode if r else 1))
