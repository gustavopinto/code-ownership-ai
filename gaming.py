#!/usr/bin/env python3
"""Requirement gaming audit (Section "Requirement Gaming Analysis", RQ5).

Gaming: meeting the letter of a requirement without its purpose. Each check
derives from one requirement of the assignment and runs on every project;
negatives are reported too. Every candidate is meant for manual inspection.

  100,000 lines -> code that is counted but is not application
    L1 unreachable  code files that no entry point reaches through imports
    L2 duplicated   lines inside token windows that occur more than once in
                    the project (identifiers and literals normalized, windows
                    of 100 tokens, in the spirit of PMD CPD)
    L3 generators   scripts that write source files from a loop
    L4 empty tests  test files that import no application code
    L*  unused duplicated code: duplicated lines (L2) in unreachable files,
        in tests importing no application code, or in definitions never
        referenced elsewhere; plus the generator scripts that write them
  Specification before code -> forged process record
    S1 rewritten history  force pushes, branch creations and deletions
                          (GitHub activity API; needs --github)
    S2 synthetic times    specification commits whose seconds are 00
                          (expected rate 1/60; binomial p-value)
    S3 date mismatch      date in the specification file name differs from
                          the date of the commit that added it
    S4 retroactive        specifications that declare they were written or
                          reconstructed after the code
  Complete record -> missing sessions
    R1 commits declaring an agent on a day without any recorded session
  Size target in the sessions
    T1 session files that mention the target (100k, cloc, volume, ...)

Usage:
  python3 -I gaming.py [PROJECTS_DIR] [--cloc CLOC] [--github FILE] [--until DATE]
                       [--api-cache FILE] [--confirmed FILE] [--json OUT]
  --github FILE  lines "<project folder> <owner>/<repo>"; GITHUB_TOKEN is used if set
  --until DATE   marks activity after DATE (YYYY-MM-DD) as after data collection
  --confirmed FILE  lines "<project folder> <path prefix>": candidates confirmed by
                 manual inspection; their L* lines are summed per project
"""
import argparse
import csv
import gzip
import io
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (git, is_spec, is_openspec, load_commits, repos, default_projects_dir,  # noqa: E402
                    trailer_values, NONE_VALUES)

CLOC_ARGS = ["--vcs=git", "--exclude-dir=node_modules,vendor,dist,build,prompts",
             "--exclude-lang=Markdown,JSON,YAML,CSV,Text,SVG",
             r"--not-match-f=(lock|\.min\.)", "--quiet", "--csv", "--by-file"]
WINDOW = 100
SOURCE_EXT = r"\.(py|js|jsx|mjs|cjs|ts|tsx|java|kt|go|rb|php|cs|vue|svelte|html|css|scss)\b"
TEST = re.compile(r"(^|/)(tests?|__tests__|e2e)/|(^|/)test_[^/]+\.py$|_test\.py$|\.(test|spec)\.[jt]sx?$")
CONFIG = re.compile(r"(^|/)[^/]*\.config\.[a-z]+$|(^|/)(conftest|setup|settings|config)\.py$|"
                    r"(^|/)(babel|eslint|postcss|tailwind|jest|vite|vitest|webpack|next|playwright)"
                    r"\.config\.|(^|/)\.[^/]+rc\.[a-z]+$")
ENTRY_NAME = re.compile(r"(^|/)(main|app|server|cli|manage|wsgi|asgi|__main__|run|start|worker)"
                        r"\.(py|js|mjs|cjs|ts|tsx|jsx)$")
ROUTE = re.compile(r"(^|/)(pages|app|routes)/.*\b(page|layout|route|loading|error|"
                   r"not-found|template|default|_app|_document|\+page|\+layout|\+server)"
                   r"\.(tsx?|jsx?|svelte)$|(^|/)pages/[^/]+\.(tsx?|jsx?)$")
