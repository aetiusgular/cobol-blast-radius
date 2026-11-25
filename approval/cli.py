"""Command line: python3 -m approval.cli <predict|decide|approve|deny|verify|revert|eval> (contracts/seams.md).

Every command prints one JSON document on stdout. Errors print
{"error": "..."} on stderr and exit 2.

  predict  --change C [--root R] [--runset S] [--e0]           a radius
  decide   (--change C | --radius X) --allowlist A [...]        a decision
  approve  --change C --allowlist A --root R --ledger L --by WHO [--confirm] [--note N]
           allow: applied and recorded. ask: needs --confirm (exit 3 without it,
           nothing written). deny: recorded as a deny entry, never applied (exit 4).
  deny     --change C --root R --ledger L --by WHO [--allowlist A] [--note N]
  verify   --ledger L [--expect-head SHA]                       exit 1 when not ok
  revert   --ledger L --seq N --root R                          the revert entry
  eval     --split dev|heldout --out results/E<k>-<split>.jsonl [--predictor full|e0]
           [--split-path P] [--root R] [--runset S] [--workdir W]
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO / "vendor" / "carddemo"
DEFAULT_RUNSET = REPO / "contracts" / "runset.json"
EVAL_DOC = REPO / "contracts" / "eval.md"
SPLIT = REPO / "contracts" / "split.jsonl"


class Refused(Exception):
    def __init__(self, code, doc):
        super().__init__(doc)
        self.code, self.doc = code, doc


def _json(path):
    return json.loads(Path(path).read_text())


def _predictor(e0):
    from radius import predict as rp
    return rp.predict_e0 if e0 else rp.predict


def _radius(a):
    if getattr(a, "radius", None):
        return _json(a.radius)
    return _predictor(getattr(a, "e0", False))(_json(a.change), Path(a.root), _json(a.runset))


def _record(a, rules):
    from approval import allowlist
    change = _json(a.change)
    radius = _radius(a)
    allowlist.check_radius_covers(change, radius)
    if getattr(a, "radius", None):  # CB-P3c-r2-S1: a supplied radius may widen the predicted one, never narrow it
        allowlist.check_radius_includes(radius, _predictor(False)(change, Path(a.root), _json(a.runset)))
    return {"change": change, "radius": radius, "decision": allowlist.decide(radius, rules),
            "decided_by": a.by, "note": a.note or ""}


def cmd_predict(a):
    return _radius(a)


def cmd_decide(a):
    from approval import allowlist
    return allowlist.decide(_radius(a), allowlist.load_rules(a.allowlist))


def cmd_approve(a):
    from approval import allowlist
    from approval.ledger import Ledger
    rec = _record(a, allowlist.load_rules(a.allowlist))
    d = rec["decision"]["decision"]
    led = Ledger(a.ledger)
    if d == "deny":
        raise Refused(4, {"refused": "deny", "entry": led.deny(rec)})
    if d == "ask" and not a.confirm:
        raise Refused(3, {"refused": "ask", "decision": rec["decision"],
                          "hint": "rerun with --confirm to approve as " + a.by})
    return led.approve(rec, Path(a.root))


def cmd_deny(a):
    from approval import allowlist
    from approval.ledger import Ledger
    rules = allowlist.load_rules(a.allowlist) if a.allowlist else []
    return Ledger(a.ledger).deny(_record(a, rules))


def cmd_verify(a):
    from approval.ledger import Ledger
    v = Ledger(a.ledger).verify()
    if a.expect_head and v["head_sha256"] != a.expect_head:
        v["ok"] = False
        v["problems"].append({"seq": None, "problem": f"head is {v['head_sha256']}, expected {a.expect_head}"})
    if not v["ok"]:
        raise Refused(1, v)
    return v


def cmd_revert(a):
    from approval.ledger import Ledger
    return Ledger(a.ledger).revert(a.seq, Path(a.root))


def cmd_eval(a):
    from approval import evalrun
    root, runset = Path(a.root), _json(a.runset)
    predict = _predictor(a.predictor == "e0")
    work = Path(a.workdir) if a.workdir else Path(tempfile.mkdtemp(prefix="cbr-eval-"))
    rows = evalrun.run(a.split, Path(a.split_path), EVAL_DOC, root, runset, Path(a.out),
                       lambda ch: predict(ch, root, runset), harness_ground_truth(root, runset, work))
    return rows[-1]


class BaselineBroken(RuntimeError):
    pass


def harness_ground_truth(root, runset, work):
    """ground_truth(change) for the eval runner: one baseline run, then one run per change, diffed.

    A baseline in which a run-set program does not compile would make every
    diff degenerate (nothing runs, so nothing changes), so it stops the run.
    """
    from groundtruth import diff as gtdiff
    from groundtruth import harness
    state = {}

    def ground_truth(change):
        if "baseline" not in state:
            base = harness.run(root, runset, Path(work) / "baseline")
            broken = sorted(p for p, r in (base.get("compile") or {}).items() if not r.get("ok"))
            if broken:
                raise BaselineBroken(f"baseline does not build: {broken}; "
                                     f"{base['compile'][broken[0]].get('diagnostics', '')[:300]}")
            state["baseline"] = base
        after = harness.run(root, runset, Path(work) / change["id"], change)
        return dict(gtdiff.diff(state["baseline"], after), cobc_version=after.get("cobc_version"))
    return ground_truth


def parser():
    p = argparse.ArgumentParser(prog="python3 -m approval.cli", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def tree(s, root_required=False):
        s.add_argument("--root", default=str(DEFAULT_ROOT), required=root_required)
        s.add_argument("--runset", default=str(DEFAULT_RUNSET))

    s = sub.add_parser("predict")
    s.add_argument("--change", required=True)
    s.add_argument("--e0", action="store_true")
    tree(s)

    s = sub.add_parser("decide")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--change")
    g.add_argument("--radius")
    s.add_argument("--allowlist", required=True)
    s.add_argument("--e0", action="store_true")
    tree(s)

    for name in ("approve", "deny"):
        s = sub.add_parser(name)
        s.add_argument("--change", required=True)
        s.add_argument("--radius", help="use this radius instead of predicting one")
        s.add_argument("--allowlist", required=(name == "approve"))
        s.add_argument("--ledger", required=True)
        s.add_argument("--by", required=True)
        s.add_argument("--note")
        if name == "approve":
            s.add_argument("--confirm", action="store_true", help="approve an ask decision")
        tree(s, root_required=True)

    s = sub.add_parser("verify")
    s.add_argument("--ledger", required=True)
    s.add_argument("--expect-head", help="fail unless the last entry has this entry_sha256")

    s = sub.add_parser("revert")
    s.add_argument("--ledger", required=True)
    s.add_argument("--seq", type=int, required=True)
    s.add_argument("--root", required=True)

    s = sub.add_parser("eval")
    s.add_argument("--split", choices=["dev", "heldout"], required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--predictor", choices=["full", "e0"], default="full")
    s.add_argument("--split-path", default=str(SPLIT))
    s.add_argument("--workdir")
    tree(s)
    return p


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        out = globals()["cmd_" + a.cmd](a)
    except Refused as r:
        print(json.dumps(r.doc, indent=2, sort_keys=True))
        return r.code
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
