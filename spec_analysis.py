#!/usr/bin/env python3
"""Specification analysis (Section "Specification Analysis" of the paper).

For every specification in the last commit of each repository, computes:

  Authorship    agent / human / undeclared, from the commit that added it
  Structure     sections "what and why", "acceptance criteria", "out of scope",
                identified by heading, and the number of acceptance criteria
  Traceability  referenced, added with code, revised after implementation,
                and, per repository, the share of added lines traced to a spec

Usage:
  python3 spec_analysis.py [PROJECTS_DIR] [--csv specs.csv]

PROJECTS_DIR (or the environment variable PROJECTS_DIR) holds one git clone per team.
Only the Python standard library and git are required.
"""
import argparse
import csv
import os
import re
import statistics
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (PROJECTS, OPENSPEC, is_spec, is_openspec, excluded_from_lines, is_code,
                    git, load_commits, authorship, trailer_values, NONE_VALUES, AGENTS)

# ---------------------------------------------------------------- structure

WHY = re.compile(r"o qu[eê]|por ?qu|objetivo|motiva|problema|contexto|\bwhat\b|\bwhy\b|"
                 r"purpose|vis[aã]o geral|overview", re.I)
AC = re.compile(r"crit[eé]rios? de aceit|acceptance|\baceite\b", re.I)
OOS = re.compile(r"fora d[eo] escopo|out of scope|non-goals|n[aã]o[- ]objetivos", re.I)
HEADING = re.compile(r"^(#{1,6})\s+(.*)")
ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s+\S")
ROW = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}")
SCENARIO = re.compile(r"^\s*(-\s*)?\*\*WHEN\*\*|^\s*-\s*WHEN\b", re.M)


def structure(text, openspec=False):
    """Returns (has_why, has_ac, has_oos, n_criteria).

    A section spans from its heading to the next heading of the same or higher
    level, so criteria grouped under subsections are counted.
    """
    lines = text.splitlines()
    heads = [(i, len(m.group(1)), m.group(2)) for i, l in enumerate(lines)
             if (m := HEADING.match(l))]
    has_why = any(WHY.search(h) for _, _, h in heads)
    has_oos = any(OOS.search(h) for _, _, h in heads)
    if openspec:
        n = len(SCENARIO.findall(text))
        return has_why, n > 0, has_oos, n
    n = 0
    for k, (i, level, h) in enumerate(heads):
        if not AC.search(h):
            continue
        end = next((j for j, lv, _ in heads[k + 1:] if lv <= level), len(lines))
        section = lines[i + 1:end]
        rows = [l for l in section if ROW.match(l) and not TABLE_SEP.match(l)]
        n += sum(1 for l in section if ITEM.match(l))
        n += max(len(rows) - 1, 0)  # minus the header row
    return has_why, n > 0, has_oos, n


# ---------------------------------------------------------------- traceability