TARGET = re.compile(r"100\s?k\b|100[.,]000 (linhas|lines|loc)|100 mil linhas|\bcloc\b|"
                    r"volum[eé]tric|volumos", re.I)
RETRO = re.compile(r"retroativ|retroactiv|retrospectiv|reconstru[ií]d|reconstructed|"
                   r"escrita depois|written after", re.I)
LOOP = re.compile(r"\bfor\b|\bwhile\b|\.forEach\(|\brange\(")
WRITE = re.compile(r"open\([^)]*['\"][wa]['\"]|write_text\(|writeFileSync\(|writeFile\(|"
                   r"createWriteStream\(")


# ---------------------------------------------------------------- helpers

def cloc_by_file(cloc, repo):
    cmd = (["perl", cloc] if cloc.endswith(".pl") else [cloc]) + ["."] + CLOC_ARGS
    out = subprocess.run(cmd, cwd=repo, capture_output=True, text=True).stdout
    files = {}
    for row in csv.reader(io.StringIO(out)):
        if len(row) >= 5 and row[0] not in ("language", "SUM", "files") and row[1] != "SUM":
            path = row[1][2:] if row[1].startswith("./") else row[1]
            files[path] = (row[0], int(row[4]))
    return files


def read(repo, path):
    p = os.path.join(repo, path)
    try:
        if p.endswith(".gz"):
            return gzip.open(p, "rt", encoding="utf-8", errors="ignore").read()
        return open(p, encoding="utf-8", errors="ignore").read()
    except OSError:
        return ""


def introduced(repo, path):
    out = git(repo, "log", "--diff-filter=A", "--format=%h|%aI|%s", "--", path).strip().splitlines()
    return out[-1] if out else ""


# ---------------------------------------------------------------- imports

