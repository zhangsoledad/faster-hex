"""Isolate the 64-digit validation result in the original Criterion consumer."""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import sys
import tarfile

replica = int(sys.argv[1])
root = Path.cwd()
work = root / "study"
source = work / "source"
results = work / "results"
results.mkdir(parents=True)
base = "25cfd8eb6a4cd8257a96fabaf73771cabcced4b4"
head = "848c4e239714cb3e2312abb9f38c2b3679439a0a"
env = dict(os.environ, CARGO_TARGET_DIR=str(work / "target"))

def run(args, cwd=root, **kw):
    return subprocess.check_output(args, cwd=cwd, env=env, text=True, **kw)

def extract(ref):
    if subprocess.run(["git","cat-file","-e",ref+"^{commit}"],capture_output=True).returncode:
        run(["git","fetch","--no-tags","https://github.com/nervosnetwork/faster-hex.git",ref])
    if source.exists():
        shutil.rmtree(source)
    source.mkdir()
    data = subprocess.check_output(["git","archive",ref])
    with tarfile.open(fileobj=io.BytesIO(data)) as ar:
        ar.extractall(source, filter="data")

def binary(tag, ref):
    extract(ref)
    if (work / "Cargo.lock").exists():
        shutil.copyfile(work / "Cargo.lock", source / "Cargo.lock")
    else:
        run(["cargo","generate-lockfile"],source)
        shutil.copyfile(source / "Cargo.lock",work / "Cargo.lock")
    if tag == "a":
        shutil.copytree(source / "benches",work / "benches")
    else:
        shutil.copytree(work / "benches",source / "benches",dirs_exist_ok=True)
    if tag in ("nospecial","narrow","old512","shared","oldfast"):
        f = source / "src/decode/validate.rs"
        s = f.read_text()
        at = s.index("unsafe fn check_mixed_avx512<const _WIDTH: usize>")
        begin = s.index("    if len == 64 {",at)
        end = s.index("    if len < 64 {",begin)
        if tag == "nospecial": s = s[:begin]+s[end:]
        if tag == "narrow": s = s[:begin]+"    if len == 64 { return check_mixed_avx2::<32>(src); }\n"+s[end:]
        if tag == "old512":
            old = "unsafe { check_mixed_avx512::<64>(src) }"
            assert s.count(old)==1
            s = s.replace(old,"unsafe { super::x86::hex_check_avx512_with_case(src, CheckCase::None) }")
        if tag == "shared":
            tail=s.index("    let (blocks, tail)",end)
            close=s.index("\n}",tail)
            s=s[:begin]+s[end:tail]+"    super::x86::hex_check_avx512_with_case(src, CheckCase::None)"+s[close:]
        if tag == "oldfast":
            v=source/"src/decode.rs"
            t=v.read_text()
            assert t.count("if validate::check_mixed(src) {")==1
            v.write_text(t.replace("if validate::check_mixed(src) {","if hex_check(src) {"))
        f.write_text(s)
    if tag in ("lookup","sat","decode","decode_all"):
        f=source/"src/decode/validate.rs"
        s=f.read_text()
        start=s.index("    if len == 64 {",s.index("unsafe fn check_mixed_avx512<const"))
        at=s.index("        return valid_avx512_mixed(_mm512_loadu_si512(src.as_ptr().cast()));",start)
        original=s[at:s.index("\n",at)]
        methods={
            "lookup": """let low = _mm_setr_epi8(1,3,3,3,3,3,3,1,1,1,0,0,0,0,0,0);
        let high = _mm_setr_epi8(0,0,0,1,2,0,2,0,0,0,0,0,0,0,0,0);
        let tags = _mm512_shuffle_epi8(_mm512_broadcast_i32x4(low), bytes);
        let hi = _mm512_and_si512(_mm512_srli_epi16::<4>(bytes), _mm512_set1_epi8(15));
        let ranges = _mm512_shuffle_epi8(_mm512_broadcast_i32x4(high), hi);
        return _mm512_testn_epi8_mask(tags,ranges)==0;""",
            "sat": """let digit = _mm512_subs_epu8(_mm512_sub_epi8(bytes,_mm512_set1_epi8(b'0' as i8)),_mm512_set1_epi8(9));
        let fold = _mm512_or_si512(bytes,_mm512_set1_epi8(0x20));
        let letter = _mm512_subs_epu8(_mm512_sub_epi8(fold,_mm512_set1_epi8(b'a' as i8)),_mm512_set1_epi8(5));
        let bad = _mm512_min_epu8(digit,letter);
        return _mm512_test_epi8_mask(bad,bad)==0;""",
            "decode": """let (_, checked) = super::x86::decode_avx512_nibbles(bytes,CheckCase::None);
        return _mm512_movepi8_mask(checked)==0;""",
        }
        if tag=="decode_all":
            first=s.index("    let digit =",s.index("unsafe fn valid_avx512_mixed"))
            last=s.index("\n}",first)
            s=s[:first]+methods["decode"].replace("return ","").rstrip(";")+s[last:]
        else:
            s=s[:at]+s[at:].replace(original,"        let bytes = _mm512_loadu_si512(src.as_ptr().cast());\n        "+methods[tag],1)
        f.write_text(s)
    # Source revisions deliberately share a checkout path, dependency artifacts and lock.
    run(["cargo","clean","--release","-p","faster-hex"], source)
    compiled = run(["cargo","bench","--locked","--bench","check","--no-run","--message-format=json"],source)
    objs=[json.loads(line) for line in compiled.splitlines() if line.startswith("{")]
    exe,=[x["executable"] for x in objs if x.get("executable") and x["target"]["name"]=="check"]
    assert any(x.get("reason")=="compiler-artifact" and x["target"]["name"]=="faster_hex" and not x["fresh"] for x in objs)
    path=work/tag
    shutil.copy2(exe,path)
    asm = run(["objdump","-d","--demangle","--no-show-raw-insn",str(path)])
    pieces=[chunk for chunk in asm.split("\n\n") if chunk and any(name in chunk.splitlines()[0] for name in ("check_mixed_avx512","hex_check_avx512_with_case","check_mixed_avx2"))]
    (results/(tag+".asm")).write_text("\n\n".join(pieces))
    if tag in ("lookup","sat","decode","decode_all"):
        with (source/"src/tests.rs").open("a") as tests:
            tests.write("""
#[test]
fn native_classification() {
    for n in [32, 64, 66, 126, 128, 130, 1024] {
        let mut input = vec![b'F'; n];
        for i in 0..n {
            for value in 0..=255u8 {
                input[i]=value;
                match crate::hex_validate(&input) {
                    Ok(()) => assert!(value.is_ascii_hexdigit()),
                    Err(crate::Error::InvalidChar { index, byte }) => {
                        assert!(!value.is_ascii_hexdigit());
                        assert_eq!((index,byte),(i,value));
                    },
                    other=>panic!("{other:?}"),
                }
            }
            input[i]=b'F';
        }
    }
}""")
        run(["cargo","test","--release","--locked","--lib","tests::native_classification","--","--exact"],source)
    return path