def normalize(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return s


def words(s):
    return {w for w in re.split(r"[^a-z0-9]+", normalize(s)) if len(w) >= 3 and not w.isdigit()}


def resolve(value, specs, present):
    """Maps the value of a Spec: trailer to spec paths.

    First by file name, among all specifications; otherwise by the words of
    the value that appear in the names of the specifications present at that
    commit, keeping the files with the largest overlap.
    """
    targets = []
    for part in re.split(r"[,;]| e | and ", value):
        part = part.strip().strip("`")
        if not part or NONE_VALUES.match(part):
            continue
        base = os.path.basename(part)
        exact = [s for s in specs if s == part or os.path.basename(s) == base
                 or os.path.basename(s) == base + ".md"
                 or (is_openspec(s) and s.split("/")[-2] == base)]
        if exact:
            targets += exact
            continue
        w = words(part)
        if not w:
            continue
        scored = [(len(w & words(os.path.basename(s) if not is_openspec(s) else s.split("/")[-2])), s)
                  for s in present]
        best = max((sc for sc, _ in scored), default=0)
        if best > 0:
            targets += [s for sc, s in scored if sc == best]
    return set(targets)


# ---------------------------------------------------------------- analysis

def analyze(repo):
    head = git(repo, "ls-files").splitlines()
    specs = sorted(p for p in head if is_spec(p))
    commits = load_commits(repo)
    index = {c["hash"]: i for i, c in enumerate(commits)}

    added_in = {}
    for c in commits:
        for status, path in c["files"]:
            if path in specs and status == "A" and path not in added_in:
                added_in[path] = c["hash"]
    for s in specs:  # files whose first appearance is not an "A" (e.g., after a rename)
        if s not in added_in:
            first = git(repo, "log", "--reverse", "--format=%H", "--", s).split()
            if first:
                added_in[s] = first[0]

    links = {}  # commit -> specs it points to
    for c in commits:
        present = [s for s in specs if s in added_in
                   and index.get(added_in[s], len(commits)) <= index[c["hash"]]]
        targets = set()
        for v in trailer_values(c["body"], "Spec"):
            targets |= resolve(v, specs, present)
        links[c["hash"]] = targets

    rows = []
    for s in specs:
        text = open(os.path.join(repo, s), encoding="utf-8", errors="ignore").read()
        has_why, has_ac, has_oos, n_ac = structure(text, is_openspec(s))
        add = added_in.get(s)
        add_commit = commits[index[add]] if add in index else None
        implementing = [c for c in commits if s in links[c["hash"]]]
        with_code = bool(add_commit) and any(is_code(p) for _, p in add_commit["files"])
        revised = False
        early = bool(implementing) and add in index and index[implementing[0]["hash"]] < index[add]
        if implementing:
            first = index[implementing[0]["hash"]]
            revised = any(s == p and st == "M"
                          for c in commits[first + 1:] for st, p in c["files"])
        rows.append(dict(
            spec=s, words=len(text.split()),
            author=authorship(add_commit) if add_commit else "undeclared",
            why=has_why, ac=has_ac, oos=has_oos, criteria=n_ac,
            referenced=bool(implementing), referenced_before=early,
            with_code=with_code, revised=revised))

    total = traced = 0
    for c in commits:
        existing = {s for s in links[c["hash"]]
                    if s in added_in and index.get(added_in[s], 1e9) <= index[c["hash"]]}
        for path, n in c["added"].items():
            if excluded_from_lines(path):
                continue
            total += n
            if existing:
                traced += n
    return rows, (traced, total)


def pct(xs, key):
    return 100 * sum(1 for x in xs if x[key]) / len(xs) if xs else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("projects", nargs="?", default=os.environ.get("PROJECTS_DIR"))
    ap.add_argument("--csv", help="write one row per specification")
    ap.add_argument("--latex", action="store_true", help="print the rows of the LaTeX table")
    args = ap.parse_args()
    if not args.projects:
        ap.error("pass PROJECTS_DIR as an argument or environment variable")

    allrows, L, latex = [], [0, 0], []
    head = (f"{'ID':>2} {'Project':18} {'Specs':>5} {'Words':>6} {'Agent':>6} {'Human':>6} "
            f"{'Why':>5} {'AC':>5} {'OOS':>5} {'Crit':>5} {'Ref':>5} {'WCode':>6} {'Rev':>5} {'Traced':>7}")
    print(head)
    for folder, (pid, name) in sorted(PROJECTS.items(), key=lambda kv: kv[1][0]):
        repo = os.path.join(args.projects, folder)
        if not os.path.isdir(os.path.join(repo, ".git")):
            print(f"{pid:>2} {name:18} (missing)", file=sys.stderr)
            continue
        rows, (traced, total) = analyze(repo)
        for r in rows:
            r["project"] = name
        allrows += rows
        L[0] += traced
        L[1] += total
        n = len(rows)
        latex.append((pid, name, rows, traced, total))
        med = statistics.median(r["words"] for r in rows) if rows else 0
        print(f"{pid:>2} {name:18} {n:>5} {med:>6.0f} "
              f"{pct([dict(x=r['author'] == 'agent') for r in rows], 'x'):>5.0f}% "
              f"{pct([dict(x=r['author'] == 'human') for r in rows], 'x'):>5.0f}% "
              f"{pct(rows, 'why'):>4.0f}% {pct(rows, 'ac'):>4.0f}% {pct(rows, 'oos'):>4.0f}% "
              f"{sum(r['criteria'] for r in rows):>5} {pct(rows, 'referenced'):>4.0f}% "
              f"{pct(rows, 'with_code'):>5.0f}% {pct(rows, 'revised'):>4.0f}% "
              f"{100 * traced / total if total else 0:>6.0f}%")
    rows = allrows
    print(f"{'':>2} {'Total':18} {len(rows):>5} {statistics.median(r['words'] for r in rows):>6.0f} "
          f"{pct([dict(x=r['author'] == 'agent') for r in rows], 'x'):>5.0f}% "
          f"{pct([dict(x=r['author'] == 'human') for r in rows], 'x'):>5.0f}% "
          f"{pct(rows, 'why'):>4.0f}% {pct(rows, 'ac'):>4.0f}% {pct(rows, 'oos'):>4.0f}% "
          f"{sum(r['criteria'] for r in rows):>5} {pct(rows, 'referenced'):>4.0f}% "
          f"{pct(rows, 'with_code'):>5.0f}% {pct(rows, 'revised'):>4.0f}% "
          f"{100 * L[0] / L[1]:>6.0f}%")

    # RQ2.1: specifications by authorship
    print()
    for group in ("agent", "human", "undeclared"):
        g = [r for r in rows if r["author"] == group]
        if g:
            print(f"{group:10} n={len(g):3}  with criteria {pct(g, 'ac'):3.0f}%  "
                  f"median words {statistics.median(r['words'] for r in g):5.0f}  "
                  f"never referenced {100 - pct(g, 'referenced'):3.0f}%")
    print(f"referenced by a commit made before the spec existed: "
          f"{sum(r['referenced_before'] for r in rows)}")
    print(f"added in the same commit as code: {sum(r['with_code'] for r in rows)} of {len(rows)}")

    if args.latex:
        print()
        p = lambda xs, k: f"{pct(xs, k):.0f}\\%"
        for pid, name, rs, traced, total in latex:
            med = statistics.median(r["words"] for r in rs)
            agent = pct([dict(x=r["author"] == "agent") for r in rs], "x")
            print(f"{pid} & {name} & {len(rs)} & {med:,.0f} & {agent:.0f}\\% & {p(rs, 'why')} & "
                  f"{p(rs, 'ac')} & {p(rs, 'oos')} & {sum(r['criteria'] for r in rs):,} & "
                  f"{p(rs, 'referenced')} & {p(rs, 'with_code')} & {p(rs, 'revised')} & "
                  f"{100 * traced / total if total else 0:.0f}\\% \\\\")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["project", "spec", "words", "author", "why", "ac",
                                              "oos", "criteria", "referenced", "referenced_before",
                                              "with_code", "revised"])
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