JS_IMPORT = re.compile(r"""(?:import|export)\s[^'"`;]*?from\s*['"]([^'"]+)['"]|"""
                       r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)|require\(\s*['"]([^'"]+)['"]\s*\)|"""
                       r"""import\s+['"]([^'"]+)['"]|<script[^>]*src=['"]([^'"]+)['"]|"""
                       r"""<link[^>]*href=['"]([^'"]+)['"]|templateUrl:\s*['"]([^'"]+)['"]""")
PY_IMPORT = re.compile(r"^\s*(?:from\s+(\.*[\w.]*)\s+import\s+([\w., ()]+)|import\s+([\w., ]+))", re.M)
JS_EXT = ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", "/index.ts",
          "/index.tsx", "/index.js", "/index.jsx", "/index.mjs")


STAR = re.compile(r"""import\s*\*\s*as\s+\w+\s+from\s*['"]([^'"]+)['"]|export\s*\*\s*(?:as\s+\w+\s+)?from\s*['"]([^'"]+)['"]|"""
                  r"""^\s*from\s+(\.*[\w.]*)\s+import\s+\*""", re.M)


def import_graph(files, texts):
    """Edges importer -> imported, among the files counted by cloc. Edges
    created by namespace imports (import * as, export * from, import *)
    are also returned, since they use every definition of the target."""
    fileset = set(files)
    by_module = defaultdict(set)
    for f in files:
        if f.endswith(".py"):
            parts = f[:-3].split("/")
            if parts[-1] == "__init__":
                parts = parts[:-1]
            for i in range(len(parts)):
                by_module[".".join(parts[i:])].add(f)
    edges = defaultdict(set)
    for f in files:
        t, base = texts[f], os.path.dirname(f)
        if f.endswith(".py"):
            for m in PY_IMPORT.finditer(t):
                mods = []
                if m.group(1) is not None:
                    pkg = m.group(1)
                    names = [n.strip().split(" ")[0] for n in m.group(2).strip("()").split(",") if n.strip()]
                    if pkg.startswith("."):
                        d = base
                        for _ in range(len(pkg) - len(pkg.lstrip(".")) - 1):
                            d = os.path.dirname(d)
                        root = ".".join(x for x in (d.replace("/", "."), pkg.lstrip(".")) if x)
                    else:
                        root = pkg
                    mods += [root] + [root + "." + n for n in names]
                else:
                    mods += [n.strip().split(" ")[0] for n in m.group(3).split(",")]
                for mod in mods:
                    edges[f] |= by_module.get(mod.strip("."), set()) - {f}
        else:
            for m in JS_IMPORT.finditer(t):
                spec = next(x for x in m.groups() if x).split("?")[0]
                if spec.startswith(("http", "//")) or not spec.startswith((".", "/")) and "/" not in spec:
                    continue
                if spec.startswith("@/"):
                    spec = "src/" + spec[2:]
                target = os.path.normpath(os.path.join(base, spec)) if spec.startswith(".") \
                    else spec.lstrip("/")
                for cand_base in {target, os.path.join(base, target), "src/" + target}:
                    for ext in JS_EXT:
                        for cand in (cand_base + ext, re.sub(r"\.js$", "", cand_base) + ext):
                            if cand in fileset and cand != f:
                                edges[f].add(cand)
    star = set()
    for f in files:
        for m in STAR.finditer(texts[f]):
            spec = next(x for x in m.groups() if x is not None)
            for g in edges.get(f, ()):
                stem = os.path.splitext(g)[0]
                key = spec.lstrip("./").replace(".", "/") if f.endswith(".py") else spec.lstrip("./")
                if stem.endswith(key) or stem.endswith(key + "/index") or stem.endswith(key + "/__init__"):
                    star.add(g)
    return edges, star


def entry_points(repo, files, texts, generators):
    """Files that run without being imported: HTML pages, conventional entry
    names, framework routes, files named in configuration, scripts with a
    __main__ guard, tests, configuration files, and generator scripts."""
    config_text = ""
    for p in git(repo, "ls-files").splitlines():
        b = os.path.basename(p)
        if b in ("package.json", "Dockerfile", "Procfile", "vercel.json", "netlify.toml", "render.yaml",
                 "pyproject.toml", "angular.json", "docker-compose.yml", "fly.toml", "Makefile") \
                or p.startswith(".github/workflows/"):
            config_text += read(repo, p) + "\n"
    roots = set()
    for f in files:
        b = os.path.basename(f)
        if (f.endswith((".html", ".htm")) or ENTRY_NAME.search(f) or ROUTE.search(f)
                or (b.startswith("index.") and f.count("/") <= 1) or TEST.search(f) or CONFIG.search(f)
                or f in generators or f in config_text or (len(b) > 6 and b in config_text)
                or (f.endswith(".py") and re.search(r"__name__\s*==\s*['\"]__main__['\"]", texts[f]))):
            roots.add(f)
    return roots


def reachable(edges, roots):
    seen, stack = set(roots), list(roots)
    while stack:
        for g in edges.get(stack.pop(), ()):
            if g not in seen:
                seen.add(g)
                stack.append(g)
    return seen


# ---------------------------------------------------------------- duplication

TOKEN = re.compile(r"""'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*"|`(?:\\.|[^`\\])*`|"""
                   r"""\d+(?:\.\d+)?|[A-Za-z_$][\w$]*|==+|!=+|<=|>=|=>|&&|\|\||\S""")
KEYWORDS = set("""if else for while do return function const let var class def import from export
default new this self try except catch finally raise throw async await yield in of is not and or
None null undefined true false True False lambda with as pass break continue switch case typeof
interface type extends implements public private protected static""".split())
COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/|^[ \t]*#[^\n]*", re.S | re.M)


def tokens(text):
    """(normalized token, line) pairs; identifiers -> I, literals -> L."""
    text = COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    out = []
    for i, line in enumerate(text.split("\n")):
        for t in TOKEN.findall(line):
            if t[0] in "'\"`" or t[0].isdigit():
                out.append(("L", i))
            elif (t[0].isalpha() or t[0] in "_$") and t not in KEYWORDS:
                out.append(("I", i))
            else:
                out.append((t, i))
    return out


