"""Ask Jev about every function and method for the anti-patterns of epic #133.

    uv run scripts/quality/audit.py run [--root DIR] [--only P1,G1] [PATH ...]
    uv run scripts/quality/audit.py report [--top 15] [--only P1,G1]

`run` sends one request per unit with all the patterns that apply to it (see `patterns.py`) and
writes out/audit.jsonl. `report` ranks the units per pattern by hit strength. `--root` points
at another checkout, such as the planted copy from `plant.py`; the default is this repository.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jev import OUT, ask_many, cost
from patterns import BY_ID, PATTERNS, Pattern, strength
from units import Unit, module_context, python_files, units

REPO = Path(__file__).resolve().parents[2]


def state(root: Path, unit: Unit) -> dict[str, Any]:
    return {
        "module_path": unit.path,
        "module_source": module_context(root, unit.path, unit.qualname),
        "target_name": unit.qualname,
        "target_source": unit.source,
    }


def run(root: Path, paths: list[str], patterns: list[Pattern], out: Path) -> None:
    jobs = []
    for unit in units(root, paths):
        applicable = {p.id: p.question for p in patterns if p.applies(unit)}
        if applicable:
            jobs.append((unit, state(root, unit), applicable))
    print(f"{len(jobs)} units, {sum(len(j[2]) for j in jobs)} questions")
    responses = ask_many((s, q) for _, s, q in jobs)
    with out.open("w") as f:
        for (unit, _, _), response in zip(jobs, responses, strict=True):
            row = {
                "key": unit.key,
                "path": unit.path,
                "lineno": unit.lineno,
                "long_context": response["long_context"],
                "hits": {k: strength(a) for k, a in response["answers"].items()},
            }
            f.write(json.dumps(row) + "\n")
    print(f"wrote {out}; cost ${cost(responses):.4f}")


def report(rows: list[dict[str, Any]], patterns: list[Pattern], top: int) -> None:
    for pattern in patterns:
        ranked = sorted(
            (r for r in rows if pattern.id in r["hits"]), key=lambda r: -r["hits"][pattern.id]
        )
        if not ranked:
            continue
        above = sum(r["hits"][pattern.id] >= 0.5 for r in ranked)
        print(f"\n## {pattern.id} {pattern.title} ({above} of {len(ranked)} at >= 0.5)")
        for r in ranked[:top]:
            print(f"{r['hits'][pattern.id]:.2f}  {r['path']}:{r['lineno']}  {r['key']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["run", "report"])
    parser.add_argument("paths", nargs="*", help="files to audit (default: src/ and tests/)")
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--only", help="comma-separated pattern IDs")
    parser.add_argument("--out", type=Path, default=OUT / "audit.jsonl")
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()
    patterns = [BY_ID[i] for i in args.only.split(",")] if args.only else PATTERNS
    if args.command == "run":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        run(args.root, args.paths or python_files(args.root, "src", "tests"), patterns, args.out)
    else:
        rows = [json.loads(line) for line in args.out.read_text().splitlines()]
        report(rows, patterns, args.top)


if __name__ == "__main__":
    main()
