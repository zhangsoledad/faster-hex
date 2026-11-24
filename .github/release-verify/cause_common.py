from pathlib import Path
import hashlib, os, struct, subprocess as sp
def sha(data):
    return hashlib.sha256(data).hexdigest()

def section(exe, name=".text"):
    data = exe.read_bytes()
    if data[:4] == b"\x7fELF":
        assert data[4:6] == b"\x02\x01"
        off, = struct.unpack_from("<Q",data,40)
        size,count,strings=struct.unpack_from("<HHH",data,58)
        rows=[struct.unpack_from("<IIQQQQIIQQ",data,off+i*size) for i in range(count)]
        stringtab=data[rows[strings][4]:rows[strings][4]+rows[strings][5]]
        for label,_,_,vma,start,length,*_ in rows:
            if stringtab[label:].split(b"\0",1)[0].decode() == name:
                return [vma,length,sha(data[start:start+length])]
    else:
        assert name==".text" and data[:4]==b"\xcf\xfa\xed\xfe"
        cursor=32
        for _ in range(struct.unpack_from("<I",data,16)[0]):
            tag,size=struct.unpack_from("<II",data,cursor)
            if tag==0x19:
                for i in range(struct.unpack_from("<I",data,cursor+64)[0]):
                    label,seg,vma,length,start=struct.unpack_from("<16s16sQQI",data,cursor+72+80*i)
                    if label.rstrip(b"\0")==b"__text" and seg.rstrip(b"\0")==b"__TEXT":
                        return [vma,length,sha(data[start:start+length])]
            cursor+=size
    raise ValueError((exe,name))

def measure(site, image, args, cwd):
    site.unlink(missing_ok=True)
    os.link(image,site)
    assert site.samefile(image)
    return float(sp.check_output([site,*map(str,args)],cwd=cwd,text=True))

def pin():
    if hasattr(os,"sched_setaffinity"):
        os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