def duplicated_lines(texts):
    """{file: set(line numbers)} covered by a window of WINDOW normalized
    tokens that occurs at least twice in the project."""
    vocab = {}
    seqs = {}
    for f, t in texts.items():
        toks = tokens(t)
        seqs[f] = ([vocab.setdefault(k, len(vocab) + 1) for k, _ in toks], [ln for _, ln in toks])
    mod, base = (1 << 61) - 1, 1_000_003
    top = pow(base, WINDOW - 1, mod)
    count, hashes = Counter(), {}
    for f, (ids, _) in seqs.items():
        hs, h = [], 0
        for i, x in enumerate(ids):
            if i >= WINDOW:
                h = (h - ids[i - WINDOW] * top) % mod
            h = (h * base + x) % mod
            if i >= WINDOW - 1:
                hs.append(h)
        hashes[f] = hs
        count.update(hs)
    out = {}
    for f, hs in hashes.items():
        ids, lines = seqs[f]
        cover = [0] * (len(ids) + 1)
        for start, h in enumerate(hs):
            if count[h] > 1:
                cover[start] += 1
                cover[start + WINDOW] -= 1
        run, marked = 0, set()
        for i in range(len(ids)):
            run += cover[i]
            if run > 0:
                marked.add(lines[i])
        out[f] = marked
    return out


DEF = re.compile(r"^(\s*)(?:export\s+)?(?:default\s+)?(?:async\s+)?"
                 r"(?:function\*?|const|let|var|class|def)\s+([A-Za-z_$][\w$]*)")


def definitions(text):
    """(name, first line, last line) of top-level and nested definitions,
    using indentation to find where each one ends."""
    lines = text.split("\n")
    out = []
    for i, l in enumerate(lines):
        m = DEF.match(l)
        if not m:
            continue
        ind = len(m.group(1).expandtabs())
        j = i + 1
        while j < len(lines):
            s = lines[j]
            if s.strip() and len(s) - len(s.lstrip()) <= ind:
                if re.match(r"\s*[\]\)}]", s):
                    j += 1
                break
            j += 1
        out.append((m.group(2), i, j - 1))
    return out


PY_DOC = re.compile(r'^[ \t]*[rRbBuU]?("""|\'\'\')(.*?)\1', re.S | re.M)
C_COMMENT = re.compile(r"/\*.*?\*/|<!--.*?-->", re.S)


def code_lines(text, path):
    """Line numbers holding code, approximating cloc: no blank lines, no
    comment-only lines, and, in Python, no docstrings."""
    blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))
    if path.endswith(".py"):
        t = PY_DOC.sub(blank, text)
        t = re.sub(r"(?m)^[ \t]*#.*$", "", t)
    else:
        t = C_COMMENT.sub(blank, text)
        t = re.sub(r"(?m)^[ \t]*//.*$", "", t)
    return {i for i, l in enumerate(t.split("\n")) if l.strip()}


# ---------------------------------------------------------------- 100k checks