hardware=run(["lscpu"] if sys.platform.startswith("linux") else ["sysctl","machdep.cpu.brand_string","machdep.cpu.features","machdep.cpu.leaf7_features"])
(results/"host.txt").write_text(hardware+"\n"+run(["rustc","-Vv"]))
print(hardware,flush=True)
if "avx512bw" not in hardware.lower():
    print("Host has already-covered AVX2; skipping the AVX-512-only study.",flush=True)
    sys.exit(0)
a = binary("a",base)
b = binary("b",head)
backend = run(["cargo","test","--locked","--lib","tests::feature_detection_matches_host","--","--exact","--nocapture"],source,stderr=subprocess.STDOUT)
(results/"backend.txt").write_text(backend)
print("\n".join(l for l in backend.splitlines() if "backend" in l),flush=True)
paths={"a":a,"b":b}
if "selected backend: AVX512" in backend:
    for k in ("lookup","sat","decode","decode_all"):
        paths[k]=binary(k,head)
else:
    paths["oldfast"]=binary("oldfast",head)
for tag in ["a","b"]:
    paths[tag*2]=work/(tag*2)
    shutil.copy2(paths[tag],paths[tag*2])
hashes={k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}
assert hashes["a"]==hashes["aa"] and hashes["b"]==hashes["bb"]
(results/"binaries.json").write_text(json.dumps(hashes,indent=2))
if hasattr(os,"sched_getaffinity"):
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
rows=[]
criterion=work/"criterion"
env["CRITERION_HOME"]=str(criterion)
rng=random.Random(23977+replica*17)
def timed(tag):
    run([str(paths[tag]),"--bench","^check_valid/byte_pairs/32$","--warm-up-time","0.2","--measurement-time","0.7","--sample-size","30","--noplot"],source,stderr=subprocess.DEVNULL)
    e,=criterion.glob("**/new/estimates.json")
    return json.loads(e.read_text())["mean"]["point_estimate"]
def summarize():
    pairs=[("a","aa"),("b","bb"),("a","b")]+[(r,k) for k in paths if k not in ("a","b","aa","bb") for r in ("a","b")]
    summary={}
    for left,right in pairs:
        ratios=[r[right]/r[left] for r in rows]
        k=sum(x>1 for x in ratios)
        p=min(1.0,2*sum(math.comb(len(ratios),i) for i in range(min(k,len(ratios)-k)+1))/2**len(ratios))
        summary[right+"/"+left]=dict(median_pct=100*(statistics.median(ratios)-1),halves=[100*(statistics.median(p)-1) for p in (ratios[:len(ratios)//2],ratios[len(ratios)//2:])],slower=k,n=len(ratios),p=p, ns=[statistics.median(r[x] for r in rows) for x in (left,right)])
    return summary
for block in range(12):
    order=list(paths);rng.shuffle(order)
    samples={k:[] for k in paths}
    for tag in order+order[::-1]: samples[tag].append(timed(tag))
    rows.append({k:statistics.mean(s) for k,s in samples.items()})
    (results/"raw.json").write_text(json.dumps(rows))
    print("finished block",block+1,flush=True)
print(json.dumps(summarize(),indent=2),flush=True)
(results/"summary.json").write_text(json.dumps(summarize(),indent=2))
