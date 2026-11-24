"""Counterbalance four intact binaries across the same 16 files under each CPU mask."""
from pathlib import Path
import hashlib,json,math,os,random,shutil,statistics,subprocess
root=Path.cwd();out=root/'affinity-report';out.mkdir(exist_ok=True)
lab=root/'relocations'
paths={k:lab/r/s for k,r,s in [('R','published','native'),('P','latest','native'),('S','published','swapped'),('Q','latest','swapped')]}
positions={r:json.loads((lab/r/'layout.json').read_text()) for r in ('published','latest')}
(out/'link-layout.json').write_text(json.dumps(positions))
allowed=sorted(os.sched_getaffinity(0))
def topology(n):
    t=Path('/sys/devices/system/cpu')/f'cpu{n}'/'topology'
    return [(t/f).read_text().strip() for f in ('physical_package_id','core_id','thread_siblings_list')]
top={c:topology(c) for c in allowed}
first=allowed[0]; second=next((c for c in reversed(allowed) if top[c][:2]!=top[first][:2]),allowed[-1])
masks={'pinned-a':[first],'pinned-b':[second],'unbound':allowed}
assert len(allowed)>1 and first!=second
(out/'host.json').write_text(json.dumps({'allowed':allowed,'topology':top,'masks':masks,'lscpu':subprocess.check_output(['lscpu'],text=True)},indent=2))
slots=[root/f'layout-sample-{i}' for i in range(16)]
for p in slots:p.touch(exist_ok=False);p.chmod(0o755)
inodes=[p.stat().st_ino for p in slots];assert len(set(inodes))==len(slots)
site=root/'same-full-buffer'
def run(p,n,count):
    site.unlink(missing_ok=True);os.link(p,site)
    return float(subprocess.check_output([site,str(n),str(count)],text=True))
allbytes={k:p.read_bytes() for k,p in paths.items()}
seed=int(os.environ['REPLICA'])
rng=random.Random(38159+seed*557)
phase0=[0,1,2,3]*4;rng.shuffle(phase0)
labels='RPSQ';rotations=[0,1,3,2,2,3,1,0]
affinity=list(masks)
cases=[(policy,n) for policy in affinity for n in (32,4096)]
counts={}
for policy,n in cases:
    os.sched_setaffinity(0,masks[policy])
    assert sorted(os.sched_getaffinity(0))==masks[policy]
    inherited=json.loads(subprocess.check_output(['python3','-c','import json,os;print(json.dumps(sorted(os.sched_getaffinity(0))))'],text=True))
    assert inherited==masks[policy]
    counts[(policy,n)]=min(4000000,max(1000,round(6000000/max(1,run(paths['R'],n,25000)))))
records=[]
for period,rot in enumerate(rotations):
    kinds=[labels[(x+rot)%4] for x in phase0]
    for p,k,ino in zip(slots,kinds,inodes):
        with p.open('wb') as outfd:
            outfd.write(allbytes[k]);outfd.flush();os.fsync(outfd.fileno())
        assert p.stat().st_ino==ino and hashlib.sha256(p.read_bytes()).digest()==hashlib.sha256(allbytes[k]).digest()
    order=list(cases);rng.shuffle(order);data={}
    for policy,n in order:
        os.sched_setaffinity(0,masks[policy])
        sources={str(i):slot for i,slot in enumerate(slots)}
        sources.update(a=paths['R'],aa=paths['R'],b=paths['P'],bb=paths['P'])
        rows=[]
        for rep in range(3):
            names=list(sources);rng.shuffle(names);obs={name:[] for name in names}
            for name in names+names[::-1]:obs[name].append(run(sources[name],n,counts[policy,n]))
            rows.append({name:statistics.mean(v) for name,v in obs.items()})
        data[policy+'/'+str(n)]=rows
    records.append({'kinds':kinds,'data':data})
    (out/f'period-{period}.json').write_text(json.dumps(records[-1]))
    print('period',period,'complete',flush=True)
os.sched_setaffinity(0,allowed)
def stats(ratios):
    k=sum(x>1 for x in ratios);n=len(ratios);p=2*sum(math.comb(n,i) for i in range(min(k,n-k)+1))/2**n
    return [round(100*(statistics.median(ratios)-1),3),k,round(min(1,p),6)]
pairs={'upgrade':('R','P'),'same-old-layout':('R','Q'),'same-new-layout':('S','P'),'move-old-to-new':('R','S'),'move-new-to-old':('P','Q'),'upgrade-layouts-exchanged':('S','Q')}
summary={}
for policy,n in cases:
    tag=policy+'/'+str(n); row={}
    samples=[o for period in records for o in period['data'][tag]]
    controls={k:stats([x[k2]/x[k1] for x in samples]) for k,k1,k2 in [('old','a','aa'),('new','b','bb')]}
    bycycle=[]
    for begin in (0,4):
        values=[{} for _ in slots]
        for period in records[begin:begin+4]:
            for i,k in enumerate(period['kinds']):
                values[i][k]=statistics.median(s[str(i)] for s in period['data'][tag])
        bycycle.append(values)
    for name,(left,right) in pairs.items():row[name]=[stats([v[right]/v[left] for v in cycle]) for cycle in bycycle]
    row['controls']=controls
    row['median_ns']={k:round(statistics.median(v[k] for cycle in bycycle for v in cycle),3) for k in labels}
    summary[tag]=row
    print(tag,row,flush=True)
(out/'summary.json').write_text(json.dumps(summary,indent=2))
# Optional read-only hardware counters, when exposed by the runner.
perf=shutil.which('perf')
if perf:
    os.sched_setaffinity(0,[first])
    for k,p in paths.items():
        for n,count in ((32,60000000),(4096,2000000)):
            dest=out/f'perf-{k}-{n}.txt'
            res=subprocess.run([perf,'stat','--no-big-num','-x','|','-e','cycles:u,instructions:u,branches:u,branch-misses:u,cpu-migrations','--',str(p),str(n),str(count)],capture_output=True,text=True,timeout=20)
            dest.write_text(f'return code {res.returncode}\n'+res.stderr)
            if res.returncode:break
        if res.returncode:break
    os.sched_setaffinity(0,allowed)
