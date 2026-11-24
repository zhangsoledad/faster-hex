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
    return path
