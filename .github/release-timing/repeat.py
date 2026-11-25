import json
import math
import os
from pathlib import Path
import statistics
import tempfile

import compare

info=Path("/proc/cpuinfo").read_text()
model=next(x.partition(":")[2].strip() for x in info.splitlines() if x.startswith("model name"))
profile="false" if "intel" in model.lower() else "thin"
os.environ["CARGO_PROFILE_BENCH_LTO"]=profile
report=compare.REPORT
report.mkdir()
with tempfile.TemporaryDirectory(prefix="hex21-") as tmp:
    work=Path(tmp)
    compare.build(work)
    core=min(os.sched_getaffinity(0))
    os.sched_setaffinity(0,{core})
    compare.DRIVERS=["hex"]
    compare.CASES={"hex":["encode/faster_hex/4096","decode/faster_hex_mixed/4096"]}
    orders=[("b0","h0","h1","b1"),("h0","b1","b0","h1"),
            ("b1","h1","h0","b0"),("h1","b0","b1","h0")]
    blocks=[]
    for order in orders*6:
        block={key:compare.measure(work,"base" if key.startswith("b") else "head") for key in order}
        blocks.append(block)
        (report/"repeat-samples.json").write_text(json.dumps({"cpu":model,"profile":profile,"core":core,"blocks":blocks}))
        print(model,profile,len(blocks),flush=True)
results={}
for case in compare.CASES["hex"]:
    estimates={}
    for label in ("source","base_sham","head_sham"):
        vals=[]
        for block in blocks:
            b0,b1,h0,h1=[block[key][case] for key in ("b0","b1","h0","h1")]
            v={"source":math.sqrt(h0*h1/(b0*b1)),"base_sham":b1/b0,"head_sham":h1/h0}[label]
            vals.append(100*(v-1))
        vals.sort()
        estimates[label]=[round(statistics.median(vals),3),sum(v>0 for v in vals),round(vals[6],3),round(vals[-7],3)]
    results[case]=estimates
(report/"repeat.json").write_text(json.dumps({"cpu":model,"profile":profile,"results":results}))
print(results,flush=True)
