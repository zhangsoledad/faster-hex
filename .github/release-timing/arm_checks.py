"""Time the released 2.0 callers of hex_check, at the same package identity and executable path."""
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile

ROOT = Path.cwd()
CASES = [f"check_valid/{case}/{length}" for length in (32, 4096) for case in ("either", "lower", "upper")]
CASES += ["check_valid/either/65", "check_compare/faster_hex/32", "check_compare/faster_hex/4096",
          "invalid/check/first/32", "invalid/check/last/4096"]
EXPR = "^(" + "|".join(CASES) + ")$"
cloud = len(sys.argv) == 1
report = ROOT / ("release-report" if cloud else "arm-evidence")
report.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix="hex-check-") as tmp:
    work = Path(tmp)
    if cloud:
        import compare
        compare.DRIVERS = ["check"]
        compare.build(work)
        names = {s: work / s / "check" for s in ("base","head")}
        core = min(os.sched_getaffinity(0))
        os.sched_setaffinity(0, {core})
        cpu = next((line.split(":",1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                    if line.startswith("model name") or line.startswith("CPU part")), "Linux ARM64")
    else:
        d = Path(sys.argv[1]).resolve()
        names = {s: d / (s + "-check") for s in ("base","head")}
        core = None
        cpu = "macOS ARM64"
    hist = []
    def point(role):
        slot = work / "run-check"
        pending = work / "pending"
        shutil.copyfile(names[role], pending)
        pending.chmod(0o755)
        os.replace(pending, slot)
        est = work / "measurements"
        env = dict(os.environ, CRITERION_HOME=str(est), RAYON_NUM_THREADS="1")
        pr = subprocess.run([str(slot),EXPR,"--bench","--noplot","--warm-up-time","0.14",
                             "--measurement-time","0.36","--sample-size","20","--nresamples","1500"],
                            cwd=work, env=env, text=True, capture_output=True)
        if pr.returncode:
            raise ValueError((pr.returncode,pr.stderr[-1000:]))
        data = {}
        for f in est.glob("**/new/benchmark.json"):
            key=json.loads(f.read_text())["full_id"]
            data[key]=json.loads((f.parent/"estimates.json").read_text())["median"]["point_estimate"]
        if set(data)!=set(CASES): raise ValueError(("unexpected measured cases",set(CASES)-set(data),set(data)-set(CASES)))
        shutil.rmtree(est)
        return data
    for order in ["bhhb","hbbh","hbbh","bhhb"] * 3:
        block=[(side, point("base" if side=="b" else "head")) for side in order]
        hist.append(block)
        (report/"arm-samples.json").write_text(json.dumps({"cpu":cpu, "core":core, "blocks":hist}))
        print(cpu,"block",len(hist),flush=True)
results={}
for case in CASES:
    ratios=[]
    repeat=[]
    for block in hist:
        b,h=([v[case] for s,v in block if s==side] for side in "bh")
        ratios.append(math.sqrt(h[0]*h[1]/(b[0]*b[1])))
        repeat.extend((abs(math.log(b[0]/b[1])),abs(math.log(h[0]/h[1]))))
    ratio=sorted(100*(r-1) for r in ratios)
    results[case]=[round(statistics.median(ratio),3),sum(r>0 for r in ratio),
                   round(ratio[2],3),round(ratio[-3],3),round(100*math.expm1(statistics.median(repeat)),3)]
(report/"arm-summary.json").write_text(json.dumps({"cpu":cpu,"results":results}))
print(json.dumps(results),flush=True)
