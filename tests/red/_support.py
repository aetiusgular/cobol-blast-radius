"""Helpers for the red tests (P2). Lanes do not edit tests/red/."""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACTS = REPO / "contracts"
MINI = REPO / "fixtures" / "mini"
CARDDEMO = REPO / "vendor" / "carddemo"


def load(path):
    return json.loads(Path(path).read_text())


def mini_runset(name="runset.json"):
    return load(MINI / name)


def mini_change(name):
    return load(MINI / "changes" / f"{name}.json")


def carddemo_runset():
    return load(CONTRACTS / "runset.json")


def need_carddemo(case):
    if not (CARDDEMO / "app" / "cbl").is_dir():
        case.fail("vendor/carddemo is missing: run scripts/setup.sh")


def copy_tree(src, tmp):
    dst = Path(tmp) / "root"
    shutil.copytree(src, dst)
    return dst


def tree_digest(root):
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


# ---------------------------------------------------------- schema check
# The subset of JSON Schema the contracts use: type, enum, required,
# properties, additionalProperties: false, items, minItems, minimum,
# minLength, pattern.
_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "integer": int, "number": (int, float), "null": type(None),
}


def _is(value, t):
    if t in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[t])


def schema_errors(value, schema, where="$"):
    import re
    errs = []
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{where}: {value!r} not in {schema['enum']}")
    if "type" in schema:
        ts = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is(value, t) for t in ts):
            return errs + [f"{where}: {type(value).__name__} is not {ts}"]
    if isinstance(value, dict):
        for k in schema.get("required", []):
            if k not in value:
                errs.append(f"{where}: missing {k}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for k in value:
                if k not in props:
                    errs.append(f"{where}: unexpected {k}")
        for k, sub in props.items():
            if k in value:
                errs += schema_errors(value[k], sub, f"{where}.{k}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errs.append(f"{where}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                errs += schema_errors(item, schema["items"], f"{where}[{i}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errs.append(f"{where}: shorter than {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{where}: {value!r} does not match {schema['pattern']}")
    if _is(value, "number") and "minimum" in schema and value < schema["minimum"]:
        errs.append(f"{where}: {value} below {schema['minimum']}")
    return errs


def assert_schema(case, value, schema_file):
    errs = schema_errors(value, load(CONTRACTS / schema_file))
    case.assertEqual(errs, [], f"{schema_file}: {errs[:5]}")
