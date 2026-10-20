"""How the planted defects of `plant.py` rank in the audit of the planted copy (epic #133).

    uv run scripts/quality/recall.py [--out scripts/quality/out/planted.jsonl]

For each plant: its hit strength for its pattern, its rank among all units the pattern was asked
about, and how many units score at least as high as the plant (the review effort to find it).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jev import OUT
from plant import PLANTED


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT / "planted.jsonl")
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.out.read_text().splitlines()]
    truth = json.loads((PLANTED / "plants.json").read_text())
    print("pattern  strength  rank       >=0.5  unit")
    for plant in truth:
        pattern = plant["pattern"]
        asked = [r for r in rows if pattern in r["hits"]]
        if not asked:
            continue  # D1 is measured by duplicates.py
        own = next(r for r in asked if r["key"] == plant["key"])["hits"][pattern]
        rank = 1 + sum(r["hits"][pattern] > own for r in asked)
        above = sum(r["hits"][pattern] >= 0.5 for r in asked)
        print(f"{pattern:<8} {own:8.2f}  {rank:>4}/{len(asked):<5} {above:>5}  {plant['key']}")


if __name__ == "__main__":
    main()
