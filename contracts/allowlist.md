# Allowlist and approval record (P3c)

## Rules (`allowlist.schema.json`)

```json
{"rules": [
  {"pattern": "AWS.M2.CARDDEMO.**", "kind": "dataset", "action": "ask"},
  {"pattern": "CVACT0*",            "action": "deny"},
  {"pattern": "READ*",              "kind": "job", "action": "allow"}
]}
```

- `kind` is `dataset`, `program`, `job`, `member` or `any`. Left out, it is `any`: the pattern is tried against every item, so one pattern can match a dataset name and a member name.
- Patterns are matched against the whole name, case-sensitively. `*` matches any run of characters except `.`, `?` matches one character except `.`, and `**` matches any run of characters including `.`. Nothing else is special.
- `action` is `allow`, `ask` or `deny`.

## Decision

`approval.allowlist.decide(radius, rules)` returns:

```json
{"decision": "ask",
 "items": [{"kind": "dataset", "name": "AWS.M2.CARDDEMO.TRANREPT", "action": "ask", "rules": [0]}]}
```

- The items are every entry of the radius's `members` (kind `member`), `programs`, `jobs` and `datasets`, in that order, each list in its own order.
- **Strictest wins.** An item's action is the strictest action among all rules that match it (`deny` > `ask` > `allow`); `rules` lists the matching rule indexes in file order. Rule order never changes a decision.
- An item no rule matches is `ask`. An empty rule list therefore makes every item `ask`.
- The change's decision is the strictest action over its items. The edited members are always items, so a change with an empty predicted radius still gets a decision.

## Approval record

The record the ledger stores for one decision: `{"change": <change>, "radius": <radius>, "decision": <decision>, "decided_by": "<who>", "note": "<free text>"}`. A `deny` decision is recorded but its change is never applied.
