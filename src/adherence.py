#!/usr/bin/env python3
"""Adherence checks (Section "Data Collection and Analysis"), table of
adherence, the description of the projects (Participants and Projects), and RQ1.

Usage:
  python3 -I src/adherence.py PROJECTS_DIR [--latex]

PROJECTS_DIR (or the environment variable PROJECTS_DIR) holds one git clone
per team. Requires git and perl (for the bundled cloc 1.98).
"""
import argparse
import os
import re
import statistics
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (git, load_commits, authorship, trailer_values, is_spec, is_openspec,  # noqa: E402
                    NONE_VALUES, AGENTS, repos, sessions)

HERE = os.path.dirname(os.path.abspath(__file__))
CLOC = os.path.join(HERE, "..", "vendor", "cloc-1.98.pl")
CLOC_ARGS = ["--vcs=git", "--exclude-dir=node_modules,vendor,dist,build,prompts",
             "--exclude-lang=Markdown,JSON,YAML,CSV,Text,SVG",
             r"--not-match-f=(lock|\.min\.)", "--csv", "--quiet"]

DATED = re.compile(r"^\d{4}-\d{2}-\d{2}-.+\.md$")
URL = re.compile(r"https?://[^\s)\]>\"'`]+")
NOT_APP = re.compile(r"github\.com|githubusercontent|localhost|127\.0\.0\.1|shields\.io|"
                     r"astral\.sh|nextjs\.org|typescriptlang|themoviedb|justwatch|"
                     r"docs\.|/docs\b|/reference", re.I)


def has_url(repo):
    path = os.path.join(repo, "README.md")
    if not os.path.exists(path):
        return False
    text = open(path, encoding="utf-8", errors="ignore").read()
    return any(not NOT_APP.search(u) for u in URL.findall(text))


