"""The D1 experiment of epic #133: three ways to find duplicated logic in src/ with Jev.

    uv run scripts/quality/duplicates.py [--root DIR] [--out FILE]

- A, whole repo (long-context mode): every function in one state. Step 1 asks per function
  whether any other one does the same; step 2 asks, for the functions above `--a-threshold`,
  which ones (one Noul per other function, all over the same state).
- B, fingerprint pairs: code ranks function pairs by shared token shingles after replacing
  names and literals; Jev scores the top `--b-pairs` pairs, two functions at a time.
- C, module pairs: step 1 asks per pair of modules whether one re-implements what the other
  provides; step 2 asks, for the pairs above `--c-threshold`, about every pair of functions
  across the two modules, over the same two-module state.

In the planted copy A gave no signal (every answer near 0.5), so it only runs with `--setups`
including A; it costs about $4 per run.

Writes the raw judgments to out/duplicates.json (or `--out`); with `--root` pointing at the
copy from `plant.py`, it also reports the recall of the planted duplicates.
"""

from __future__ import annotations

import argparse
import io
import itertools
import json
import keyword
import tokenize
from pathlib import Path
from typing import Any

from jev import OUT, ask_many, cost
from patterns import strength
from units import Unit, python_files, units

REPO = Path(__file__).resolve().parents[2]
BATCH = 100  # questions per request over the whole-repo state
MIN_TOKENS = 25  # functions shorter than this are left out of B

SAME_LOGIC = (
    "Two functions duplicate each other when they implement the same computation or decision, so "
    "one could call the other or both could share a helper, even if names, structure or style "
    "differ. Merely calling the same functions, following the same pattern (for example two "
    "parsers of different fields) or both being short accessors is not duplication."
)


def _noul(instructions: str, true: str, false: str) -> dict[str, Any]:
    return {
        "type": "noul",
        "instructions": instructions,
        "criteria": {"true": true, "false": false},
    }


def _batched(questions: dict[str, Any]) -> list[dict[str, Any]]:
    items = list(questions.items())
    return [dict(items[i : i + BATCH]) for i in range(0, len(items), BATCH)]


def setup_a(found: list[Unit], threshold: float) -> dict[str, Any]:
    state = {
        "functions": [{"name": u.key, "source": u.source} for u in found],
    }
    step1 = {
        str(i): _noul(
            f"{SAME_LOGIC} Does any other function in `functions` duplicate the logic of "
            f"`functions[{i}]`?",
            "At least one other function duplicates it.",
            "No other function duplicates it.",
        )
        for i in range(len(found))
    }
    answers: dict[str, Any] = {}
    responses = ask_many((state, q) for q in _batched(step1))
    for r in responses:
        answers.update(r["answers"])
    any_dup = {found[int(i)].key: a["noul"] for i, a in answers.items()}
    targets = [i for i, u in enumerate(found) if any_dup[u.key] >= threshold]
    jobs = []
    for i in targets:
        pair_questions = {
            str(j): _noul(
                f"{SAME_LOGIC} Does `functions[{j}]` duplicate the logic of `functions[{i}]`?",
                "It duplicates it.",
                "It does not.",
            )
            for j in range(len(found))
            if j != i
        }
        jobs.extend((i, q) for q in _batched(pair_questions))
    step2 = ask_many((state, q) for _, q in jobs)
    pairs: dict[tuple[str, str], float] = {}
    for (i, _), r in zip(jobs, step2, strict=True):
        for j, a in r["answers"].items():
            first, second = sorted((found[i].key, found[int(j)].key))
            key = (first, second)
            pairs[key] = max(pairs.get(key, 0.0), a["noul"])
    return {
        "any": any_dup,
        "pairs": [[a, b, p] for (a, b), p in sorted(pairs.items(), key=lambda kv: -kv[1])],
        "cost": cost(responses) + cost(step2),
        "long_context": responses[0]["long_context"],
    }


