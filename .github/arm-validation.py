import hashlib,io,json,math,os,random,shutil,statistics,subprocess,sys,tarfile
from pathlib import Path
root=Path.cwd();work=root/"work";api=work/"lib";app=work/"app";(app/"src").mkdir(parents=True)
results=root/"results";results.mkdir()
shutil.copyfile(root/".github/validate-probe.rs",app/"src/main.rs")
(app/"Cargo.toml").write_text('[package]\nname="validation-caller"\nversion="0.1.0"\nedition="2021"\n[workspace]\n[dependencies]\nfaster-hex={path="../lib"}\n')
def out(args,wd=root,env=None):return subprocess.check_output(args,cwd=wd,env=env,text=True).strip()
(results/"host.txt").write_text(out(["lscpu"])+"\n"+out(["rustc","-Vv"]))
refs={"a":"25cfd8eb6a4cd8257a96fabaf73771cabcced4b4","b":"848c4e239714cb3e2312abb9f38c2b3679439a0a","f":"8a4064cecd2f2cf9340293d3095290c8f8b67ca7"}
images={}
for p in ("false","thin"):
    td=work/("target-"+p)
    env=dict(os.environ,CARGO_PROFILE_RELEASE_LTO=p,CARGO_TARGET_DIR=str(td))
    for k,ref in refs.items():
        if subprocess.run(["git","cat-file","-e",ref+"^{commit}"],capture_output=True).returncode:
            out(["git","fetch","--no-tags","https://github.com/"+"nervosnetwork"+"/faster-hex.git",ref])
        if api.exists():shutil.rmtree(api)
        api.mkdir()
        with tarfile.open(fileobj=io.BytesIO(subprocess.check_output(["git","archive",ref]))) as ar:ar.extractall(api,filter="data")
        if not (app/"Cargo.lock").exists():out(["cargo","generate-lockfile"],app,env)
        if td.exists():out(["cargo","clean","--release","-p","faster-hex","-p","validation-caller"],app,env)
        data=out(["cargo","build","--release","--locked","--message-format=json"],app,env)
        rows=[json.loads(x) for x in data.splitlines() if x.startswith("{")]
        assert any(x.get("reason")=="compiler-artifact" and x["target"]["name"]=="faster_hex" and not x["fresh"] for x in rows)
        prog=work/(p+"-"+k)
        shutil.copy2(td/"release/validation-caller",prog)
        images[p,k]=prog
    for k in ("a","b","f"):
        dup=work/(p+"-"+k+k);shutil.copy2(images[p,k],dup);images[p,k+k]=dup
assert "aarch64" in out(["uname","-m"])
if hasattr(os,"sched_getaffinity"):os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
(results/"hashes.json").write_text(json.dumps({p+"/"+k:hashlib.sha256(im.read_bytes()).hexdigest() for (p,k),im in images.items()}))
summary={};allrows={}
for p in ("false","thin"):
    for n,name in ((8,"valid"),(32,"valid"),(4096,"valid"),(4096,"last"),(4096,"first"),(4096,"middle")):
        def run(k,i):return float(out([images[p,k],str(n),str(i),name],app))
        cnt=max(1000,min(10000000,round(15000000/max(1,run("a",12000)))))
        rng=random.Random(int(sys.argv[1])*971+len(allrows)*1421)
        rows=[]
        for _ in range(20):
            roles=["a","b","f","aa","bb","ff"];rng.shuffle(roles)
            obs={k:[] for k in roles}
            for k in roles+roles[::-1]:obs[k].append(run(k,cnt))
            rows.append({k:statistics.mean(v) for k,v in obs.items()})
        key=p+"/"+str(n)+"/"+name;allrows[key]=rows;summary[key]={}
        for left,right in (("a","aa"),("b","bb"),("f","ff"),("a","b"),("a","f"),("b","f")):
            v=[j[right]/j[left] for j in rows];pos=sum(x>1 for x in v)
            summary[key][right+"/"+left]=[round(100*(statistics.median(g)-1),3) for g in (v,v[:10],v[10:])]+[round(min(1,2*sum(math.comb(20,i) for i in range(min(pos,20-pos)+1))/2**20),5)]
        (results/"summary.json").write_text(json.dumps(summary,indent=2));(results/"raw.json").write_text(json.dumps(allrows))
        print(key,summary[key]["f/b"],flush=True)
