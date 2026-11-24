from pathlib import Path
import subprocess
from cross_file_copies import crossover
root=Path.cwd()
dest=root/'samples'
dest.mkdir()
(dest/'host.txt').write_text(subprocess.check_output(['lscpu'],text=True))
paths=[root/'images/thin'/(v+'-full_buffer') for v in ('published','latest')]
crossover(paths,root/'same-executable',root,dest,[(32,'buffer'),(4096,'buffer')])
