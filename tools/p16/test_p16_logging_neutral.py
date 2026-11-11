#!/usr/bin/env python3
"""P16HP/P16ACT diagnostics are off without nvfblog=1 and never change behaviour.

1. The real P16LOG/FBLOGV/fbVerbose block from nvrm-fb.cpp, compiled on its own: with nvfblog unset nothing reaches
   IOLog, kprintf or the trace and the arguments are not evaluated; with nvfblog=1 the line reaches all three.
2. The real eventCallback, hotplugKick, hotplugFire and kapiInit enumeration, against the NVKMS boundary fake of
   test_hotplug_diagnostics.py, run per scenario with nvfblog off and on: the API call order and the final state are
   identical, no P16 line appears when off, and P16 lines appear when on.
3. With --baseline <nvrm-fb.cpp before the diagnostics>, the same scenarios give the same API call order and final
   state as that source.
Userspace only: no kernel, IOKit or hardware claim is made.
"""
import argparse, ast, json, os, pathlib, re, subprocess, tempfile

ap = argparse.ArgumentParser()
ap.add_argument('--source', type=pathlib.Path, required=True)
ap.add_argument('--vendor', type=pathlib.Path, required=True, help='open-gpu-kernel-modules 620.70.06 tree')
ap.add_argument('--baseline', type=pathlib.Path)
ap.add_argument('--output', type=pathlib.Path, required=True)
a = ap.parse_args()
HERE = pathlib.Path(__file__).resolve().parent
INC = ['src/nvidia-modeset/os-interface/include', 'src/nvidia-modeset/kapi/interface', 'src/nvidia-modeset/interface',
       'src/common/sdk/nvidia/inc', 'src/common/unix/common/inc', 'src/common/inc', 'src/nvidia/arch/nvalloc/unix/include']


def method(text, marker):
    start = text.index(marker); opening = text.index('{', start); depth = 0
    for pos in range(opening, len(text)):
        if text[pos] == '{': depth += 1
        elif text[pos] == '}':
            depth -= 1
            if depth == 0: return text[start:pos + 1]
    raise AssertionError(marker)


def build(td, name, code, extra=()):
    cpp = td / f'{name}.cpp'; cpp.write_text(code); binary = td / name
    r = subprocess.run(['clang++', '-std=c++17', '-fsanitize=address,undefined', '-g', '-Werror=format',
                        '-Wno-unused-parameter', *extra, str(cpp), '-o', str(binary)], capture_output=True, text=True)
    if r.returncode: raise SystemExit(f'{name} does not build:\n{r.stderr[-3000:]}')
    return binary


results = {'macro': None, 'scenarios': []}
source = a.source.read_text()

