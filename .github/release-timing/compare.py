"""Compare the 2.0 sources and PR 77 at one package identity, path, core and lockfile."""
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import tempfile

BASE = "6d84260fe321669e7f93ecfb8aecb4db0f582f14"
HEAD = "ca43f97fdde37c3b14882644c74469e78d6bce05"
ROOT = Path.cwd()
TOOLS = ROOT / ".github/release-timing"
REPORT = ROOT / "release-report"
CASES = {
    "hex": [f"{op}/{n}" for n in (32, 4096) for op in (
        "encode/faster_hex", "decode/faster_hex_mixed"
    )] + ["decode_array/faster_hex/32"],
    "serde": [f"serde_json/{op}/{n}" for n in (32, 4096)
              for op in ("serialize_reuse", "deserialize", "deserialize_escaped")],
}
DRIVERS = [*CASES, "array_read_slice"]


def archive(revision, dest, *paths):
    data = subprocess.check_output(["git", "archive", revision, *paths], cwd=ROOT)
    subprocess.run(["tar", "-xf", "-", "-C", str(dest)], input=data, check=True)


def build(work):
    project = work / "project"
    project.mkdir()
    archive(BASE, project)
    manifest = subprocess.check_output(["git", "show", HEAD + ":Cargo.toml"], cwd=ROOT)
    assert b'version = "2.1.0"' in manifest
    (project / "Cargo.toml").write_bytes(
        manifest + b'\n[[bench]]\nname = "array_read_slice"\nharness = false\n'
    )
    shutil.copyfile(TOOLS / "release.lock", project / "Cargo.lock")
    shutil.copyfile(TOOLS / "array_read_slice.rs", project / "benches/array_read_slice.rs")
    env = dict(os.environ, CARGO_TARGET_DIR=str(work / "target"))
    for role, rev in (("base", BASE), ("head", HEAD)):
        if role == "head":
            (project / "src").rename(work / "baseline-src")
            archive(rev, project, "src")
            for source in (project / "src").rglob("*.rs"):
                source.touch()
        args = ["cargo", "bench", "--locked", "--no-run", "--message-format=json-render-diagnostics"]
        for name in DRIVERS:
            args.extend(["--bench", name])
        output = subprocess.check_output(args, cwd=project, env=env, text=True)
        rows = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
        artifacts = {r["target"]["name"]: r for r in rows if r.get("reason") == "compiler-artifact"
                     and r["target"]["kind"] == ["bench"] and r.get("executable")}
        assert set(artifacts) == set(DRIVERS) and all(not a["fresh"] for a in artifacts.values())
        dest = work / role
        dest.mkdir()
        for name, item in artifacts.items():
            shutil.copy2(item["executable"], dest / name)
        print(role, rev, "built at", project, flush=True)


def measure(work, role):
    points = {}
    estimates = work / "criterion"
    env = dict(os.environ, CRITERION_HOME=str(estimates), RAYON_NUM_THREADS="1")
    for name in DRIVERS:
        slot = work / ("run-" + name)
        # Overwrite the same file in-place so each variant gets the same invocation path and inode.
        if not slot.exists():
            slot.touch(mode=0o755)
        with slot.open("r+b") as out, (work / role / name).open("rb") as binary:
            shutil.copyfileobj(binary, out)
            out.truncate()
        if name == "array_read_slice":
            for n, iterations in ((32, 250000), (4096, 6000)):
                for form in ("plain", "escaped"):
                    key = f"serde_array/{form}/{n}"
                    points[key] = float(subprocess.check_output(
                        [str(slot), str(n), str(iterations), form], env=env, text=True))
            continue
        cases = CASES[name]
        expr = "^(" + "|".join(cases) + ")$"
        proc = subprocess.run([str(slot), expr, "--bench", "--noplot", "--warm-up-time", "0.15",
                               "--measurement-time", "0.40", "--sample-size", "20", "--nresamples", "1500"],
                              env=env, cwd=work, capture_output=True, text=True)
        if proc.returncode:
            raise RuntimeError(proc.stderr[-2500:])
        for case in cases:
            data = json.loads((estimates / case / "new/estimates.json").read_text())
            points[case] = data["median"]["point_estimate"]
    shutil.rmtree(estimates)
    return points


def main():
    REPORT.mkdir()
    with tempfile.TemporaryDirectory(prefix="hex21-") as tmp:
        work = Path(tmp)
        build(work)
        cpu = min(os.sched_getaffinity(0))
        os.sched_setaffinity(0, {cpu})
        model = next(line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                     if line.startswith("model name"))
        data = {"base": BASE, "head": HEAD, "cpu": model, "core": cpu,
                "lto": os.environ["CARGO_PROFILE_BENCH_LTO"], "blocks": []}
        for order in ["bhhb", "hbbh", "hbbh", "bhhb"] * 3:
            block = [(key, measure(work, "base" if key == "b" else "head")) for key in order]
            data["blocks"].append(block)
            (REPORT / "samples.json").write_text(json.dumps(data))
            print(model, "paired block", len(data["blocks"]), "of 12", flush=True)
    results = {}
    for case in data["blocks"][0][0][1]:
        ratios = []
        repeat = []
        for block in data["blocks"]:
            b, h = ([row[case] for key, row in block if key == side] for side in "bh")
            ratios.append(math.sqrt(h[0] * h[1] / (b[0] * b[1])))
            repeat.extend((abs(math.log(b[0] / b[1])), abs(math.log(h[0] / h[1]))))
        results[case] = {"delta_percent": round(100 * (statistics.median(ratios) - 1), 3),
                         "blocks_slower": sum(x > 1 for x in ratios),
                         "within_build_repeat_percent": round(100 * math.expm1(statistics.median(repeat)), 3)}
    print(json.dumps(results, indent=2), flush=True)
    (REPORT / "summary.json").write_text(json.dumps({"cpu": model, "results": results}))


if __name__ == "__main__":
    main()
