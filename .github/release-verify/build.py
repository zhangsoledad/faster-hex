import hashlib,json,os,shutil,subprocess,sys,tarfile,tomllib
from pathlib import Path
root=Path.cwd(); tools=Path(__file__).resolve().parent
head='8a4064cecd2f2cf9340293d3095290c8f8b67ca7'
release='e4ede54fe330383a5de28c0a1f06668ff9dbf06c8094e1c5150c39488a5e911d'
prof=sys.argv[1]
assert prof in ('default','thin')
app=root/'caller'; src=root/'package-source';vendor=root/'vendor'
(app/'src/bin').mkdir(parents=True);shutil.copytree(tools/'bin',app/'src/bin',dirs_exist_ok=True)
template=(tools/'Cargo.toml').read_text();lock=(tools/'Cargo.lock').read_text()
oldck,=[x['checksum'] for x in tomllib.loads(lock)['package'] if x['name']=='faster-hex' and x['version']=='2.1.0']
def resolve(ver,ck):
    (app/'Cargo.toml').write_text(template.replace('"=2.1.0"','"='+ver+'"'))
    (app/'Cargo.lock').write_text(lock.replace('name = "faster-hex"\nversion = "2.1.0"','name = "faster-hex"\nversion = "'+ver+'"').replace('"faster-hex 2.1.0"','"faster-hex '+ver+'"').replace(oldck,ck))
def run(args,path=app,env=None):return subprocess.check_output(args,cwd=path,env=env,text=True)
resolve('2.0.0',release)
run(['cargo','vendor','--locked','--versioned-dirs',str(vendor)])
assert json.loads((vendor/'faster-hex-2.0.0/.cargo-checksum.json').read_text())['package']==release
run(['git','clone','--quiet','--local','--no-checkout',str(root),str(src)],root)
run(['git','switch','--quiet','--detach',head],src)
run(['cargo','package','--quiet','--no-verify'],src)
pkg=src/'target/package/faster-hex-2.1.0.crate'
with tarfile.open(pkg) as ar:ar.extractall(vendor,filter='data')
dest=vendor/'faster-hex-2.1.0'
assert json.loads((dest/'.cargo_vcs_info.json').read_text())['git']['sha1']==head
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
ck=digest(pkg);files={p.relative_to(dest).as_posix():digest(p) for p in dest.rglob('*') if p.is_file()}
(dest/'.cargo-checksum.json').write_text(json.dumps({'package':ck,'files':files}))
target=root/'consumer-build';env=dict(os.environ,CARGO_TARGET_DIR=str(target),CARGO_INCREMENTAL='0')
if prof=='thin':env['CARGO_PROFILE_RELEASE_LTO']='thin'
else:env.pop('CARGO_PROFILE_RELEASE_LTO',None)
cargo=['cargo','--config','source.crates-io.replace-with="release-check"','--config','source.release-check.directory='+json.dumps(str(vendor))]
images=root/'images'/prof;images.mkdir(parents=True)
for role,ver,checksum in [('published','2.0.0',release),('latest','2.1.0',ck)]:
    resolve(ver,checksum)
    graph=json.loads(run(cargo+['metadata','--format-version=1','--offline','--locked'],env=env))
    own,=[p for p in graph['packages'] if p['name']=='faster-hex' and p['version']==ver]
    assert own['source'].startswith('registry+') and Path(own['manifest_path']).parent==vendor/('faster-hex-'+ver)
    ids={row['id'] for row in graph['resolve']['nodes'] if own['id'] in row['dependencies']}
    assert {'real-hex-consumers','ckb-jsonrpc-types','gix-hash'} <= {p['name'] for p in graph['packages'] if p['id'] in ids}
    args=cargo+['build','--locked','--offline','--release','--quiet']
    run(args+['--bins'],env=env)
    if role=='latest':
        # Only the public prefix driver uses the adoption patch. All other binaries were already linked.
        run(['git','apply',str(tools/'gix-public.patch')],root/'gitoxide')
        run(args+['--bin','public_prefix'],env=env)
    for f in sorted((tools/'bin').glob('*.rs')):shutil.copy2(target/'release'/f.stem,images/(role+'-'+f.stem))
print('Verified two registry packages and downstream dependency selection',prof,release,ck)
with tarfile.open(root/(prof+'.tgz'),'w:gz',compresslevel=1) as ar:ar.add(images,arcname='images/'+prof)
