"""Eval runner: writes results rows (contracts/eval.md).

`run` scores a predictor against ground truth on one split. `predict(change)`
returns a radius and `ground_truth(change)` an output diff, so the runner
does not depend on how either is made. Recall and precision are micro
averages over (change, output dataset) pairs; per-class numbers and the
no-op table sit in the summary row, each as its own table, never combined.
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPLITS = ("dev", "heldout")


class SplitHashMismatch(Exception):
    pass


# ---------------------------------------------------------------- machine
def _cpu():
    try:
        with open("/proc/cpuinfo") as fh:
            for ln in fh:
                if ln.startswith("model name"):
                    return ln.split(":", 1)[1].strip()
    except OSError:
        pass
    return "unknown CPU"


def _mem():
    try:
        with open("/proc/meminfo") as fh:
            for ln in fh:
                if ln.startswith("MemTotal:"):
                    return f"{int(ln.split()[1]) / 1048576:.1f} GiB"
    except (OSError, ValueError, IndexError):
        pass
    return "unknown memory"


def _gpu():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return "no GPU"
    try:
        out = subprocess.run([exe, "--query-gpu=name", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "no GPU"
    names = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    return ", ".join(names) if out.returncode == 0 and names else "no GPU"


def machine():
    """$FORGE_MACHINE_FILE's contents when set, else `<cpu>|<MemTotal GiB>|<GPU or "no GPU">`, read now."""
    f = os.environ.get("FORGE_MACHINE_FILE")
    if f:
        return Path(f).read_text().strip()
    return f"{_cpu()}|{_mem()}|{_gpu()}"


# ---------------------------------------------------------------- provenance
def _git(*args):
    try:
        out = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def git_state():
    sha = _git("rev-parse", "HEAD") or "unknown"
    status = _git("status", "--porcelain", "--untracked-files=no")
    return sha, (status is None or status != "")


def cobc_version():
    exe = shutil.which("cobc")
    if not exe:
        return "cobc not found"
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "cobc not runnable"
    return (out.stdout.splitlines() or ["cobc gave no version"])[0].strip()


def frozen_hash(eval_doc):
    m = re.search(r"^split-sha256:\s*([0-9a-f]{64})\s*$", Path(eval_doc).read_text(), re.M)
    if not m:
        raise SplitHashMismatch(f"{eval_doc} has no split-sha256 line")
    return m.group(1)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_split(split_path, split, data=None):
    """The changes of `split` in the split file, parsed from `data` (its bytes) when given."""
    text = (Path(split_path).read_bytes() if data is None else data).decode("utf-8")
    rows = []
    for ln in text.splitlines():
        if ln.strip():
            ch = json.loads(ln)
            if ch.get("split") == split:
                rows.append(ch)
    return rows


# ---------------------------------------------------------------- scoring
def _ratio(num, den):
    return num / den if den else None


def _tally():
    return {"changes": 0, "scored": 0, "changed": 0, "predicted": 0, "hits": 0}
# In a summary row these counts are named changed_count and predicted_count:
# `changed` and `predicted` are the per-change lists (results-row.schema.json).


def _add(t, row):
    t["changes"] += 1
    if not row["excluded"]:
        t["scored"] += 1
        t["changed"] += len(row["changed"])
        t["predicted"] += len(row["predicted"])
        t["hits"] += len(row["true_positive"])


def _finish(t):
    return {"changes": t["changes"], "scored": t["scored"], "changed_count": t["changed"],
            "predicted_count": t["predicted"], "hits": t["hits"],
            "recall": _ratio(t["hits"], t["changed"]), "precision": _ratio(t["hits"], t["predicted"])}