# ---- 1. the macro block, as compiled into the kext
m = re.search(r'static int gFbVerbose = -1;.*?#define FBLOGV\(.*?while \(0\)\n', source, re.S)
p16 = re.search(r'#define P16LOG\(.*?while \(0\)\n', source, re.S)
assert m and p16, 'fbVerbose/FBLOGV/P16LOG definitions not found'
macro = r'''
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
static int io, kp, tr, evaluated;
static void IOLog(const char *, ...) { io++; }
static void kprintf(const char *, ...) { kp++; }
static void trace(const char *) { tr++; }
#define FBTRACE(buf) do { trace(buf); } while (0)
static int PE_parse_boot_argn(const char *n, void *v, int) { const char *e = getenv("NVFBLOG");
    if (strcmp(n, "nvfblog") || !e) return 0; *(uint32_t *)v = (uint32_t)atoi(e); return 1; }
static unsigned arg() { evaluated++; return 7; }
''' + m.group(0) + p16.group(0) + r'''
int main() { P16LOG("P16HP probe %u", arg()); printf("io %d kprintf %d trace %d evaluated %d\n", io, kp, tr, evaluated); }
'''
with tempfile.TemporaryDirectory(prefix='p16-log-neutral-') as td:
    td = pathlib.Path(td)
    mb = build(td, 'macro', macro)
    off = subprocess.run([str(mb)], capture_output=True, text=True, env={k: v for k, v in os.environ.items() if k != 'NVFBLOG'}).stdout.strip()
    zero = subprocess.run([str(mb)], capture_output=True, text=True, env={**os.environ, 'NVFBLOG': '0'}).stdout.strip()
    on = subprocess.run([str(mb)], capture_output=True, text=True, env={**os.environ, 'NVFBLOG': '1'}).stdout.strip()
    assert off == 'io 0 kprintf 0 trace 0 evaluated 0', ('nvfblog unset', off)
    assert zero == 'io 0 kprintf 0 trace 0 evaluated 0', ('nvfblog=0', zero)
    # FBLOGV expands its arguments once per sink (IOLog, kprintf, trace), so on they are evaluated more than once
    assert re.fullmatch(r'io 1 kprintf 1 trace 1 evaluated [1-9]', on), ('nvfblog=1', on)
    results['macro'] = {'unset': off, 'nvfblog=0': zero, 'nvfblog=1': on}
    # ...which is harmless only while no P16LOG argument has a side effect
    calls = []
    for start in [i.start() for i in re.finditer(r'\bP16LOG\(', source)][1:]:   # [0] is the #define
        depth = 0
        for pos in range(start + 6, len(source)):
            depth += {'(': 1, ')': -1}.get(source[pos], 0)
            if depth == 0: calls.append(source[start:pos + 1]); break
    for c in calls:
        body = re.sub(r'"(?:[^"\\]|\\.)*"', '""', c)
        assert not re.search(r'\+\+|--|(?<![=!<>])=(?!=)|->(?:retain|release)\(', body), ('side effect in a P16LOG argument', c)
    results['p16log_calls_side_effect_free'] = len(calls)

    # ---- 2./3. behaviour with the diagnostics off and on (and against the baseline source)
    tree = ast.parse((HERE / 'test_hotplug_diagnostics.py').read_text())
    def assigned(name):
        return next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
    fixture, main, scenarios = assigned('fixture'), assigned('main'), assigned('scenarios')
    fixture = fixture.replace('static void hotplugKick();', 'static void hotplugKick(NvKmsKapiDisplay = 0);')
    fixture = fixture.replace('bool listOK=true;unsigned required=0;', 'bool listOK=true;unsigned required=0; bool connectorOK=true,connectorValid=true;NvU32 dynamicMask=1;')
    fixture = fixture.replace(' bool getDisplays(', ''' bool (*getConnectorInfo)(void*,NvKmsKapiConnector,NvKmsKapiConnectorInfo*)=&connectorInfo;
 static bool connectorInfo(void*,NvKmsKapiConnector h,NvKmsKapiConnectorInfo*c){op("connector-info:"+std::to_string(h));c->dynamicDpyIdListValid=NV_TRUE;c->dynamicDpyIdList=nvNvU32ToDpyIdList(0x2);return true;}
 bool getDisplays(''')
    fixture = fixture.replace(' IOService*getProvider()', ' void setProperty(const char*,unsigned long long,unsigned){}\n IOService*getProvider()')
    # nvfblog for the fake: the environment variable, like the macro test
    fixture += r'''
#include <cstdlib>
static bool fbVerbose(){const char*e=getenv("NVFBLOG");return e&&atoi(e);}
#define FBLOGV(...) fblog(__VA_ARGS__)
static void fbGuardCleared(const char*){op("guard-cleared");}
'''
    boot_main = main.replace('if(scenario=="event-dpy"', r'''if(scenario.rfind("boot",0)==0){gNDpy=-1;api.cfg[2]=DpyCfg{};
  if(scenario=="boot-list-failed")api.listOK=false;
  if(scenario=="boot-overflow")api.required=33;
  boot(&api,&device);
 }else if(scenario=="event-dpy"''', 1)
    assert boot_main != main
    def program(text, name):
        helpers = text[text.index('// Dynamic display event hints'):text.index('// How many displays the boot enumeration found.')].replace('static int gNDpy = -1;', '')
        definition = re.search(r'#define P16LOG\(.*?while \(0\)\n', text, re.S)
        event = method(text, 'static void eventCallback(').replace('static void eventCallback(', 'void NVRMNVDAFramebuffer::eventCallback(', 1)
        boot = method(text[text.index('bool NVRMNVDAFramebuffer::kapiInit()'):], 'if (gNDpy < 0)').replace('hotplugKick(', 'NVRMNVDAFramebuffer::hotplugKick(')
        # the connector capture before IOFree(ri) belongs to kapiInit's preamble; the fake supplies its result
        code = fixture + (definition.group(0) if definition else '#define P16LOG(...) do {} while (0)\n') + helpers + event + '\n'
        code += method(text, 'void NVRMNVDAFramebuffer::hotplugKick(') + '\n' + method(text, 'void NVRMNVDAFramebuffer::hotplugFire(') + '\n'
        code += ('static bool boot(Api*fKms,void*fDev){unsigned fNumHeads=4,fNumConnectors=1;NvKmsKapiConnector bootConnectors[NVKMS_KAPI_MAX_CONNECTORS]={42};'
                 'unsigned bootConnectorCount=1;auto getProvider=[]()->IOService*{return nullptr;};\n' + boot + '\nreturn true;}\n')
        return build(td, name, code + boot_main, ['-I' + str(a.vendor / p) for p in INC] + ['-I' + str(a.source.resolve().parent)])
    binary = program(source, 'source')
    base = program(a.baseline.read_text(), 'baseline') if a.baseline else None
    state = lambda lines: [s for s in lines if s.startswith(('OP ', 'STATE '))]
    p16lines = lambda lines: [s for s in lines if s.startswith('LOG ') and ' P16' in ' ' + s[4:]]
    for scenario in scenarios + ['boot', 'boot-list-failed', 'boot-overflow']:
        run = lambda b, v: subprocess.run([str(b), scenario], capture_output=True, text=True, check=True,
                                          env={**{k: x for k, x in os.environ.items() if k != 'NVFBLOG'}, **({'NVFBLOG': v} if v else {})}).stdout.splitlines()
        o_off, o_zero, o_on = run(binary, None), run(binary, '0'), run(binary, '1')
        assert state(o_off) == state(o_on) == state(o_zero), f'{scenario}: nvfblog changes the API call order or the final state'
        assert not p16lines(o_off) and not p16lines(o_zero), f'{scenario}: a P16 line appeared without nvfblog=1: {p16lines(o_off)[:3]}'
        if scenario not in ('event-flip', 'event-other'):
            assert p16lines(o_on), f'{scenario}: no P16 line with nvfblog=1'
        else:
            assert not p16lines(o_on), f'{scenario}: routine events must stay silent'
        same_as_baseline = None
        if base:
            o_base = run(base, None)
            same_as_baseline = state(o_base) == state(o_on)
            assert same_as_baseline, f'{scenario}: API call order or final state differs from the baseline source'
        results['scenarios'].append({'scenario': scenario, 'operations': len(state(o_on)), 'p16_lines_on': len(p16lines(o_on)),
                                     'identical_off_on': True, 'identical_to_baseline': same_as_baseline})
a.output.write_text(json.dumps(results, indent=2) + '\n')
n = len(results['scenarios'])
print(f'PASS: P16LOG off (unset and nvfblog=0): no output, arguments not evaluated; on: kernel log and trace. '
      f'{n} scenarios: identical API order and state with nvfblog off and on' + (', and identical to the baseline source' if a.baseline else '') + '; no P16 line when off.')
