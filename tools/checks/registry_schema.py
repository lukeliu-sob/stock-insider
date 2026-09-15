#!/usr/bin/env python3
"""Structural gate: registry schema validation (blocking gate D7-3).

Also enforces ID uniqueness and depends_on referential integrity.
Requires: pyyaml, jsonschema.
"""

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "docs" / "req" / "requirements.yaml"
SCHEMA = ROOT / "docs" / "req" / "req-schema.json"


def main() -> None:
    import jsonschema
    import yaml

    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(registry, schema)

    reqs = registry["requirements"]
    ids = [r["id"] for r in reqs]
    dupes = [i for i, c in collections.Counter(ids).items() if c > 1]
    if dupes:
        sys.exit(f"FAIL registry: duplicate IDs {dupes}")

    idset = set(ids)
    bad = [
        (r["id"], d) for r in reqs for d in r.get("depends_on", []) if d not in idset
    ]
    if bad:
        sys.exit(f"FAIL registry: dangling depends_on {bad}")

    print(
        f"PASS registry schema gate: {len(reqs)} entries "
        f"(v{registry['meta']['registry_version']})"
    )


if __name__ == "__main__":
    main()
