"""Apply a change to a source tree, all or nothing (contracts/change.md)."""


class ApplyError(Exception):
    pass


def apply(change, root):
    raise NotImplementedError("groundtruth.changes.apply")
