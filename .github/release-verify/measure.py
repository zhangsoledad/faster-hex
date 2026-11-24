import hashlib,json,math,os,platform,random,shutil,statistics,subprocess,sys
from pathlib import Path
root=Path.cwd()
kind=sys.argv[1]
if kind=='local':
    profiles=('default','thin')
    out=root/'local-release-data'
else:
    profiles=[x for x in ('default','thin') if (root/'images'/x).is_dir()]
    out=root/'release-data'
out.mkdir(exist_ok=True)
if hasattr(os,'sched_getaffinity'):
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
def image(p,role,b):
    if kind=='local':return root/'m5-images'/p/('prefix' if b=='public_prefix' else 'append')/(role+'-'+b)
    return root/'images'/p/(role+'-'+b)
cases=[('public_prefix',7,'sha1-adopt'),('public_prefix',7,'sha256-adopt'),('public_prefix',0,'sha1-adopt'),('public_prefix',0,'sha256-adopt')]
cases += [('full_buffer',n,'') for n in (4,32,4096)]+[('qualified_decode',n,'') for n in (32,4096)]
cases += [('legacy_check',32,''),('full_format',32,'display'),('owned_blocks',32,'array'),('owned_blocks',4096,'vec-late')]
cases += [('ckb_caller',n,k) for n in (32,4096) for k in ('plain','escaped')]+[('gix_caller',n,'parse') for n in (20,32)]
cases += [('array_read_slice',32,'plain'),('vec_read_slice',4096,'escaped'),('array_round_slice',32,'plain'),('vec_round_slice',4096,'plain'),('vec_write',4096,'plain')]
summary={}
replica=int(os.environ.get('REPLICA','1'))
def report(v):
    k=sum(x>1 for x in v);n=len(v); h=n//2
    return [round(100*(statistics.median(t)-1),3) for t in (v,v[:h],v[h:])]+[round(min(1,2*sum(math.comb(n,i) for i in range(min(k,n-k)+1))/2**n),5)]
labels=('published','latest','published-again','latest-again')
pinned={}
hashfile=out/'hashes.json'
for i,(b,n,k) in enumerate(cases):
    for p in profiles:
        key=f'{p}/{b}/{n}/{k}'
        paths={}
        for role in labels:
            raw=image(p,role.removesuffix('-again'),b)
            if role.endswith('-again'):
                dup=out/(p+'-'+role+'-'+b)
                if not dup.exists():shutil.copy2(raw,dup)
                paths[role]=dup
            else:paths[role]=raw
        if b not in pinned.get(p,{}):
            pinned.setdefault(p,{})[b]={x:hashlib.sha256(v.read_bytes()).hexdigest() for x,v in paths.items()}
            assert all(pinned[p][b][x]==pinned[p][b][x+'-again'] for x in ('published','latest'))
            hashfile.write_text(json.dumps(pinned))
        def measure(role,count):
            args=[n,k,count] if b in ('gix_caller','ckb_caller') else [n,count,k]
            if not k:args=args[:2]
            return float(subprocess.check_output([str(paths[role]),*map(str,args)],text=True))
        count=max(128,min(6000000,round(12500000/max(0.5,measure('published',5000)))))
        rng=random.Random(168277+137*i+replica*2383+(p=='thin')*181)
        raw=[]
        for j in range(20):
            order=list(labels);rng.shuffle(order);s={role:[] for role in order}
            for role in order+order[::-1]:s[role].append(measure(role,count))
            raw.append({role:statistics.mean(arr) for role,arr in s.items()})
        data={x:report([row[v]/row[u] for row in raw]) for x,u,v in [('change','published','latest'),('old_control','published','published-again'),('new_control','latest','latest-again')]}
        data['median_ns']=[round(statistics.median(r[role] for r in raw),3) for role in ('published','latest')]
        data['raw']=raw;summary[key]=data
        (out/'summary.json').write_text(json.dumps(summary));print(key,data['change'],data['old_control'][0],data['new_control'][0],data['median_ns'],flush=True)