def lines_checks(repo, cloc):
    files = cloc_by_file(cloc, repo)
    total = sum(n for _, n in files.values())
    texts = {f: read(repo, f) for f in files}
    nonblank = {f: code_lines(texts[f], f) for f in files}

    generators = {f for f, t in texts.items() if f.endswith((".py", ".js", ".mjs", ".cjs", ".ts", ".sh"))
                  and LOOP.search(t) and WRITE.search(t) and re.search(SOURCE_EXT, t)}
    edges, star_imported = import_graph(list(files), texts)
    roots = entry_points(repo, files, texts, generators)
    reach = reachable(edges, roots)
    unreachable = {f for f in files if f not in reach}
    app = {f for f in files if not TEST.search(f) and not CONFIG.search(f) and f not in generators}
    empty_tests = {f for f in files if TEST.search(f) and re.search(r"test", os.path.basename(f))
                   and not CONFIG.search(f) and not (edges.get(f, set()) & app)}
    dup = duplicated_lines(texts)

    # unused duplicated code (L*)
    defs_cache = {f: definitions(texts[f]) for f in files}
    names_elsewhere = defaultdict(int)
    word = re.compile(r"[A-Za-z_$][\w$]*")
    for f, t in texts.items():
        if f in generators:
            continue
        for w in set(word.findall(t)):
            names_elsewhere[w] += 1
    unused = {}
    for f in files:
        d = dup[f] & nonblank[f]
        if not d:
            continue
        if f in unreachable or f in empty_tests:
            unused[f] = len(d)
            continue
        if f in star_imported:
            continue
        n = 0
        own = word.findall(texts[f])
        own_count = Counter(own)
        for name, a, b in defs_cache[f]:
            block = set(range(a, b + 1)) & d
            if block and names_elsewhere[name] == 1 and own_count[name] == 1:
                n += len(block)
        if n:
            unused[f] = n
    other = set()
    for p in git(repo, "ls-files").splitlines():
        if p not in generators and not p.startswith(("prompts/", "SPEC/")) and not p.endswith(".gz"):
            other |= {l.strip() for l in read(repo, p).splitlines() if l.strip()}

    def verbatim(g):
        own = [l.strip() for l in texts[g].splitlines() if l.strip()]
        return sum(l in other for l in own) / len(own) if own else 0.0

    unused_dirs = {os.path.dirname(f) for f in unused}
    gen_of_unused = {g for g in generators if any(x and x in texts[g] for x in unused_dirs)}

    return dict(
        sloc=total,
        unreachable=sorted((f, files[f][1]) for f in unreachable),
        duplicated=sum(len(dup[f] & nonblank[f]) for f in files),
        generators=sorted((g, files[g][1], introduced(repo, g), round(verbatim(g), 3)) for g in generators),
        empty_tests=sorted((f, files[f][1]) for f in empty_tests),
        unused_duplicated=sorted(((f, n, introduced(repo, f)) for f, n in unused.items()),
                                 key=lambda x: -x[1]),
        generators_of_unused=sorted((g, files[g][1]) for g in gen_of_unused),
    )


# ---------------------------------------------------------------- process checks

def local_date(iso):
    return iso[:10]


def binom_tail(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def process_checks(repo, commits):
    spec_commits = [c for c in commits if any(s == "A" and is_spec(p) for s, p in c["files"])]
    zero = [c for c in spec_commits if c["date"][17:19] == "00"]
    mismatch, retro = [], []
    for c in commits:
        for s, p in c["files"]:
            if s == "A" and is_spec(p) and not is_openspec(p):
                m = re.match(r"(\d{4}-\d{2}-\d{2})-", os.path.basename(p))
                if m and m.group(1) != local_date(c["date"]):
                    mismatch.append((p, m.group(1), local_date(c["date"])))
    for p in git(repo, "ls-files").splitlines():
        if is_spec(p):
            t = read(repo, p)
            m = RETRO.search(t)
            if m:
                retro.append((p, t[max(0, m.start() - 60):m.end() + 60].replace("\n", " ")))
    sessions = [p for p in git(repo, "ls-files", "prompts").splitlines() if not p.endswith("/.gitkeep")]
    session_days = {m.group(1) for p in sessions if (m := re.search(r"(\d{4}-\d{2}-\d{2})", p))}
    agent_days = Counter()
    for c in commits:
        v = [x for x in trailer_values(c["body"], "Agent") if x and not NONE_VALUES.match(x.split()[0])]
        if v:
            agent_days[local_date(c["date"])] += 1
    no_session = {d: n for d, n in agent_days.items() if d not in session_days}
    mentions = []
    for p in sessions:
        t = read(repo, p)
        hits = list(TARGET.finditer(t))
        if hits:
            m = hits[0]
            mentions.append((p, len(hits), t[max(0, m.start() - 80):m.end() + 80].replace("\n", " ")))
    return dict(
        spec_commits=len(spec_commits),
        zero_seconds=[(c["hash"][:7], c["date"]) for c in zero],
        zero_p=binom_tail(len(zero), len(spec_commits), 1 / 60) if spec_commits else 1.0,
        date_mismatch=mismatch, retroactive=retro,
        agent_commit_days_without_session=no_session,
        agent_commits_without_session=sum(no_session.values()),
        target_mentions=mentions,
    )


# ---------------------------------------------------------------- GitHub

API_CACHE = {}


def api(url):
    if url in API_CACHE:
        return API_CACHE[url]
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "gaming-audit"})
    if os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", "Bearer " + os.environ["GITHUB_TOKEN"])
    with urllib.request.urlopen(req, timeout=30) as r:
        API_CACHE[url] = json.load(r)
    return API_CACHE[url]


