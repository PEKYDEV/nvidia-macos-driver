#!/usr/bin/env python3
"""Stress the production hint accumulator and bounded union with concurrent producers.
Break caught: non-atomic read/modify/write or clearing hints while taking a snapshot.
"""
import argparse,pathlib,subprocess,tempfile,json
p=argparse.ArgumentParser();p.add_argument('--source',type=pathlib.Path,required=True);p.add_argument('--vendor',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--sanitizer',choices=['address,undefined','thread'],default='address,undefined');a=p.parse_args()
s=a.source.read_text();helpers=s[s.index('// Dynamic display event hints'):s.index('// How many displays the boot enumeration found.')]
cpp=r'''
#include <nvkms.h>
#include <cassert>
#include <atomic>
#include <thread>
#include <vector>
#include <cstdio>
#define FBLOG(...) ((void)0)
'''+helpers+r'''
int main(){
 NvKmsKapiDisplay buf[3]={0,0,0xdeadbeef};NvU32 n=0;
 nvrmAppendDisplay(buf,&n,2,1);nvrmAppendDisplay(buf,&n,2,1);nvrmAppendDisplay(buf,&n,2,0);nvrmAppendDisplay(buf,&n,2,3);
 assert(n==1&&buf[0]==1);nvrmAppendDisplay(buf,&n,2,2);nvrmAppendDisplay(buf,&n,2,4);assert(n==2&&buf[1]==2&&buf[2]==0xdeadbeef);
 std::atomic<bool> go{false},done{false};std::vector<std::thread> producers;
 for(unsigned i=0;i<32;++i)producers.emplace_back([&,i]{while(!go.load())std::this_thread::yield();for(unsigned j=0;j<10000;++j)nvrmRememberDisplay(1u<<i);});
 std::thread consumer([&]{while(!go.load())std::this_thread::yield();unsigned previous=0;while(!done.load()){
  NvKmsKapiDisplay handles[32]={};NvU32 count=0;nvrmAppendEventDisplays(handles,&count,32);assert(count<=32);unsigned snapshot=0;
  for(unsigned j=0;j<count;++j){assert(handles[j]&&!(handles[j]&(handles[j]-1)));assert(!(snapshot&handles[j]));snapshot|=handles[j];}
  assert((snapshot&previous)==previous);previous=snapshot;
 }});
 go.store(true);for(auto&t:producers)t.join();done.store(true);consumer.join();
 NvKmsKapiDisplay handles[32]={};n=0;nvrmAppendEventDisplays(handles,&n,32);assert(n==32);for(unsigned i=0;i<32;++i)assert(handles[i]==(1u<<i));
 puts("PASS: 32 concurrent producers, 320000 events, concurrent snapshots, no lost IDs; capacity canary and duplicate/invalid guards");
}
'''
incs=['src/nvidia-modeset/os-interface/include','src/nvidia-modeset/kapi/interface','src/nvidia-modeset/interface','src/common/sdk/nvidia/inc','src/common/unix/common/inc','src/common/inc','src/nvidia/arch/nvalloc/unix/include']
with tempfile.TemporaryDirectory(prefix='p16-atomic-') as td:
 td=pathlib.Path(td);c=td/'test.cpp';c.write_text(cpp);binary=td/'test'
 command=['clang++','-std=c++17','-pthread','-g','-fsanitize='+a.sanitizer,*['-I'+str(a.vendor/i) for i in incs],str(c),'-o',str(binary)]
 compile=subprocess.run(command,capture_output=True,text=True);run=subprocess.run([str(binary)],capture_output=True,text=True) if not compile.returncode else None
 result=dict(sanitizer=a.sanitizer,command=command,compile_exit=compile.returncode,compile_stderr=compile.stderr,run_exit=run.returncode if run else None,stdout=run.stdout if run else '',stderr=run.stderr if run else '')
 a.output.write_text(json.dumps(result,indent=2)+'\n');print(result['stdout']+result['compile_stderr']+result['stderr']);raise SystemExit(compile.returncode or (run.returncode if run else 1))
