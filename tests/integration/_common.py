"""Shared helpers for the cross-lane tests."""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACTS = REPO / "contracts"
MINI = REPO / "fixtures" / "mini"
CARDDEMO = REPO / "vendor" / "carddemo"

sys.path.insert(0, str(REPO))
from tests.red._support import schema_errors, tree_digest  # noqa: E402,F401


def load(path):
    return json.loads(Path(path).read_text())


def schema(name):
    return load(CONTRACTS / name)


def need_cobc(case):
    if shutil.which("cobc") is None:
        case.fail("cobc is missing: run scripts/setup.sh")


def need_carddemo(case):
    if not (CARDDEMO / "app" / "cbl").is_dir():
        case.fail("vendor/carddemo is missing: run scripts/setup.sh")


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cli(*args):
    r = subprocess.run([sys.executable, "-m", "approval.cli", *map(str, args)], cwd=REPO,
                       capture_output=True, text=True, timeout=600)
    out = json.loads(r.stdout) if r.stdout.strip() else None
    return r.returncode, out, r.stderr


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def assertSchema(self, value, name):
        errs = schema_errors(value, schema(name))
        self.assertEqual(errs, [], f"{name}: {errs[:5]}")