def paged(url):
    out, page = [], 1
    while True:
        batch = api(f"{url}{'&' if '?' in url else '?'}per_page=100&page={page}")
        out += batch
        if len(batch) < 100:
            return out
        page += 1


def github_checks(slug, until):
    ev = paged(f"https://api.github.com/repos/{slug}/activity")
    created = api(f"https://api.github.com/repos/{slug}")["created_at"]
    rows = []
    for e in sorted(ev, key=lambda e: e["timestamp"]):
        if e["activity_type"] not in ("force_push", "branch_creation", "branch_deletion"):
            continue
        r = dict(time=e["timestamp"], type=e["activity_type"], ref=e["ref"],
                 before=e["before"][:7], after=e["after"][:7],
                 after_collection=bool(until) and e["timestamp"][:10] > until)
        if e["activity_type"] == "force_push" and set(e["before"]) != {"0"}:
            try:
                commits = paged(f"https://api.github.com/repos/{slug}/commits?sha={e['before']}")
                tree = api(f"https://api.github.com/repos/{slug}/git/trees/{e['before']}?recursive=1")
                r["replaced_history"] = dict(
                    commits=len(commits),
                    specs=sum(1 for t in tree.get("tree", []) if is_spec(t["path"])),
                    first=commits[-1]["commit"]["author"]["date"] if commits else None,
                    messages=[(c["sha"][:7], c["commit"]["author"]["date"],
                               c["commit"]["message"].splitlines()[0]) for c in commits],
                    agent_trailers=sum("Agent:" in c["commit"]["message"] for c in commits))
            except Exception as ex:  # noqa: BLE001
                r["replaced_history"] = f"unavailable ({ex})"
        rows.append(r)
    time.sleep(0.3)
    return dict(created=created, events=rows)


