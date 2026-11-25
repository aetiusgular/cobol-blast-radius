#!/usr/bin/env python3
"""P5 eval: E0 and E1 on the frozen split, the repeat check, and the results tables.

    python3 -I scripts/p5-eval.py release          # once per release: E0 and E1 on dev and heldout
    python3 -I scripts/p5-eval.py repeat --tag T   # E0 and E1 on dev again, compared with the release rows
    python3 -I scripts/p5-eval.py summary          # results/summary.md from the release rows

`release` writes results/E<k>-<split>.jsonl (contracts/eval.md) and
results/P5-release.json, and refuses to run when any of those already hold
rows: heldout runs once per release (eval.md rule 2). `repeat` writes
results/P5-<tag>-E<k>-dev.jsonl, fresh files so the tree stays clean for the
next run's git_dirty, and fails unless every row matches the release row of
the same change apart from run_id, date, git_sha, git_dirty and machine
(eval.md rule 4: no model, so a repeat must be identical). It also fails when
the scored code differs from the code the release ran (code_digest below).
The repeat runs dev only, so heldout is looked at once.

Ground truth is the GnuCOBOL harness (groundtruth/), the prediction is the
graph (radius/); this script joins them only through approval.cli and
approval.evalrun, as `python3 -m approval.cli eval` does.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from approval import cli, evalrun  # noqa: E402

RESULTS = REPO / "results"
RELEASE = RESULTS / "P5-release.json"
ROOT = REPO / "vendor" / "carddemo"
RUNSET = REPO / "contracts" / "runset.json"
SPLIT = REPO / "contracts" / "split.jsonl"
EVAL_DOC = REPO / "contracts" / "eval.md"
PREDICTORS = (("E0", "e0"), ("E1", "full"))
VOLATILE = ("run_id", "date", "git_sha", "git_dirty", "machine")
# What decides a score: both lanes, the runner, the contracts and run set,
# the fixtures and the scripts (this one included). Docs and results are not in it.
CODE_PATHS = ("groundtruth", "radius", "approval", "contracts", "fixtures", "scripts")


def code_digest():
    """sha256 over (path, sha256 of bytes) of every tracked file under CODE_PATHS."""
    out = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(REPO), "ls-files", "-z", "--", *CODE_PATHS],
                         capture_output=True, check=True).stdout
    h = hashlib.sha256()
    for rel in sorted(p for p in out.decode().split("\0") if p):
        h.update(rel.encode() + b"\0" + hashlib.sha256((REPO / rel).read_bytes()).hexdigest().encode() + b"\n")
    return h.hexdigest()


def run_one(split, predictor, out):
    runset = json.loads(RUNSET.read_text())
    predict = cli._predictor(predictor == "e0")
    work = Path(tempfile.mkdtemp(prefix=f"cbr-p5-{predictor}-{split}-"))
    rows = evalrun.run(split, SPLIT, EVAL_DOC, ROOT, runset, out,
                       lambda ch: predict(ch, ROOT, runset), cli.harness_ground_truth(ROOT, runset, work))
    s = rows[-1]
    print(f"{out.name}: {s['predictor']} {split} recall={s['recall']} precision={s['precision']} "
          f"hits={s['hits']} changed={s['changed_count']} predicted={s['predicted_count']} run_id={s['run_id']}")
    return rows


def read_rows(path):
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()] if path.exists() else []


def first_run(path):
    """Rows of the first run in a results file (a later run appends beside it)."""
    rows = read_rows(path)
    if not rows:
        return []
    rid = rows[0]["run_id"]
    return [r for r in rows if r["run_id"] == rid]


def release(_a):
    targets = [RESULTS / f"{k}-{s}.jsonl" for k, _ in PREDICTORS for s in evalrun.SPLITS]
    held = [p.name for p in targets + [RELEASE] if p.exists() and p.stat().st_size]
    if held:
        print(f"p5-eval: release rows already exist ({', '.join(held)}); heldout runs once per release",
              file=sys.stderr)
        return 2
    sha, dirty = evalrun.git_state()
    if dirty:
        print("p5-eval: the tree has uncommitted changes; a release run needs a clean commit", file=sys.stderr)
        return 2
    digest = code_digest()
    runs = {}
    for k, pred in PREDICTORS:
        for split in evalrun.SPLITS:
            runs[f"{k}-{split}"] = run_one(split, pred, RESULTS / f"{k}-{split}.jsonl")[-1]["run_id"]
    RELEASE.write_text(json.dumps({"git_sha": sha, "code_digest": digest, "code_paths": list(CODE_PATHS),
                                   "runs": runs}, indent=2, sort_keys=True) + "\n")
    write_summary()
    return 0


def strip(row):
    return {k: v for k, v in row.items() if k not in VOLATILE}


def compare(ref, new):
    """Differences between two runs' rows, matched by change id (the summary row by kind)."""
    key = lambda r: r.get("change_id") or r["kind"]  # noqa: E731
    a, b = {key(r): strip(r) for r in ref}, {key(r): strip(r) for r in new}
    probs = [f"{k}: only in the release run" for k in sorted(a.keys() - b.keys())]
    probs += [f"{k}: only in the repeat" for k in sorted(b.keys() - a.keys())]
    for k in sorted(a.keys() & b.keys()):
        diff = sorted(f for f in a[k].keys() | b[k].keys() if a[k].get(f) != b[k].get(f))
        if diff:
            probs.append(f"{k}: {', '.join(diff)} differ")
    return probs