def _shingles(source: str, k: int = 6) -> set[tuple[str, ...]]:
    """Token k-grams with names, numbers and strings replaced, comments and docstrings dropped."""
    tokens = []
    for t in tokenize.generate_tokens(io.StringIO(source).readline):
        if t.type == tokenize.NAME:
            tokens.append(t.string if keyword.iskeyword(t.string) else "N")
        elif t.type == tokenize.NUMBER:
            tokens.append("0")
        elif t.type == tokenize.STRING:
            if tokens and tokens[-1] in (":", "INDENT"):
                continue  # docstring
            tokens.append("S")
        elif t.type == tokenize.OP:
            tokens.append(t.string)
        elif t.type == tokenize.INDENT:
            tokens.append("INDENT")
    if len(tokens) < MIN_TOKENS:
        return set()
    return {tuple(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def setup_b(found: list[Unit], top: int) -> dict[str, Any]:
    shingles = {u.key: _shingles(u.source) for u in found}
    candidates = []
    for a, b in itertools.combinations(found, 2):
        sa, sb = shingles[a.key], shingles[b.key]
        if sa and sb:
            candidates.append((len(sa & sb) / len(sa | sb), a, b))
    candidates.sort(key=lambda c: -c[0])
    question = {
        "duplicate": {
            "type": "score",
            "instructions": f"{SAME_LOGIC} How much logic do `a.source` and `b.source` share?",
            "criteria": [
                "No shared logic beyond common idioms",
                "A similar shape, but they compute different things",
                "The same computation or decision; one helper could serve both",
                "A copy of each other, possibly with renamed variables",
            ],
        }
    }
    chosen = candidates[:top]
    states = [
        {"a": {"name": a.key, "source": a.source}, "b": {"name": b.key, "source": b.source}}
        for _, a, b in chosen
    ]
    responses = ask_many((s, question) for s in states)
    pairs = [
        (a.key, b.key, round(jaccard, 3), strength(r["answers"]["duplicate"]))
        for (jaccard, a, b), r in zip(chosen, responses, strict=True)
    ]
    return {
        "pairs": sorted(pairs, key=lambda p: -p[3]),
        "rank": {f"{a.key} | {b.key}": n for n, (_, a, b) in enumerate(candidates, 1)},
        "cost": cost(responses),
    }


def setup_c(root: Path, modules: list[str], found: list[Unit], threshold: float) -> dict[str, Any]:
    sources = {m: (root / m).read_text() for m in modules}
    pairs = list(itertools.combinations(modules, 2))
    question = {
        "reimplements": _noul(
            f"{SAME_LOGIC} Does one of the modules `module_a` and `module_b` contain a function "
            "that re-implements logic the other module already provides, instead of importing "
            "and calling it?",
            "One module duplicates logic that the other already has.",
            "They share no duplicated logic.",
        )
    }
    states = [
        {
            "module_a": {"path": a, "source": sources[a]},
            "module_b": {"path": b, "source": sources[b]},
        }
        for a, b in pairs
    ]
    responses = ask_many((s, question) for s in states)
    rows = [
        (a, b, float(r["answers"]["reimplements"]["noul"]), bool(r["long_context"]))
        for (a, b), r in zip(pairs, responses, strict=True)
    ]
    by_module: dict[str, list[Unit]] = {}
    for u in found:
        by_module.setdefault(u.path, []).append(u)
    jobs = []
    for (a, b, score, _), s in zip(rows, states, strict=True):
        if score < threshold:
            continue
        cross = list(itertools.product(by_module.get(a, []), by_module.get(b, [])))
        questions = {
            str(n): _noul(
                f"{SAME_LOGIC} Do the function `{fa.qualname}` in `module_a` and the function "
                f"`{fb.qualname}` in `module_b` duplicate each other?",
                "They duplicate each other.",
                "They do not.",
            )
            for n, (fa, fb) in enumerate(cross)
        }
        jobs.extend((cross, s, q) for q in _batched(questions))
    step2 = ask_many((s, q) for _, s, q in jobs)
    functions = [
        (cross[int(n)][0].key, cross[int(n)][1].key, float(a["noul"]))
        for (cross, _, _), r in zip(jobs, step2, strict=True)
        for n, a in r["answers"].items()
    ]
    return {
        "pairs": sorted(rows, key=lambda p: -p[2]),
        "functions": sorted(functions, key=lambda p: -p[2]),
        "cost": cost(responses) + cost(step2),
    }


def recall(result: dict[str, Any], truth: list[dict[str, str]]) -> None:
    a_pairs = {(p[0], p[1]): p[2] for p in result.get("A", {}).get("pairs", [])}
    a_any = result.get("A", {}).get("any", {})
    c_functions = {tuple(sorted(p[:2])): p[2] for p in result["C"]["functions"]}
    b_pairs = {(p[0], p[1]): p[3] for p in result["B"]["pairs"]}
    c_pairs = {(p[0], p[1]): p[2] for p in result["C"]["pairs"]}
    nan = float("nan")
    print("\nplanted duplicate  A any / pair   B rank (score)   C modules / functions")
    for plant in (t for t in truth if t["pattern"] == "D1"):
        a, b = sorted((plant["key"], plant["original"]))
        ma, mb = sorted((a.split("::")[0], b.split("::")[0]))
        rank = result["B"]["rank"].get(f"{a} | {b}")
        print(
            f"{plant['key']}\n"
            f"  A {a_any.get(plant['key'], nan):.2f} / {a_pairs.get((a, b), nan):.2f}"
            f"   B #{rank} ({b_pairs.get((a, b), nan):.2f})"
            f"   C {c_pairs.get((ma, mb), nan):.2f} / {c_functions.get((a, b), nan):.2f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--out", type=Path, default=OUT / "duplicates.json")
    parser.add_argument("--a-threshold", type=float, default=0.5)
    parser.add_argument("--b-pairs", type=int, default=80)
    parser.add_argument("--c-threshold", type=float, default=0.6)
    parser.add_argument("--setups", default="BC", help="which of A, B, C to run")
    args = parser.parse_args()
    modules = python_files(args.root, "src")
    found = units(args.root, modules)
    result = {}
    if "A" in args.setups:
        result["A"] = setup_a(found, args.a_threshold)
    if "B" in args.setups:
        result["B"] = setup_b(found, args.b_pairs)
    if "C" in args.setups:
        result["C"] = setup_c(args.root, modules, found, args.c_threshold)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1))
    for name, part in result.items():
        print(f"{name}: ${part['cost']:.4f}")
    if (truth := args.root / "plants.json").exists() and {"B", "C"} <= set(args.setups):
        recall(result, json.loads(truth.read_text()))


if __name__ == "__main__":
    main()
