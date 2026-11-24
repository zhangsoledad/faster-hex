"""Run the same binaries on each CPU. All reported timings are for faster-hex."""
from pathlib import Path
import hashlib,json,math,os,random,shutil,statistics,subprocess,sys,tarfile
mode, value=sys.argv[1:]
root=Path.cwd()
names=("a","b","once","both")
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
if mode=="build":
    sys.argv[1:]=["0"]
    source=(root/".github/validation-study.py").read_text().split("hardware=run(",1)[0]
    ns={"__name__":"frozen"}
    exec(compile(source,"build-frozen-drive","exec"),ns)
    dest=root/value;dest.mkdir()
    for n in names:
        binary=ns["binary"](n,ns["base" if n=="a" else "head"])
        shutil.copy2(binary,dest/n)
    (dest/"hashes.json").write_text(json.dumps({n:digest(dest/n) for n in names}))
    with tarfile.open(root/(value+".tgz"),"w:gz",compresslevel=2) as tar:tar.add(dest,arcname=value)
    sys.exit(0)
replica=int(value)
results=root/"results"; measurement={}; out={}
if hasattr(os,"sched_getaffinity"):os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
for profile in ("thin","false"):
    with tarfile.open(root/"packaged"/(profile+".tgz")) as tar:tar.extractall(root,filter="data")
    path=root/profile
    sums=json.loads((path/"hashes.json").read_text())
    assert sums=={n:digest(path/n) for n in names}
    shutil.copyfile(path/"hashes.json",results/(profile+"-hashes.json"))
    for n in ("a","b"):shutil.copy2(path/n,path/(n+n))
    for cases,count,measurement_time in [([16,32,64,4096],10,"0.18")]:
        rng=random.Random(replica+741912+(profile=="thin")*991+cases[0])
        roles=[*names,"aa","bb"]
        rows={n:[] for n in cases}
        pattern="^check_valid/byte_pairs/("+("|".join(map(str,cases)))+")$"
        for block in range(count):
            order=roles.copy();rng.shuffle(order)
            values={n:{r:[] for r in roles} for n in cases}
            for key in order+order[::-1]:
                stats=root/"criterion";env=dict(os.environ,CRITERION_HOME=str(stats))
                subprocess.run([path/key,"--bench",pattern,"--warm-up-time","0.09","--measurement-time",measurement_time,"--sample-size","20","--nresamples","2000","--noplot"],cwd=path,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
                for n in cases:
                    est, = stats.glob(f"**/byte_pairs/{n}/new/estimates.json")
                    values[n][key].append(json.loads(est.read_text())["mean"]["point_estimate"])
            for n in cases:
                rows[n].append({r:statistics.mean(s) for r,s in values[n].items()})
                measurement[profile+"/"+str(n)]=rows[n]
            (results/"raw.json").write_text(json.dumps(measurement))
        for n,series in rows.items():
            pairs=[("a","aa"),("b","bb"),("a","b"),("a","once"),("b","once"),("a","both"),("b","both"),("once","both")]
            summary={}
            for x,y in pairs:
                scores=[entry[y]/entry[x] for entry in series];k=sum(i>1 for i in scores);h=len(series)//2
                summary[y+"/"+x]=[round(100*(statistics.median(s)-1),3) for s in (scores,scores[:h],scores[h:])]+[round(min(1,2*sum(math.comb(len(scores),i) for i in range(min(k,len(scores)-k)+1))/2**len(scores)),5)]
            out[profile+"/"+str(n)]=summary
        (results/"summary.json").write_text(json.dumps(out,indent=2))
        print(profile,cases,"finished",flush=True)
