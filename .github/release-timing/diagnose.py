"""Isolate the cold CPU feature check at a fixed package version and toolchain."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import struct
import subprocess
import tempfile

import compare


ROLES = {
    "base": (compare.BASE, compare.BASE),
    "head": (compare.HEAD, compare.HEAD),
    "base_new": (compare.BASE, compare.HEAD),
    "head_old": (compare.HEAD, compare.BASE),
}
PAIRS = [("head", "base"), ("base_new", "base"), ("head", "head_old"),
         ("head_old", "base"), ("head", "base_new")]
CASES = {
    "hex": ["decode/faster_hex_mixed/4096"],
    "serde": [f"serde_json/{op}/{n}" for n in (32, 4096)
              for op in ("serialize_reuse", "serialize_text_reuse")]
             + ["serde_json/deserialize/4096", "serde_json/deserialize_escaped/32"],
}


def function_span(source):
    start = source.index("fn vectorization_support_no_cache_x86() -> Vectorization {")
    end = source.index("// We enable xsave so", start)
    assert source[start:end].rstrip().endswith("}")
    return start, end


def section_hashes(binary):
    image = binary.read_bytes()
    assert image[:6] == b"\x7fELF\x02\x01"
    header = struct.unpack_from("<16s2HI3QI6H", image)
    offset, size, count, names_index = header[6], header[11], header[12], header[13]
    sections = [struct.unpack_from("<IIQQQQIIQQ", image, offset + i * size) for i in range(count)]
    names = sections[names_index][4]
    result = {}
    for idx, kind, flags, addr, start, length, *_ in sections:
        if flags & 2 and kind != 8:
            name = image[names + idx:image.index(b"\0", names + idx)].decode()
            result[name] = [addr, length, hashlib.sha256(image[start:start + length]).hexdigest()]
    return result


def build(work):
    project = work / "project"
    project.mkdir()
    compare.archive(compare.BASE, project)
    manifest = subprocess.check_output(["git", "show", compare.HEAD + ":Cargo.toml"])
    (project / "Cargo.toml").write_bytes(
        manifest + b'\n[[bench]]\nname = "array_read_slice"\nharness = false\n'
    )
    shutil.copyfile(compare.TOOLS / "release.lock", project / "Cargo.lock")
    shutil.copyfile(compare.TOOLS / "array_read_slice.rs", project / "benches/array_read_slice.rs")
    for_sources = {}
    for rev in (compare.BASE, compare.HEAD):
        source = subprocess.check_output(["git", "show", rev + ":src/lib.rs"], text=True)
        a, b = function_span(source)
        for_sources[rev] = source[a:b]
    assert len(set(for_sources.values())) == 2
    layout = {}
    for role, (tree, cpu) in ROLES.items():
        if role != "base":
            (project / "src").rename(work / ("unused-before-" + role))
            compare.archive(tree, project, "src")
        lib = project / "src/lib.rs"
        old = lib.read_text()
        a, b = function_span(old)
        assert old[a:b] == for_sources[tree]
        if tree != cpu:
            lib.write_text(old[:a] + for_sources[cpu] + old[b:])
        for source in (project / "src").rglob("*.rs"):
            source.touch()
        args = ["cargo", "bench", "--locked", "--no-run", "--message-format=json-render-diagnostics"]
        for driver in compare.DRIVERS:
            args.extend(["--bench", driver])
        output = subprocess.check_output(args, cwd=project, text=True,
                                         env=dict(os.environ, CARGO_TARGET_DIR=str(work / "target")))
        rows = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
        artifacts = {r["target"]["name"]: r for r in rows if r.get("reason") == "compiler-artifact"
                     and r["target"]["kind"] == ["bench"] and r.get("executable")}
        assert set(artifacts) == set(compare.DRIVERS) and all(not r["fresh"] for r in artifacts.values())
        dest = work / role
        dest.mkdir()
        layout[role] = {}
        for name in CASES:
            binary = dest / name
            shutil.copy2(artifacts[name]["executable"], binary)
            layout[role][name] = section_hashes(binary)
            symbols = subprocess.check_output(["nm", "-n", "-S", "-C", str(binary)], text=True)
            shortlist = [line for line in symbols.splitlines() if any(term in line for term in
                         ["vectorization_support_no_cache_x86", "format_escaped_str_contents", "converts::from_utf8"])]
            print(role, name, "selected symbols", *shortlist, sep="\n", flush=True)
    (compare.REPORT / "layout.json").write_text(json.dumps(layout))
    for x,y in PAIRS:
        print(x, "/", y, {name: layout[x][name][".text"] == layout[y][name][".text"] for name in CASES}, flush=True)


def main():
    compare.REPORT.mkdir()
    with tempfile.TemporaryDirectory(prefix="hex21-") as tmp:
        work = Path(tmp)
        build(work)
        compare.DRIVERS = list(CASES)
        compare.CASES = CASES
        cpu = min(os.sched_getaffinity(0))
        os.sched_setaffinity(0, {cpu})
        model = next(line.partition(":")[2].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                     if line.startswith("model name"))
        orders = [("base", "head", "head_old", "base_new"), ("head", "base_new", "base", "head_old"),
                  ("base_new", "head_old", "head", "base"), ("head_old", "base", "base_new", "head")]
        blocks = []
        for order in orders * 3:
            blocks.append({role: compare.measure(work, role) for role in order})
            (compare.REPORT / "samples.json").write_text(json.dumps({"cpu": model, "core": cpu, "blocks": blocks}))
            print(model, "block", len(blocks), flush=True)
    results = {}
    for case in blocks[0]["base"]:
        results[case] = {}
        for x, y in PAIRS:
            d = sorted(100 * (block[x][case] / block[y][case] - 1) for block in blocks)
            results[case][x + "/" + y] = [round(statistics.median(d), 3), sum(v > 0 for v in d),
                                           round(d[2], 3), round(d[-3], 3)]
    print(json.dumps(results, indent=2), flush=True)
    (compare.REPORT / "control.json").write_text(json.dumps({"cpu": model, "results": results}))


if __name__ == "__main__":
    main()
