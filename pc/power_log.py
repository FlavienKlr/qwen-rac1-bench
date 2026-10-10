#!/usr/bin/env python3
"""
GPU power once a second, Windows or Linux, for the energy figures.

    python pc/power_log.py runs/qwen38-base/power.csv

Writes epoch,power_w,util_pct,mem_used_mib. The epoch is this PC's clock,
the same clock logproxy.py stamps requests with, so the two line up.
"""
import subprocess
import sys
import time

out = sys.argv[1] if len(sys.argv) > 1 else "power.csv"
query = ["nvidia-smi", "--query-gpu=power.draw,utilization.gpu,memory.used", "--format=csv,noheader,nounits"]
with open(out, "a") as f:
    if f.tell() == 0:
        f.write("epoch,power_w,util_pct,mem_used_mib\n")
    while True:
        t = time.time()
        try:
            line = subprocess.run(query, capture_output=True, text=True, timeout=5).stdout.splitlines()[0]
            f.write(f"{t:.3f}," + ",".join(x.strip() for x in line.split(",")) + "\n")
            f.flush()
        except Exception as e:  # keep logging through a hiccup
            print(f"nvidia-smi: {e}", file=sys.stderr)
        time.sleep(max(0.0, 1.0 - (time.time() - t)))
