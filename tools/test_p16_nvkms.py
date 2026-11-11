#!/usr/bin/env python3
"""P16 host tests that compile NVRMFB code against NVIDIA's NVKMS headers (run by tools/run_all_tests.py).

The headers come from NM_OGKM620 or OGKM: the open-gpu-kernel-modules 620.70.06 tree build_rm620.sh patched (the same
tree build/fb_build.sh compiles NVRMFB against). Without one the test reports SKIP.

  tools/p16/test_dynamic_display_events.py   32 cases: event, kick, worker and boot enumeration keep dynamic (MST) IDs
  tools/p16/test_dynamic_display_atomic.py   32 concurrent producers, under ThreadSanitizer and under ASan/UBSan
  tools/p16/test_p16_logging_neutral.py      P16LOG off and on: no output when off, same behaviour either way
"""
import os, pathlib, subprocess, sys, tempfile
ROOT = pathlib.Path(__file__).resolve().parents[1]
P16 = ROOT / "tools" / "p16"
SRC = ROOT / "kexts/NVRMFB/fb/nvrm-fb.cpp"
tree = next((pathlib.Path(os.environ[k]) for k in ("NM_OGKM620", "OGKM") if os.environ.get(k)), None)
if not tree or not (tree / "src/nvidia-modeset/kapi/interface/nvkms-kapi.h").is_file():
    print("SKIP: no NVKMS headers; set NM_OGKM620 (or OGKM) to the open-gpu-kernel-modules 620.70.06 tree"); sys.exit(2)
fails = 0
with tempfile.TemporaryDirectory(prefix="p16-nvkms-") as td:
    out = lambda n: str(pathlib.Path(td) / n)
    common = ["--source", str(SRC), "--vendor", str(tree)]
    for name, argv in (
        ("test_dynamic_display_events.py", common + ["--output", out("events.json")]),
        ("test_dynamic_display_atomic.py", common + ["--sanitizer", "thread", "--output", out("tsan.json")]),
        ("test_dynamic_display_atomic.py", common + ["--sanitizer", "address,undefined", "--output", out("asan.json")]),
        ("test_p16_logging_neutral.py", common + ["--output", out("neutral.json")]),
    ):
        r = subprocess.run([sys.executable, str(P16 / name), *argv], cwd=ROOT, capture_output=True, text=True)
        text = (r.stdout + r.stderr).strip()
        passed = sum(1 for l in text.splitlines() if l.startswith("PASS"))
        label = name + ("" if "--sanitizer" not in argv else " (" + argv[argv.index("--sanitizer") + 1] + ")")
        print(("ok   " if r.returncode == 0 else "FAIL ") + f"{label}: {passed} PASS line(s)")
        if r.returncode:
            print(text[-2000:]); fails += 1
print(f"{fails} failed")
sys.exit(1 if fails else 0)
