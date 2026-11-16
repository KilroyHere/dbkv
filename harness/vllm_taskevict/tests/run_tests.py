"""Run every test_* function in this directory without pytest (the dbkv env has none). Exit 1 on failure.

    python harness/vllm_taskevict/tests/run_tests.py [module ...]     # e.g. test_gateway_taskevict
"""
import importlib, os, sys, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

mods = sys.argv[1:] or sorted(f[:-3] for f in os.listdir(HERE) if f.startswith("test_") and f.endswith(".py"))
fails = 0
for m in mods:
    mod = importlib.import_module(m)
    for name in [n for n in dir(mod) if n.startswith("test_") and callable(getattr(mod, n))]:
        t0 = time.time()
        try:
            getattr(mod, name)()
            print(f"PASS {m}.{name} ({time.time() - t0:.1f} s)", flush=True)
        except Exception:  # noqa: BLE001
            fails += 1
            print(f"FAIL {m}.{name} ({time.time() - t0:.1f} s)", flush=True)
            traceback.print_exc()
print(f"{'FAILED' if fails else 'OK'}: {fails} failure(s)")
sys.exit(1 if fails else 0)
