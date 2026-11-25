"""Compare linked x86 code bytes, including padding, at their actual addresses."""
import hashlib
import struct
import subprocess


def sections(binary):
    image = binary.read_bytes()
    header = struct.unpack_from("<16s2HI3QI6H", image)
    assert image.startswith(b"\x7fELF\x02\x01")
    table, size, count, names = header[6], header[11], header[12], header[13]
    rows = [struct.unpack_from("<IIQQQQIIQQ", image, table + i * size) for i in range(count)]
    names = rows[names][4]
    result = {}
    for index, kind, flags, address, start, length, *_ in rows:
        if flags & 2 and kind != 8:
            key = image[names + index:image.index(b"\0", names + index)].decode()
            result[key] = (address, image[start:start + length])
    return result


def functions(binary):
    text = subprocess.check_output(["nm", "-S", "-n", "--defined-only", str(binary)], text=True)
    funcs = {}
    for line in text.splitlines():
        fields = line.split(maxsplit=3)
        if len(fields) == 4 and fields[2] in ("T", "t", "W", "w"):
            addr, size, _, name = fields
            funcs.setdefault(name, []).append((int(addr, 16), int(size, 16)))
    return funcs


def compare(base, other):
    sections_a, sections_b = sections(base), sections(other)
    a, b = functions(base), functions(other)
    addr_a, data_a = sections_a[".text"]
    addr_b, data_b = sections_b[".text"]
    probes_a = {k: v for k, v in a.items() if "faster_hex" in k and "support_no_cache_x86" in k}
    probes_b = {k: v for k, v in b.items() if "faster_hex" in k and "support_no_cache_x86" in k}
    skip = set()
    for group in (probes_a, probes_b):
        for symbols in group.values():
            for start, length in symbols:
                skip.update(range(start, (start + length + 15) // 16 * 16))
    changed_other = sum(x != y and addr_a + i not in skip for i, (x, y) in enumerate(zip(data_a, data_b)))
    moved = sum([addr for addr, _ in a[k]] != [addr for addr, _ in b[k]] for k in a.keys() & b.keys())
    return {
        "base_text": [addr_a, len(data_a)], "other_text": [addr_b, len(data_b)],
        "base_probes": probes_a, "other_probes": probes_b,
        "shared_function_names": len(a.keys() & b.keys()), "addresses_differ": moved,
        "function_names_only_one_side": len(a.keys() ^ b.keys()),
        "differing_bytes_outside_probes": changed_other if addr_a == addr_b and len(data_a) == len(data_b) else None,
        "equal_excluding_probe_slots": addr_a == addr_b and len(data_a) == len(data_b) and changed_other == 0,
        "different_allocated_sections": sorted(k for k in sections_a.keys() | sections_b.keys()
                                              if sections_a.get(k) != sections_b.get(k)),
        "text_sha256": [hashlib.sha256(d).hexdigest() for d in (data_a, data_b)],
    }