def sloc(repo):
    out = subprocess.run(["perl", CLOC, ".", *CLOC_ARGS], cwd=repo,
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split(",")
        if len(parts) >= 5 and parts[1] == "SUM":
            return int(parts[4])
    return 0


def spec_first(commits, spec_paths):
    """Among (commit, file) pairs in which a Spec: trailer names a file in
    SPEC/, the share in which that file had been added in an earlier commit.
    None if no trailer names a file."""
    added = {}
    for i, c in enumerate(commits):
        for status, path in c["files"]:
            if status == "A" and path not in added:
                added[path] = i
    tagged = earlier = 0
    for i, c in enumerate(commits):
        files = []
        for v in trailer_values(c["body"], "Spec"):
            for part in re.split(r"[,;\s]+", v):
                part = part.strip("`").lstrip("./")
                if not part.startswith("SPEC/"):
                    part = "SPEC/" + part if DATED.match(part) else part
                if part.startswith("SPEC/") and part.endswith(".md"):
                    files.append(part)
        for f in files:
            tagged += 1
            earlier += added.get(f, len(commits)) < i
    return earlier / tagged if tagged else None


def load_mailmap(path):
    """Alias e-mail -> canonical e-mail, from a git mailmap ("<canonical> <alias>" lines)."""
    aliases = {}
    if path:
        for line in open(path, encoding="utf-8"):
            emails = re.findall(r"<([^>]*)>", line.split("#")[0])
            if len(emails) == 2:
                aliases[emails[1].lower()] = emails[0].lower()
    return aliases


# Committers who used several e-mails (e.g., a personal address and GitHub's
# no-reply address) are merged through the mailmap in $COMMITTERS_MAILMAP.
MAILMAP = load_mailmap(os.environ.get("COMMITTERS_MAILMAP"))


def human_authors(commits):
    """Distinct human committers, after merging the e-mails of the same person."""
    emails = {c["email"].lower() for c in commits
              if not AGENTS.search(c["author"]) and not AGENTS.search(c["email"])}
    return {MAILMAP.get(e, e) for e in emails}


def merged_aliases(commits):
    """Alias e-mails of this project merged by the mailmap."""
    return {c["email"].lower() for c in commits if c["email"].lower() in MAILMAP}


def both_trailers(commits):
    return sum(1 for c in commits if trailer_values(c["body"], "Agent")
               and trailer_values(c["body"], "Spec")) / len(commits)


def project_row(pid, name, path):
    """Adherence measures of one project."""
    commits = load_commits(path)
    head = git(path, "ls-files").splitlines()
    specs = [p for p in head if is_spec(p)]
    dated = sum(1 for p in specs if p.startswith("SPEC/") and DATED.match(os.path.basename(p)))
    r = dict(id=pid, name=name, url=has_url(path),
             spec_dir=any(p.startswith('SPEC/') for p in head), dated=dated, specs=len(specs),
             spec_first=spec_first(commits, specs), sessions=len(sessions(path)),
             trailers=both_trailers(commits), authors=len(human_authors(commits)),
             aliases=len(merged_aliases(commits)), sloc=sloc(path), commits=len(commits),
             agent_commits=sum(1 for c in commits if authorship(c) == "agent"))
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("projects", nargs="?", default=os.environ.get("PROJECTS_DIR"))
    ap.add_argument("--latex", action="store_true")
    args = ap.parse_args()
    if not args.projects:
        ap.error("pass PROJECTS_DIR as an argument or environment variable")

    rows = [project_row(pid, name, path) for pid, name, folder, path in repos(args.projects)]

    f = lambda x: "--" if x is None else f"{100 * x:.0f}%"
    print(f"{'ID':>2} {'Project':18} URL Specs  First Sess Trail Auth     SLOC Commits Agent")
    for r in rows:
        print(f"{r['id']:>2} {r['name']:18} {'yes' if r['url'] else 'NO ':3} "
              f"{r['dated']:>2}/{r['specs']:<2} {f(r['spec_first']):>5} {r['sessions']:>4} "
              f"{f(r['trailers']):>5} {r['authors']:>4} {r['sloc']:>8,} "
              f"{r['commits']:>7} {r['agent_commits']:>5}")

    s = [r["sloc"] for r in rows]
    top = sorted(rows, key=lambda r: -r["sloc"])
    reached = [r for r in rows if r["sloc"] >= 100_000]
    nc = sum(r["commits"] for r in rows)
    na = sum(r["agent_commits"] for r in rows)
    sf = [r["spec_first"] for r in rows if r["spec_first"] is not None]
    print()
    print(f"SLOC total {sum(s):,}; median {statistics.median(s):,.0f}; min {min(s):,}; max {max(s):,}")
    print("reached 100,000: " + ", ".join(f"{r['name']} ({r['sloc']:,})" for r in reached)
          + f"; share of all code {100 * sum(r['sloc'] for r in reached) / sum(s):.0f}%")
    print(f"commits {nc:,}; attributed to an agent {na} ({100 * na / nc:.0f}%)")
    print(f"projects with URL {sum(r['url'] for r in rows)}; with SPEC/ "
          f"{sum(r['spec_dir'] for r in rows)}")
    if not MAILMAP:
        print("WARNING: COMMITTERS_MAILMAP not set; authors are counted by e-mail")
    merged = [r for r in rows if r["aliases"]]
    print(f"disambiguation: {sum(r['aliases'] for r in merged)} alias e-mails merged in "
          f"{len(merged)} projects ({', '.join(r['name'] for r in merged)})")
    print("single human committer: " + ", ".join(f"{r['name']} ({r['authors']})" for r in rows if r["authors"] < 2))
    print(f"spec first computable in {len(sf)} projects, range {100 * min(sf):.0f}%--{100 * max(sf):.0f}%")
    print(f"no session: {sum(r['sessions'] == 0 for r in rows)}; one session: "
          f"{sum(r['sessions'] == 1 for r in rows)}")
    t = [r["trailers"] for r in rows]
    print(f"both trailers: median {100 * statistics.median(t):.0f}%; projects with none "
          f"{sum(x == 0 for x in t)}")
    print(f"single human author: {sum(r['authors'] == 1 for r in rows)}; no human author: "
          f"{sum(r['authors'] == 0 for r in rows)}")

    if args.latex:
        print()
        yes, no = "\\yes", "\\no"
        lp = lambda x: f(x).replace("%", "\\%")
        for r in rows:
            cells = [str(r["id"]), r["name"], yes if r["url"] else no, f"{r['dated']}/{r['specs']}",
                     lp(r["spec_first"]), str(r["sessions"]), lp(r["trailers"]), str(r["authors"]),
                     f"{r['sloc']:,}"]
            print(" & ".join(cells) + " \\\\")


if __name__ == "__main__":
    main()
