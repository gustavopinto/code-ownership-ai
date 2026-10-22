#!/usr/bin/env python3
"""Table of projects: process measures (RQ1) and specification measures (RQ2).

Usage:
  python3 -I project_table.py PROJECTS_DIR [--agents data/agents.csv]

Combines adherence.py and spec_analysis.py into the rows of the LaTeX table.
The Agents column is read from data/agents.csv (taken from each README).
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adherence import project_row  # noqa: E402
from common import repos  # noqa: E402
from spec_analysis import analyze  # noqa: E402
from tests_analysis import load_excluded, project_tests  # noqa: E402

# Footnote marks of the table, by project folder
MARKS = {"name": {"dsai_ap1-Reprodutor-Media-Play": r"$^{\S}$", "dsai-ap1-2Drogue": r"$^{\P}$"},
         "spec_first": {"dsai-ap1--HealthOS-": r"$^{*}$"},
         "ac": {"dsai-ap1-kapitrace": r"$^{\dagger}$"},
         "authors": {"dsai-ap1-sigrestaurant": r"$^{\ddagger}$"}}


def pct(x):
    return "--" if x is None else f"{100 * x:.0f}\\%"


def share(rows, key):
    return sum(1 for r in rows if r[key]) / len(rows) if rows else None


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("projects", nargs="?", default=os.environ.get("PROJECTS_DIR"))
    ap.add_argument("--agents", default=os.path.join(here, "data", "agents.csv"))
    args = ap.parse_args()
    if not args.projects:
        ap.error("pass PROJECTS_DIR as an argument or environment variable")
    gamed = load_excluded(os.path.join(here, "data", "confirmed.txt"))
    agents = {r["folder"]: r["agents"] for r in
              csv.DictReader(l for l in open(args.agents, encoding="utf-8") if not l.startswith("#"))}

    all_specs, T = [], dict(sloc=0, sessions=0, dated=0, specs=0, traced=0, total=0)
    for pid, name, folder, path in repos(args.projects):
        a = project_row(pid, name, path)
        specs, (traced, total) = analyze(path)
        tests = project_tests(path, name, gamed.get(folder, []), None, count_lines=False)
        T["tests"] = T.get("tests", 0) + tests["cases"]
        all_specs += specs
        for k in ("sloc", "sessions", "dated", "specs"):
            T[k] += a[k]
        T["traced"] += traced
        T["total"] += total
        mark = lambda col: MARKS[col].get(folder, "")
        bold = lambda text, fail: f"\\textbf{{{text}}}" if fail else text
        sloc = f"{a['sloc']:,}"
        if a["sloc"] >= 100_000:
            sloc = "\\cellcolor{green!25}" + sloc
        cells = [
            str(pid), f"\\textsf{{{name}}}" + mark("name"), agents.get(folder, ""), sloc,
            "\\checkmark" if a["url"] else "\\textbf{$\\times$}",
            bold(f"{a['dated']}/{a['specs']}", a["dated"] == 0),
            bold(str(a["sessions"]), a["sessions"] == 0),
            bold(pct(a["trailers"]), a["trailers"] is not None and a["trailers"] < 0.1),
            bold(str(a["authors"]), a["authors"] < 2) + mark("authors"),
            f"{tests['cases']:,}",
            pct(a["spec_first"]) + mark("spec_first"),
            pct(sum(1 for r in specs if r["author"] == "agent") / len(specs)) if specs else "--",
            pct(share(specs, "ac")) + mark("ac"),
            pct(share(specs, "referenced")), pct(share(specs, "with_code")), pct(share(specs, "revised")),
            pct(traced / total if total else None),
        ]
        print(" & ".join(cells) + " \\\\")
    b = lambda x: f"\\textbf{{{x}}}"
    S = all_specs
    print("\\midrule")
    print(" & ".join(["", b("Total"), "", b(f"{T['sloc']:,}"), "", b(f"{T['dated']}/{T['specs']}"),
                      b(T["sessions"]), "", "", b(f"{T['tests']:,}"), "",
                      b(pct(sum(1 for r in S if r["author"] == "agent") / len(S))), b(pct(share(S, "ac"))),
                      b(pct(share(S, "referenced"))), b(pct(share(S, "with_code"))),
                      b(pct(share(S, "revised"))), b(pct(T["traced"] / T["total"]))]) + " \\\\")


if __name__ == "__main__":
    main()
