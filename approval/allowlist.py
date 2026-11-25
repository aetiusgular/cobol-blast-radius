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
