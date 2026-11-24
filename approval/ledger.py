"""Append-only, hash-chained approval ledger with revert (contracts/ledger.md)."""


class Ledger:
    def __init__(self, path):
        self.path = path

    def approve(self, record, root):
        raise NotImplementedError("approval.ledger.Ledger.approve")

    def deny(self, record):
        raise NotImplementedError("approval.ledger.Ledger.deny")

    def verify(self):
        raise NotImplementedError("approval.ledger.Ledger.verify")

    def revert(self, seq, root):
        raise NotImplementedError("approval.ledger.Ledger.revert")

    def entries(self):
        raise NotImplementedError("approval.ledger.Ledger.entries")
