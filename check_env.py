"""Day one check on LinuxONE: architecture, Python, packages and a tiny training timing.
Screenshot the output for judging criterion 3.
    python check_env.py
"""
import importlib
import os
import platform
import time

print("Machine     :", platform.machine(), "(expect s390x on LinuxONE)")
print("System      :", platform.platform())
print("Python      :", platform.python_version())
print("CPU cores   :", os.cpu_count())
try:
    with open("/proc/meminfo") as f:
        print("Memory      :", f.readline().split(":")[1].strip())
except OSError:
    pass

for name in ["numpy", "pandas", "sklearn", "joblib", "lightgbm", "streamlit", "requests"]:
    try:
        mod = importlib.import_module(name)
        print(f"{name:<12}: OK {getattr(mod, '__version__', '')}")
    except Exception as exc:  # noqa: BLE001
        print(f"{name:<12}: MISSING ({exc.__class__.__name__})")

try:
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier

    X = np.random.rand(20000, 12)
    y = (X[:, 0] + X[:, 1] > 1).astype(int)
    t = time.time()
    HistGradientBoostingClassifier(max_iter=100).fit(X, y)
    print(f"Train 20k x 12 gradient boosting: {time.time() - t:.2f} s")
except Exception as exc:  # noqa: BLE001
    print("Timing test skipped:", exc)