def score(change, radius, diff, predict_error=None):
    """The per-change fields of a row."""
    changed = sorted(set(diff.get("changed") or []))
    universe = set(changed) | set(diff.get("unchanged") or [])
    guessed = sorted(set((radius or {}).get("datasets") or []))
    predicted = [d for d in guessed if d in universe]
    hits = sorted(set(predicted) & set(changed))
    excluded = bool(diff.get("excluded"))
    row = {
        "change_id": change["id"], "class": change.get("class"),
        "changed": changed, "predicted": predicted,
        "predicted_outside_universe": [d for d in guessed if d not in universe],
        "true_positive": hits,
        "false_positive": sorted(set(predicted) - set(changed)),
        "false_negative": sorted(set(changed) - set(predicted)),
        "unverifiable": sorted((radius or {}).get("unverifiable") or []),
        "status_changes": diff.get("status_changes") or [],
        "excluded": excluded, "exclusion_reason": diff.get("exclusion_reason") if excluded else None,
        "predict_error": predict_error,
        "recall": None if excluded else _ratio(len(hits), len(changed)),
        "precision": None if excluded else _ratio(len(hits), len(predicted)),
    }
    return row


def _predictor_name(radius):
    p = (radius or {}).get("predictor") or {}
    return f"{p.get('name', 'unknown')}@{p.get('version', '?')}"


def run(split, split_path, eval_doc, root, runset, out_path, predict, ground_truth):
    """Score `predict` against `ground_truth` on `split`; append the rows to `out_path` and return them."""
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}")
    frozen = frozen_hash(eval_doc)
    data = Path(split_path).read_bytes()  # read once: the rows scored are the bytes hashed
    actual = hashlib.sha256(data).hexdigest()
    if split == "heldout" and actual != frozen:
        raise SplitHashMismatch(f"{split_path} hashes to {actual}, {eval_doc} freezes {frozen}")
    changes = load_split(split_path, split, data)

    date = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    sha, dirty = git_state()
    common = {
        "run_id": f"{date[:10]}-{uuid.uuid4().hex[:12]}", "git_sha": sha, "git_dirty": dirty,
        "machine": machine(), "model_revision": None, "quant": None, "runtime": None, "date": date,
        "carddemo_commit": runset.get("carddemo_commit", ""), "split": split, "split_sha256": actual,
        "split_matches_contract": actual == frozen,
    }

    rows, names, cobc = [], [], set()
    for ch in changes:
        err = None
        try:
            radius = predict(ch)
        except Exception as exc:  # a predictor crash is a miss, and it is shown
            radius, err = None, f"{type(exc).__name__}: {exc}"
        diff = ground_truth(ch)  # a grader failure stops the run; it is never guessed
        if diff.get("cobc_version"):
            cobc.add(diff["cobc_version"])
        name = _predictor_name(radius) if radius else "error"
        if radius:
            names.append(name)
        rows.append(dict(score(ch, radius, diff, err), kind="change", predictor=name))

    predictor = ",".join(sorted(set(names))) or "none"
    cobc_v = ",".join(sorted(cobc)) or cobc_version()

    total, per_class, noop = _tally(), {}, {"correct": 0, "incorrect": 0, "excluded": 0, "ids_incorrect": []}
    reasons = {}
    for r in rows:
        _add(total, r)
        _add(per_class.setdefault(r["class"], _tally()), r)
        if r["excluded"]:
            reasons[r["exclusion_reason"]] = reasons.get(r["exclusion_reason"], 0) + 1
        if r["class"] == "noop":
            if r["excluded"]:
                noop["excluded"] += 1
            elif not r["changed"] and not r["predicted"]:
                noop["correct"] += 1
            else:
                noop["incorrect"] += 1
                noop["ids_incorrect"].append(r["change_id"])
    t = _finish(total)
    summary = {
        "kind": "summary", "predictor": predictor,
        **t,
        "per_class": {k: _finish(v) for k, v in sorted(per_class.items())},
        "noop": noop, "excluded_by_reason": dict(sorted(reasons.items())),
        "predict_errors": sum(1 for r in rows if r["predict_error"]),
        "predicted_outside_universe": sum(len(r["predicted_outside_universe"]) for r in rows),
    }
    rows.append(summary)
    rows = [dict(common, cobc_version=cobc_v, **r) for r in rows]

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "a") as fh:
        fh.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    return rows
