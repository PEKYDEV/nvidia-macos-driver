#!/usr/bin/env python3
"""Exercise the production boot/hotplug enumeration against NVKMS's size contract.

This is a userspace boundary test, not a macOS kernel or hardware test.
The insufficient-capacity response matches NVIDIA 615.78.08 GetDisplays:
success + required count, with the handle array left untouched.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "kexts/NVRMFB/fb/nvrm-fb.cpp").read_text()
if "--baseline" in sys.argv:
    SOURCE = subprocess.check_output(
        ["git", "show", "HEAD:kexts/NVRMFB/fb/nvrm-fb.cpp"], cwd=ROOT, text=True)


def enumeration(marker):
    method = SOURCE.index(marker)
    start = min(SOURCE.index("NvU32 n =", method),
                SOURCE.index("NvKmsKapiDisplay handles[", method))
    end = SOURCE.index("struct NvKmsKapiDynamicDisplayParams *dd", start)
    # Exercise the capacity contract before merging independently discovered IDs.
    boundary = SOURCE.find("const NvU32 listed = n", start, end)
    if boundary >= 0: end = boundary
    return SOURCE[start:end]


fixture = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <algorithm>
using NvU32 = uint32_t;
using NvKmsKapiDisplay = uint32_t;
constexpr unsigned NVKMS_KAPI_MAX_CONNECTORS = 16;
#define FBLOG(...) ((void)0)
struct Api {
    unsigned total = 3, calls = 0;
    bool fail = false;
    bool getDisplays(void *, NvU32 *n, NvKmsKapiDisplay *out) {
        ++calls;
        if (fail) return false;
        // A count-only call sees an earlier topology. No writes if too small.
        if (!out) { *n = 2; return true; }
        if (*n >= total)
            for (unsigned i = 0; i < total; ++i) out[i] = 1u << i;
        *n = total;
        return true;
    }
} api;
struct Fb {
    Api *fKms = &api;
    void *fDev = nullptr;
    unsigned fNumHeads = 4, fNumConnectors = 6;
} object;
unsigned consumed = 0;
void consume(unsigned n, const NvKmsKapiDisplay *handles, unsigned capacity) {
    assert(n <= capacity && "returned required count must not index beyond array");
    for (unsigned i = 0; i < n; ++i)
        assert(handles[i] == 1u << i && "consumed an unwritten display handle");
    consumed = n;
}
'''
boot = enumeration("bool NVRMNVDAFramebuffer::kapiInit(")
hotplug = enumeration("void NVRMNVDAFramebuffer::hotplugFire(")
code = fixture + "\nbool boot() {\nauto fKms=object.fKms; auto fDev=object.fDev;\n" + boot
code += "consume(n, handles, sizeof handles / sizeof handles[0]); return true; }\n"
code += "void hotplug() {\nauto me=&object;\n" + hotplug
code += "consume(n, handles, sizeof handles / sizeof handles[0]); }\n"
code += r'''
int main() {
    for (bool bootPath : {false, true}) {
        for (unsigned count : {3u, 1u, 32u}) {
            api = Api{}; api.total = count; consumed = 0;
            if (bootPath) assert(boot()); else hotplug();
            assert(consumed == count);
        }
        api = Api{}; api.total = 33; consumed = 0;
        if (bootPath) boot(); else hotplug();
        assert(consumed == 0 && "oversized topology must be rejected");
        api = Api{}; api.fail = true; consumed = 0;
        if (bootPath) boot(); else hotplug();
        assert(consumed == 0);
    }
    api = Api{}; api.total = 0; consumed = 99; hotplug();
    assert(consumed == 0);
    api = Api{}; api.total = 0; boot();
    puts("PASS: production snapshot boundary: grow/shrink/32-capacity/overflow/API failure/empty (dynamic union tested separately)");
}
'''
compiler = os.environ.get("CXX") or shutil.which("clang++") or shutil.which("g++")
if not compiler:
    raise SystemExit("C++ compiler required")
with tempfile.TemporaryDirectory() as directory:
    directory = pathlib.Path(directory)
    cpp, binary = directory / "test.cpp", directory / "test"
    cpp.write_text(code)
    # Zero automatic storage makes an untouched array deterministic in the old code.
    subprocess.run([compiler, "-std=c++17", "-ftrivial-auto-var-init=zero",
                    "-fsanitize=address,undefined", "-g", str(cpp), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
