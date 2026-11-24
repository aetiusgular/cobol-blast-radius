"""Byte diff of two run results (contracts/ground-truth.md). Pure: reads its two arguments only."""


def _step_key(s):
    k = f"{s['job']}.{s['step']}"
    return k + (f".{s['procstep']}" if s.get("procstep") else "")


def _exclusion(baseline, after):
    if after.get("apply_error"):
        return "apply_failure"
    for prog, res in sorted((after.get("compile") or {}).items()):
        if not res.get("ok") and (baseline.get("compile") or {}).get(prog, {}).get("ok"):
            return "compile_failure"
    if after.get("cics_only"):
        return "cics_only"
    return None


def diff(baseline, after):
    """Which outputs changed between `baseline` and `after` (two run results)."""
    base_out = baseline.get("outputs") or {}
    after_out = after.get("outputs") or {}
    changed, unchanged = [], []
    for name in sorted(set(base_out) | set(after_out)):
        a = base_out.get(name, {}).get("sha256")
        b = after_out.get(name, {}).get("sha256")
        if name in base_out and name in after_out and a == b and a is not None:
            unchanged.append(name)
        elif name in base_out and name in after_out and a is None and b is None:
            unchanged.append(name)
        else:
            changed.append(name)

    status_changes = []
    before_steps = {}
    for s in baseline.get("steps") or []:
        before_steps.setdefault(_step_key(s), []).append(s)
    seen = {}
    for s in after.get("steps") or []:
        k = _step_key(s)
        i = seen.get(k, 0)
        seen[k] = i + 1
        prev = before_steps.get(k, [])
        b = prev[i] if i < len(prev) else None
        bv = {"status": b["status"], "rc": b["rc"]} if b else None
        av = {"status": s["status"], "rc": s["rc"]}
        if bv != av:
            status_changes.append({"step": k, "before": bv, "after": av})
    for k, prev in sorted(before_steps.items()):
        for s in prev[seen.get(k, 0):]:
            status_changes.append({"step": k, "before": {"status": s["status"], "rc": s["rc"]}, "after": None})

    reason = _exclusion(baseline, after)
    return {
        "change_id": after.get("change_id"),
        "changed": changed,
        "unchanged": unchanged,
        "excluded": reason is not None,
        "exclusion_reason": reason,
        "status_changes": status_changes,
    }
