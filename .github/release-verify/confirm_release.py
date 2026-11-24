from pathlib import Path
import hashlib,json,subprocess
from cross_file_copies import crossover
from cause_common import section
root=Path.cwd()
results=root/'cross-results'
results.mkdir()
subprocess.run(['lscpu'],stdout=(results/'host.txt').open('w'),check=True)
for profile,target,cases,last in [('thin','full_buffer',[(32,'buffer'),(4096,'buffer')],False),('default','ckb_caller',[(32,'plain')],True),('default','qualified_decode',[(4,'decode'),(8,'decode')],False)]:
    directory=root/'images'/profile
    images=[directory/(role+'-'+target) for role in ('published','latest')]
    out=results/(profile+'-'+target)
    out.mkdir()
    info={}
    for role,exe in zip(('2.0.0','pr77'),images):
        info[role]={sec:section(exe,sec) for sec in ('.text','.rodata')}
        nm=subprocess.check_output(['nm','-nC',str(exe)],text=True)
        (out/(role+'-symbols.txt')).write_text('\n'.join(l for l in nm.splitlines() if any(x in l for x in ('full_buffer::main','hex_encode','qualified_decode::main','ckb_caller::main')))+'\n')
    (out/'sections.json').write_text(json.dumps(info))
    crossover(images,root/'caller-live',root,out,cases,count_last=last)