def repeat(a):
    if not RELEASE.exists():
        print("p5-eval: no results/P5-release.json; run `release` first", file=sys.stderr)
        return 2
    rel = json.loads(RELEASE.read_text())
    digest = code_digest()
    checks = []
    checks.append(("scored code matches the release's", digest == rel["code_digest"],
                   f"{digest[:16]} vs {rel['code_digest'][:16]}"))
    for k, pred in PREDICTORS:
        ref = first_run(RESULTS / f"{k}-dev.jsonl")
        out = RESULTS / f"P5-{a.tag}-{k}-dev.jsonl"
        if out.exists():
            out.unlink()  # a rerun of the same tag replaces its own file, never a release file
        new = run_one("dev", pred, out)
        probs = compare(ref, new) if ref else ["no release rows to compare with"]
        checks.append((f"{k} dev repeat ({len(new) - 1} changes) identical to release run {ref[0]['run_id'] if ref else '-'}",
                       not probs, "; ".join(probs[:5]) or "identical apart from " + ", ".join(VOLATILE)))
    write_summary(a.tag, checks)
    ok = all(c[1] for c in checks)
    for name, good, note in checks:
        print(f"{'ok  ' if good else 'FAIL'} {name}: {note}")
    print(f"p5-eval: repeat {'passed' if ok else 'FAILED'}")
    return 0 if ok else 1


# ---------------------------------------------------------------- tables
def _f(x):
    return "—" if x is None else f"{x:.3f}"


def write_summary(tag=None, checks=None):
    runs = {f"{k}-{s}": first_run(RESULTS / f"{k}-{s}.jsonl") for k, _ in PREDICTORS for s in evalrun.SPLITS}
    L = ["## cobol-blast-radius P5: blast radius against GnuCOBOL output diffs", ""]
    any_row = next((r for rs in runs.values() for r in rs), None)
    if any_row:
        L += [f"Release rows: git `{any_row['git_sha'][:12]}`, CardDemo `{any_row['carddemo_commit'][:8]}`, "
              f"`{any_row['cobc_version']}`, machine `{any_row['machine']}`, {any_row['date'][:10]}. "
              "No model. Unit: (change, output dataset) pairs, micro averaged. Every table stands alone.", ""]
    L += ["### 1. Recall and precision", "",
          "| run | split | changes | scored | changed | predicted | hits | recall | precision | run_id |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for name, rows in runs.items():
        if rows:
            s = rows[-1]
            L.append(f"| {name.split('-')[0]} ({s['predictor']}) | {s['split']} | {s['changes']} | {s['scored']} | "
                     f"{s['changed_count']} | {s['predicted_count']} | {s['hits']} | {_f(s['recall'])} | "
                     f"{_f(s['precision'])} | `{s['run_id']}` |")
    L += ["", "### 2. Per change class", "",
          "| run | split | class | scored | changed | predicted | hits | recall | precision |",
          "|---|---|---|---|---|---|---|---|---|"]
    for name, rows in runs.items():
        if rows:
            s = rows[-1]
            for c, t in s["per_class"].items():
                L.append(f"| {name.split('-')[0]} | {s['split']} | {c} | {t['scored']} | {t['changed_count']} | "
                         f"{t['predicted_count']} | {t['hits']} | {_f(t['recall'])} | {_f(t['precision'])} |")
    L += ["", "### 3. No-op controls (correct = nothing changed and nothing predicted)", "",
          "| run | split | correct | incorrect | excluded | incorrect ids |", "|---|---|---|---|---|---|"]
    for name, rows in runs.items():
        if rows:
            s = rows[-1]
            n = s["noop"]
            L.append(f"| {name.split('-')[0]} | {s['split']} | {n['correct']} | {n['incorrect']} | {n['excluded']} | "
                     f"{', '.join(n['ids_incorrect']) or '—'} |")
    L += ["", "### 4. Misses, false alarms, exclusions", "",
          "| run | split | changes with a miss | missed pairs | false-alarm pairs | excluded (reason: n) | "
          "predicted outside the output universe | unverifiable (CICS or not in the run set) | predict errors |",
          "|---|---|---|---|---|---|---|---|---|"]
    for name, rows in runs.items():
        if rows:
            s, ch = rows[-1], [r for r in rows if r["kind"] == "change"]
            miss = [r for r in ch if r["false_negative"]]
            L.append(f"| {name.split('-')[0]} | {s['split']} | {len(miss)} | {sum(len(r['false_negative']) for r in ch)} | "
                     f"{sum(len(r['false_positive']) for r in ch)} | "
                     f"{', '.join(f'{k}: {v}' for k, v in s['excluded_by_reason'].items()) or '0'} | "
                     f"{s['predicted_outside_universe']} | {sum(len(r.get('unverifiable') or []) for r in ch)} | "
                     f"{s['predict_errors']} |")
    L += ["", "Table 3 of SPEC.md (\"reachable but unchanged\", split into \"path not exercised\" and "
          "\"change is equivalent\") is not produced: the harness gives a byte diff and cannot tell the two "
          "apart, so false alarms are counted only as one column above."]
    if checks is not None:
        L += ["", f"### 5. Repeat run `{tag}` (eval.md rule 4)", "", "| check | result | note |", "|---|---|---|"]
        L += [f"| {n} | {'pass' if g else 'FAIL'} | {note} |" for n, g, note in checks]
    (RESULTS / "summary.md").write_text("\n".join(L) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("release")
    r = sub.add_parser("repeat")
    r.add_argument("--tag", required=True, choices=["repeat", "box"])
    sub.add_parser("summary")
    a = p.parse_args()
    if not (ROOT / "app").is_dir():
        print(f"p5-eval: no CardDemo checkout at {ROOT}", file=sys.stderr)
        return 3
    if a.cmd == "summary":
        write_summary()
        return 0
    return {"release": release, "repeat": repeat}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
