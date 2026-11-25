"""Allowlist decisions, strictest rule wins (contracts/allowlist.md).

`*` matches any run of characters except `.`, `?` one character except `.`,
and `**` any run including `.`. Patterns match the whole name,
case-sensitively. An item no rule matches asks. The change's decision is the
strictest action over its items, so rule order never changes a decision.
"""
import json
import re
from pathlib import Path

ACTIONS = ("allow", "ask", "deny")
KINDS = ("dataset", "program", "job", "member", "any")
_RANK = {a: i for i, a in enumerate(ACTIONS)}

# The radius lists that become items, in contract order.
_ITEM_LISTS = (("member", "members"), ("program", "programs"), ("job", "jobs"), ("dataset", "datasets"))


class RuleError(ValueError):
    pass


def compile_pattern(pattern):
    """The regex for one allowlist pattern (whole-name match)."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^.]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^.]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out), re.DOTALL)


def check_rules(rules):
    """Raise RuleError unless `rules` is a list of valid rules (allowlist.schema.json)."""
    if not isinstance(rules, list):
        raise RuleError("rules must be a list")
    for n, r in enumerate(rules):
        if not isinstance(r, dict):
            raise RuleError(f"rule {n}: not an object")
        extra = set(r) - {"pattern", "kind", "action"}
        if extra:
            raise RuleError(f"rule {n}: unexpected {sorted(extra)}")
        if not isinstance(r.get("pattern"), str) or not r["pattern"]:
            raise RuleError(f"rule {n}: pattern must be a non-empty string")
        if r.get("action") not in ACTIONS:
            raise RuleError(f"rule {n}: action must be one of {list(ACTIONS)}")
        if r.get("kind", "any") not in KINDS:
            raise RuleError(f"rule {n}: kind must be one of {list(KINDS)}")


def load_rules(path):
    """Read an allowlist file ({"rules": [...]}) and return its checked rule list."""
    doc = json.loads(Path(path).read_text())
    if not isinstance(doc, dict) or set(doc) != {"rules"}:
        raise RuleError(f"{path}: want an object with exactly one key, rules")
    check_rules(doc["rules"])
    return doc["rules"]


def edited_members(change):
    """The members a change's edits touch (radius.md: `app/cpy/CVACT01Y.cpy` gives `CVACT01Y`)."""
    out = set()
    for e in change.get("edits") or []:
        name = str(e.get("file", "")).replace("\\", "/").rsplit("/", 1)[-1]
        out.add((name.rsplit(".", 1)[0] if "." in name else name).upper())
    return sorted(out)


def check_radius_covers(change, radius):
    """Raise RuleError unless `radius` is for `change` and names every member its edits touch.

    allowlist.md makes the edited members items of every decision. A radius
    that leaves one out (a stale or hand-edited radius file) would let a rule
    on that member go unchecked, so it is refused rather than decided.
    """
    if radius.get("change_id") != change.get("id"):
        raise RuleError(f"radius is for {radius.get('change_id')!r}, change is {change.get('id')!r}")
    missing = sorted(set(edited_members(change)) - set(radius.get("members") or []))
    if missing:
        raise RuleError(f"radius does not name the edited members {missing}")


def check_radius_includes(radius, predicted):
    """Raise RuleError unless `radius` names every member, program, job and dataset `predicted` does.

    A supplied radius can widen the predicted one, which only makes the
    decision stricter. One that leaves an item out (a stale or hand-edited
    radius file) would let a rule on that item go unchecked, so it is refused.
    """
    missing = []
    for kind, key in _ITEM_LISTS:
        have = set(radius.get(key) or [])
        missing += [f"{kind} {name}" for name in predicted.get(key) or [] if name not in have]
    if missing:
        raise RuleError(f"radius leaves out predicted items {missing}")


def _git_head(root):
    """The tree's git HEAD when `root` is the top of its own checkout, else None."""
    import subprocess
    try:
        top = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(root), "rev-parse", "--show-toplevel", "HEAD"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = top.stdout.split()
    if top.returncode != 0 or len(lines) != 2 or Path(lines[0]).resolve() != Path(root).resolve():
        return None
    return lines[1]


def check_runset_fits(runset, root):
    """Raise RuleError unless `runset` describes the tree at `root` (allowlist.md, CB-P3c-r3-S1).

    The predictor only follows the jobs and programs the run set names. A run
    set for another tree finds none of them and predicts a narrower radius,
    which would let a rule on a dataset go unchecked, so it is refused.
    """
    root = Path(root)
    problems = []
    for j in runset.get("jobs") or []:
        if not (root / str(j.get("file", ""))).is_file():
            problems.append(f"job {j.get('job')} ({j.get('file')})")
    dirs = runset.get("program_dirs") or []
    for prog in runset.get("programs") or []:
        if not any((root / d / f"{prog}{ext}").is_file()
                   for d in dirs for ext in (".cbl", ".CBL", ".cob", ".COB")):
            problems.append(f"program {prog}")
    if problems:
        raise RuleError(f"run set does not describe {root}: missing {problems[:5]}"
                        + (f" and {len(problems) - 5} more" if len(problems) > 5 else ""))
    want, head = runset.get("carddemo_commit"), _git_head(root)
    if head and want and want != head:
        raise RuleError(f"run set is for commit {want}, {root} is at {head}")


def strictest(actions, default="ask"):
    actions = list(actions)
    return max(actions, key=_RANK.__getitem__) if actions else default


def decide(radius, rules):
    """The decision for `radius` under `rules` (the list under "rules")."""
    check_rules(rules)
    compiled = [(r.get("kind", "any"), compile_pattern(r["pattern"]), r["action"]) for r in rules]
    items = []
    for kind, key in _ITEM_LISTS:
        for name in radius.get(key) or []:
            hits = [i for i, (k, rx, _) in enumerate(compiled)
                    if k in ("any", kind) and rx.fullmatch(name)]
            items.append({"kind": kind, "name": name,
                          "action": strictest(compiled[i][2] for i in hits),
                          "rules": hits})
    return {"decision": strictest(i["action"] for i in items), "items": items}
