#!/usr/bin/env python3
"""Change only one link input's order. Choose by addresses, never by timings."""
from pathlib import Path
import hashlib,json,os,re,shlex,shutil,subprocess as sp,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from cause_common import section
cc=os.environ['ENCODING_CC']
args=sys.argv[1:]
argv=[v for arg in args for v in (shlex.split(Path(arg[1:]).read_text()) if arg.startswith('@') else [arg])]
if '-o' not in argv or not Path(argv[argv.index('-o')+1]).name.startswith('full_buffer-'):
    os.execv(cc,[cc,*args])
target=Path(argv[argv.index('-o')+1])
root=Path(os.environ['ENCODING_LAB']); role=os.environ['ENCODING_ROLE']
out=root/'relocations'/role;out.mkdir(parents=True,exist_ok=True)
refs=root/'references/images/thin'
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def symbols(file):
    text=sp.check_output(['nm','-nS','-C','--defined-only',file],text=True)
    found={}
    for line in text.splitlines():
        m=re.match(r'^([\da-f]+) ([\da-f]+) [tT] (.+)$',line)
        if not m:continue
        address,size,name=m.groups();name=re.sub(r'::h[\da-f]{16}$','',name)
        if name.startswith('faster_hex::encode::hex_encode_avx2'):key='avx'
        elif name=='full_buffer::main':key='main'
        elif name.startswith('full_buffer::main::'):key='loop'
        elif name=='__rustc::__rust_alloc':key='alloc'
        elif name=='__rustc::__rust_realloc':key='realloc'
        else:continue
        assert key not in found,(key,name)
        found[key]=[int(address,16),int(size,16)]
    assert set(found)=={'avx','main','loop','alloc','realloc'},found
    return found
def invoke(seq):sp.run([cc,*seq],check=True)
invoke(args)
native=out/'native';shutil.copy2(target,native)
positions=symbols(native)
reference=refs/(role+'-full_buffer')
assert section(native)==section(reference) and section(native,'.rodata')==section(reference,'.rodata'),(role,section(native),section(reference))
other='latest' if role=='published' else 'published'
goal=symbols(refs/(other+'-full_buffer'))
objects=[arg for arg in argv if arg.endswith('.o') and Path(arg).is_file()]
raw=sp.check_output(['nm','-A','-C','--defined-only',*objects],text=True)
owners={line.split(':',1)[0] for line in raw.splitlines() if re.search(r'\b[TtWw]\s+(?:__rustc::)?__rust_(?:re)?alloc$',line)}
assert len(owners)==1,('allocator object not unique',owners,objects)
alloc=owners.pop();assert alloc in objects
remaining=[arg for arg in argv if arg!=alloc]
all_positions=[(remaining.index(obj),obj) for obj in objects if obj!=alloc]
# Try natural crate-boundary anchors first, falling back to remaining object slots.
def priority(item):
    _,obj=item
    for i,tag in enumerate(('.addr2line-','.adler2-','.alloc-','.faster_hex-','.core-')):
        if tag in Path(obj).name:return i
    return 8
all_positions.sort(key=priority)
manifest={'native':positions,'goal':goal,'native_sha':digest(native),'native_matches_reference_text':True,'allocator':Path(alloc).name,'trials':[]}
selected=None
for where,anchor in all_positions:
    moved=remaining[:where]+[alloc]+remaining[where:]
    if moved==argv:continue
    invoke(moved)
    syms=symbols(target)
    matches=all(syms[k]==goal[k] for k in ('avx','main','loop'))
    manifest['trials'].append([Path(anchor).name,syms['avx'][0],syms['alloc'][0],matches])
    if matches and (not selected or syms['alloc']==goal['alloc']):
        selected=syms
        shutil.copy2(target,out/'swapped')
        manifest.update(swapped=syms,anchor=Path(anchor).name,unmodified_input_count=len(objects),rodata_unchanged=section(native,'.rodata')==section(target,'.rodata'))
        if syms['alloc']==goal['alloc'] and syms['realloc']==goal['realloc']:break
(out/'layout.json').write_text(json.dumps(manifest,indent=2))
print('layout',role,positions,'->',selected,file=sys.stderr)
assert selected,('no requested layout',manifest)
shutil.copy2(native,target)
