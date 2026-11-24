"""Eval runner: writes results rows (contracts/eval.md)."""


class SplitHashMismatch(Exception):
    pass


def machine():
    raise NotImplementedError("approval.evalrun.machine")


def run(split, split_path, eval_doc, root, runset, out_path, predict, ground_truth):
    raise NotImplementedError("approval.evalrun.run")
