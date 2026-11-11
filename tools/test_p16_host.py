#!/usr/bin/env python3
"""P16 host tests that need nothing outside this tree (run by tools/run_all_tests.py).

  tools/p16/test_nvaccel_registration_failure_barrier.py  NVAccel: no head takes a failed head's pipe (22 checks)
  tools/p16/test_display_enumeration_snapshot.py          NVRMFB: getDisplays read once at full capacity (ASan/UBSan)
"""
import pathlib, subprocess, sys, tempfile
ROOT = pathlib.Path(__file__).resolve().parents[1]
P16 = ROOT / "tools" / "p16"
fails = 0
with tempfile.TemporaryDirectory(prefix="p16-host-") as td:
    for name, argv in (
        ("test_nvaccel_registration_failure_barrier.py",
         ["--source", str(ROOT / "kexts/NVRM/accel/nvrm-accel.cpp"), "--output", str(pathlib.Path(td) / "barrier.json")]),
        ("test_display_enumeration_snapshot.py", []),
    ):
        r = subprocess.run([sys.executable, str(P16 / name), *argv], cwd=ROOT, capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip()
        print(("ok   " if r.returncode == 0 else "FAIL ") + name + ": " + (out.splitlines()[-1] if out else ""))
        if r.returncode:
            print(out[-2000:]); fails += 1
print(f"{fails} failed")
sys.exit(1 if fails else 0)