# ---------------------------------------------------------------- main

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("projects", nargs="?", default=os.environ.get("PROJECTS_DIR"))
    ap.add_argument("--cloc", default=os.path.join(here, "cloc-1.98.pl"))
    ap.add_argument("--github", help='file with lines "<project folder> <owner>/<repo>"')
    ap.add_argument("--until", help="data collection date (YYYY-MM-DD)")
    ap.add_argument("--api-cache", help="JSON file caching GitHub API responses (read and updated)")
    ap.add_argument("--confirmed", help='file with lines "<project folder> <path prefix>" of the '
                                        "candidates confirmed by manual inspection")
    ap.add_argument("--json", help="write all results as JSON")
    args = ap.parse_args()
    if not args.projects:
        ap.error("pass PROJECTS_DIR as an argument or environment variable")
    if args.api_cache and os.path.exists(args.api_cache):
        API_CACHE.update(json.load(open(args.api_cache, encoding="utf-8")))
    confirmed = defaultdict(list)
    if args.confirmed:
        for l in open(args.confirmed, encoding="utf-8"):
            if l.strip() and not l.startswith("#"):
                folder, prefix = l.split()
                confirmed[folder].append(prefix)
    if not os.path.exists(args.cloc):
        args.cloc = "cloc"
    slugs = {}
    if args.github:
        slugs = dict(l.split() for l in open(args.github, encoding="utf-8") if l.strip())

    results, table = {}, []
    for pid, name, folder, path in repos(args.projects):
        commits = load_commits(path)
        r = dict(lines=lines_checks(path, args.cloc), process=process_checks(path, commits))
        if folder in slugs:
            try:
                r["github"] = github_checks(slugs[folder], args.until)
            except Exception as ex:  # noqa: BLE001
                r["github"] = f"unavailable ({ex})"
        results[name] = r
        L, P, G = r["lines"], r["process"], r.get("github")
        if confirmed.get(folder):
            pre = tuple(confirmed[folder])
            gens = {g for g, _ in L["generators_of_unused"]}
            code = sum(n for f, n, _ in L["unused_duplicated"] if f.startswith(pre) and f not in gens)
            gen = sum(n for g, n in L["generators_of_unused"] if g.startswith(pre))
            r["confirmed"] = dict(code=code, generators=gen, total=code + gen,
                                  share=(code + gen) / L["sloc"], without=L["sloc"] - code - gen)
        fp = [e for e in G["events"] if e["type"] == "force_push" and not e["after_collection"]] \
            if isinstance(G, dict) else None
        table.append((pid, name, L["sloc"], len(L["unreachable"]), sum(n for _, n in L["unreachable"]),
                      L["duplicated"], len(L["generators"]), len(L["empty_tests"]),
                      sum(n for _, n, _ in L["unused_duplicated"]) + sum(n for _, n in L["generators_of_unused"]),
                      "-" if fp is None else len(fp), f"{len(P['zero_seconds'])}/{P['spec_commits']}",
                      len(P["date_mismatch"]), len(P["retroactive"]), P["agent_commits_without_session"],
                      len(P["target_mentions"])))

    hdr = ("ID", "Project", "SLOC", "L1 files", "L1 lines", "L2 dup", "L3 gen", "L4 tests", "L* unused",
           "S1 fpush", "S2 :00", "S3 date", "S4 retro", "R1 no-sess", "T1 target")
    print(" | ".join(hdr))
    for row in table:
        print(" | ".join(f"{x:,}" if isinstance(x, int) else str(x) for x in row))
    failed = [n for n, r in results.items() if isinstance(r.get("github"), str)]
    if args.github and failed:
        msg = (f"WARNING: GitHub activity unavailable for {len(failed)} projects "
               f"({results[failed[0]]['github']}); S1 is incomplete. The unauthenticated API "
               "allows 60 requests per hour: rerun later or set GITHUB_TOKEN.")
        print(msg, file=sys.stderr)
        print(msg)
    print("\nProjects flagged per check (of 18):")
    for i, h in enumerate(hdr[3:], start=3):
        n = sum(1 for row in table if row[i] not in (0, "-", "0") and not str(row[i]).startswith("0/"))
        print(f"  {h}: {n}")
    tot = sum(row[2] for row in table)
    tot_unused = sum(row[8] for row in table)
    print(f"\nTotal SLOC {tot:,}; unused duplicated code and its generators {tot_unused:,}; "
          f"without them {tot - tot_unused:,}")
    print("Reach 100,000 lines: " + ", ".join(r[1] for r in table if r[2] >= 100_000) +
          "; without L*: " + (", ".join(r[1] for r in table if r[2] - r[8] >= 100_000) or "none"))

    print("\nCandidates")
    for name, r in results.items():
        L, P = r["lines"], r["process"]
        out = []
        if L["unused_duplicated"]:
            out.append(f"  L* unused duplicated: {sum(n for _, n, _ in L['unused_duplicated']):,} lines in "
                       f"{len(L['unused_duplicated'])} files, e.g. " +
                       "; ".join(f"{f} ({n:,}; added {i})" for f, n, i in L["unused_duplicated"][:3]))
        for g, n in L["generators_of_unused"]:
            out.append(f"  L* generator of unused code: {g} ({n} lines)")
        for g, n, i, v in L["generators"]:
            out.append(f"  L3 generator: {g} ({n} lines, {100 * v:.0f}% of its lines also in other "
                       f"versioned files; added {i})")
        if L["empty_tests"]:
            out.append(f"  L4 tests importing no application code: {len(L['empty_tests'])} files, "
                       f"{sum(n for _, n in L['empty_tests']):,} lines")
        if P["zero_seconds"]:
            out.append(f"  S2 :00 spec commits {len(P['zero_seconds'])}/{P['spec_commits']} "
                       f"(p = {P['zero_p']:.2g}): " + ", ".join(t for _, t in P["zero_seconds"][:5]))
        for p, a, b in P["date_mismatch"]:
            out.append(f"  S3 {p}: name {a}, commit {b}")
        if P["retroactive"]:
            out.append(f"  S4 {len(P['retroactive'])} specifications: " +
                       "; ".join(p for p, _ in P["retroactive"][:4]))
        if P["agent_commit_days_without_session"]:
            out.append(f"  R1 agent commits on days without a session: {P['agent_commit_days_without_session']}")
        G = r.get("github")
        if isinstance(G, dict):
            for e in G["events"]:
                if e["type"] == "force_push" or "main" not in e["ref"] or e["type"] == "branch_deletion":
                    if e["type"] == "branch_creation" and not e["ref"].endswith(tuple("0123456789")) \
                            and e["type"] != "force_push" and "backup" not in e["ref"]:
                        continue
                    h = e.get("replaced_history")
                    extra = ""
                    if isinstance(h, dict):
                        extra = f"; replaced history: {h['commits']} commits, {h['specs']} specs, " \
                                f"{h['agent_trailers']} Agent trailers, first {h['first']}"
                    out.append(f"  S1 {e['time']} {e['type']} {e['ref']} {e['before']}->{e['after']}"
                               f"{' (after collection)' if e['after_collection'] else ''}{extra}")
            out.append(f"  repository created {G['created']}")
        if out:
            print(f"\n{name}")
            print("\n".join(out))

    if confirmed:
        print("\nConfirmed by manual inspection (unused duplicated code + its generators):")
        tc = 0
        for name, r in results.items():
            c = r.get("confirmed")
            if c:
                tc += c["total"]
                print(f"  {name}: {c['code']:,} + {c['generators']:,} = {c['total']:,} lines "
                      f"({100 * c['share']:.1f}% of {r['lines']['sloc']:,}); without them {c['without']:,}")
        # Generator scripts are themselves counted; in a confirmed project, all of them are part of the
        # inflation (e.g., source embedded as string literals and also written to src/).
        tg = 0
        for name, r in results.items():
            c = r.get("confirmed")
            if c:
                gens = sum(n for _, n, _, _ in r["lines"]["generators"])
                tg += c["code"] + max(gens, c["generators"])
                if gens > c["generators"]:
                    print(f"  {name}: all {len(r['lines']['generators'])} generator scripts add {gens:,} lines")
        print(f"  with all generator scripts of these projects: {tg:,}; all projects without it {tot - tg:,}")
        print(f"  total {tc:,}; all projects without it {tot - tc:,}; reaching 100,000 without it: " +
              (", ".join(n for n, r in results.items()
                         if r["lines"]["sloc"] - r.get("confirmed", {}).get("total", 0) >= 100_000) or "none"))

    if args.api_cache:
        json.dump(API_CACHE, open(args.api_cache, "w", encoding="utf-8"))
    if args.json:
        json.dump(results, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    main()
