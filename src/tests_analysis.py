#!/usr/bin/env python3
"""Automated tests in the projects (not required by the assignment).

Usage:
  python3 -I src/tests_analysis.py PROJECTS_DIR [--cloc CLOC] [--exclude data/confirmed.txt]

For each project, in its last commit:
  test files     code files under a test folder (test/, tests/, __tests__/, e2e/,
                 cypress/) or named as tests (test_*.py, *_test.*, *.test.*, *.spec.*,
                 *Test.java, *Tests.java)
  test SLOC      lines of code of those files, counted with cloc 1.98
  test cases     test functions or blocks (def test_, it(, test(, @Test, ...)
  frameworks     test frameworks declared in package.json, requirements, or pom.xml
  CI             a workflow under .github/workflows that runs tests
Files listed in --exclude (candidates confirmed as gaming) are reported separately.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import git, repos  # noqa: E402

CODE = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java")
TEST_DIR = re.compile(r"(^|/)(tests?|__tests__|e2e|cypress|spec)/", re.I)
TEST_NAME = re.compile(r"(^test_.*\.py$|_test\.\w+$|\.(test|spec)\.\w+$|Tests?\.java$)", re.I)
CASES = re.compile(r"^\s*(async\s+)?def\s+test_\w*|^\s*(it|test)(\.each\([^)]*\))?\s*\(|^\s*@(Test|ParameterizedTest)\b",
                   re.M)
FRAMEWORKS = ["pytest", "unittest", "jest", "vitest", "mocha", "playwright", "cypress", "supertest",
              "junit", "testing-library", "httpx"]
EXCLUDED_DIRS = re.compile(r"(^|/)(node_modules|vendor|dist|build|prompts)/")


def is_test(path):
    return (path.endswith(CODE) and not EXCLUDED_DIRS.search(path)
            and (TEST_DIR.search(path) or TEST_NAME.search(os.path.basename(path))))


def cloc_lines(repo, files, cloc):
    if not files:
        return 0
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("\n".join(files))
        name = f.name
    out = subprocess.run(["perl", cloc, "--list-file=" + name, "--json", "--quiet"],
                         cwd=repo, capture_output=True, text=True).stdout
    os.unlink(name)
    try:
        return json.loads(out)["SUM"]["code"]
    except (ValueError, KeyError):
        return 0


def frameworks(repo, files):
    found = set()
    for f in files:
        base = os.path.basename(f)
        if base in ("package.json", "pom.xml", "build.gradle", "pyproject.toml") or base.startswith("requirements"):
            text = open(os.path.join(repo, f), encoding="utf-8", errors="ignore").read().lower()
            found |= {fw for fw in FRAMEWORKS if fw in text}
    return sorted(found)


def ci_runs_tests(repo, files):
    for f in files:
        if f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml")):
            text = open(os.path.join(repo, f), encoding="utf-8", errors="ignore").read().lower()
            if re.search(r"\b(pytest|jest|vitest|npm (run )?test|pnpm (run )?test|yarn test|mvn .*test|playwright)",
                         text):
                return True
    return False


def project_tests(path, name, gamed_prefixes, cloc, count_lines=True):
    """Test measures of one project; files under gamed_prefixes are left out."""
    files = git(path, "ls-files").splitlines()
    prefixes = tuple(gamed_prefixes)
    tests = [f for f in files if is_test(f)]
    gamed = [f for f in tests if prefixes and f.startswith(prefixes)]
    real = [f for f in tests if f not in gamed]
    cases = sum(len(CASES.findall(open(os.path.join(path, f), encoding="utf-8", errors="ignore").read()))
                for f in real)
    code = [f for f in files if f.endswith(CODE) and not EXCLUDED_DIRS.search(f)
            and not (prefixes and f.startswith(prefixes))]
    return dict(name=name, files=len(real), cases=cases, gamed=len(gamed),
                sloc=cloc_lines(path, real, cloc) if count_lines else None,
                code=cloc_lines(path, code, cloc) if count_lines else None,
                ci=ci_runs_tests(path, files), fw=frameworks(path, files))


def load_excluded(path):
    excluded = {}
    if path and os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if line.strip() and not line.startswith("#"):
                folder, prefix = line.split()
                excluded.setdefault(folder, []).append(prefix)
    return excluded


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("projects", nargs="?", default=os.environ.get("PROJECTS_DIR"))
    ap.add_argument("--cloc", default=os.path.join(here, "..", "vendor", "cloc-1.98.pl"))
    ap.add_argument("--exclude", default=os.path.join(here, "..", "data", "confirmed.txt"),
                    help='lines "<project folder> <path prefix>" of confirmed gaming')
    args = ap.parse_args()
    if not args.projects:
        ap.error("pass PROJECTS_DIR as an argument or environment variable")
    excluded = {}
    if args.exclude and os.path.exists(args.exclude):
        for line in open(args.exclude, encoding="utf-8"):
            if line.strip() and not line.startswith("#"):
                folder, prefix = line.split()
                excluded.setdefault(folder, []).append(prefix)

    print(f"{'ID':>2} {'Project':14} {'files':>5} {'SLOC':>7} {'cases':>6} {'%code':>6} "
          f"{'gamed':>6}  CI  frameworks")
    rows = []
    for pid, name, folder, path in repos(args.projects):
        r = project_tests(path, name, excluded.get(folder, []), args.cloc)
        rows.append(r)
        cases, gamed = r["cases"], r["gamed"]
        share = 100 * r["sloc"] / r["code"] if r["code"] else 0
        print(f"{pid:>2} {name:14} {r['files']:>5} {r['sloc']:>7,} {cases:>6} {share:>5.0f}% "
              f"{gamed:>6}  {'yes' if r['ci'] else ' - '} {', '.join(r['fw'])}")

    with_tests = [r for r in rows if r["cases"] > 0]
    print(f"\nprojects with at least one test case (excluding confirmed gaming): {len(with_tests)} of {len(rows)}")
    print(f"projects with tests run in CI: {sum(r['ci'] for r in rows)}")
    ts, cs = sum(r["sloc"] for r in rows), sum(r["code"] for r in rows)
    print(f"test SLOC {ts:,} of {cs:,} code SLOC ({100 * ts / cs:.0f}%), excluding confirmed gaming; "
          f"test cases {sum(r['cases'] for r in rows):,}")
    shares = sorted(100 * r["sloc"] / r["code"] for r in rows if r["code"])
    print(f"median share of test code per project: {shares[len(shares) // 2]:.0f}%")


if __name__ == "__main__":
    main()
