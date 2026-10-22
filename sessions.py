#!/usr/bin/env python3
"""Prompts recorded in prompts/sessoes/: volume, origin of specifications,
coverage of agent commits, and prompting by student.

Usage:
  python3 -I sessions.py PROJECTS_DIR [--survey] [--csv prompts.csv]

PROJECTS_DIR (or $PROJECTS_DIR) holds one git clone per team. With --survey,
the per-student measures are correlated with ownership; it needs the inputs of
survey.py (SURVEY_CSV, SURVEY_IDENTITIES, SURVEY_GENDER) and numpy/scipy.

Parsers (one per export format; a file no parser recognizes is "unparsed"):
  claude      Claude Code .jsonl: messages of type "user" with text content,
              without tool results, slash commands, meta messages, or sidechains
  codex       Codex .jsonl / .jsonl.gz: event_msg/user_message, without injected
              instructions and environment context
  antigravity Antigravity .jsonl: USER_INPUT steps (text in <USER_REQUEST>)
  opencode    OpenCode/DeepSeek .json: messages of type "user"
  copilot     GitHub Copilot .json: requests[].message.text
  markdown    transcripts: turns marked by "❯", "Usuário:", "### Usuário",
              "## User", "## Prompt", "## Prompt recebido", "Prompt do Usuário",
              or ">" blocks; summaries ("**Solicitação:**") are marked as such
Files whose name says they come from a subagent, metadata files, build logs, and
manifests are not sessions. A Markdown file that renders a .jsonl of the same
session (same name) is skipped to avoid double counting.
"""
import argparse
import csv
import datetime as dt
import gzip
import json
import os
import re
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import authorship, git, load_commits, repos  # noqa: E402

TOLERANCE = dt.timedelta(hours=2)   # coverage: commit within a session window +- tolerance;
                                    # files without timestamps cover the day in their name
SHORT = 3                           # a prompt of at most SHORT words is "short"
# A prompt that asks the agent to write a specification: a request verb followed,
# within five words, by "spec"/"especificação", and not about committing or implementing one.
SPEC_REQUEST = re.compile(r"\b(cri[ae]r?|fa[cç]a|fazer|escrev[ae]r?|gerar?|gere|redija|elabore|monte|write|create|draft)"
                          r"\s+(\S+\s+){0,4}?(spec|specs|especifica[çc][ãa]o|especifica[çc][õo]es)\b", re.I)
NOT_REQUEST = re.compile(r"commit|implement", re.I)
SPEC_WORDS = re.compile(r"\bspec\b|\bspecs\b|especifica|SPEC/", re.I)
INJECTED = re.compile(r"^\s*(<environment_context>|<user_instructions>|# AGENTS\.md|<permissions|"
                      r"The following is the Codex agent history|<turn_aborted>|<subagent)", re.I)
CLAUDE_SKIP = re.compile(r"^\s*(<command-|<local-command|Caveat:|<system-reminder>|\[Request interrupted)")


def words(text):
    return len(text.split())


def ts(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value / 1000 if value > 1e11 else value, dt.timezone.utc)
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def name_time(path):
    """Date and time in the file name (YYYY-MM-DD[-HHMM]), taken as local time (UTC-3)."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:-(\d{2})(\d{2}))?", os.path.basename(path))
    if not m:
        return None
    y, mo, d, h, mi = m.groups()
    return dt.datetime(int(y), int(mo), int(d), int(h or 12), int(mi or 0),
                       tzinfo=dt.timezone(dt.timedelta(hours=-3)))


# ---------------------------------------------------------------- parsers

def read_lines(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def parse_jsonl(path):
    prompts, times, kind, fallback = [], [], None, []
    for d in read_lines(path):
        if not isinstance(d, dict):
            continue
        t = ts(d.get("timestamp") or d.get("created_at"))
        if t:
            times.append(t)
        if d.get("type") == "user" and isinstance(d.get("message"), dict):
            kind = "claude"
            if d.get("isMeta") or d.get("isSidechain"):
                continue
            c = d["message"].get("content")
            if isinstance(c, list):
                if any(x.get("type") == "tool_result" for x in c if isinstance(x, dict)):
                    continue
                c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
            if isinstance(c, str):
                c = re.sub(r"<(system-reminder|ide_[a-z_]+)>.*?</\1>", "", c, flags=re.S)
                c = re.sub(r"</?pasted_content[^>]*>", "", c).strip()
            if isinstance(c, str) and c and not CLAUDE_SKIP.match(c):
                prompts.append((t, c))
        elif d.get("type") == "event_msg" and isinstance(d.get("payload"), dict):
            kind = kind or "codex"
            p = d["payload"]
            if p.get("type") == "user_message" and p.get("message", "").strip() \
                    and not INJECTED.match(p["message"]):
                prompts.append((t, p["message"].strip()))
        elif d.get("type") == "response_item" and isinstance(d.get("payload"), dict):
            kind = kind or "codex"
            p = d["payload"]
            if p.get("type") == "message" and p.get("role") == "user":
                text = "\n".join(x.get("text", "") for x in p.get("content") or [] if isinstance(x, dict))
                if text.strip() and not text.lstrip().startswith("<") and not INJECTED.match(text):
                    fallback.append((t, text.strip()))
        elif d.get("type") in ("session_meta", "turn_context"):
            kind = kind or "codex"
        elif d.get("type") == "USER_INPUT":
            kind = "antigravity"
            c = str(d.get("content", ""))
            m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", c, re.S)
            text = (m.group(1) if m else c).strip()
            if text:
                prompts.append((t, text))
        elif "step_index" in d:
            kind = "antigravity"
    if kind == "codex" and not prompts:  # sessions without user_message events
        prompts = fallback
    return kind, prompts, times


def parse_json(path):
    try:
        d = json.load(open(path, encoding="utf-8", errors="ignore"))
    except ValueError:
        return None, [], []
    prompts, times = [], []
    if isinstance(d, dict) and isinstance(d.get("messages"), list):
        for m in d["messages"]:
            t = ts((m.get("time") or {}).get("created"))
            if t:
                times.append(t)
            if m.get("type") == "user" and str(m.get("text", "")).strip():
                prompts.append((t, m["text"].strip()))
        return "opencode", prompts, times
    if isinstance(d, dict) and isinstance(d.get("requests"), list):
        for r in d["requests"]:
            t = ts(r.get("timestamp"))
            if t:
                times.append(t)
            text = (r.get("message") or {}).get("text", "")
            if text.strip():
                prompts.append((t, text.strip()))
        return "copilot", prompts, times
    return None, [], []


MD_TURN = re.compile(r"^(❯ |Usuário: |#{2,3} (Usuário|User|Prompt( recebido)?)\b|## \d+\. Prompt do Usuário|> )",
                     re.M)


def parse_markdown(path):
    text = open(path, encoding="utf-8", errors="ignore").read()
    lines = text.splitlines()
    prompts, cur, mode = [], [], None
    # ">" blocks are turns only in transcripts without headings; elsewhere they quote output
    quotes_are_turns = not re.search(r"^#{1,3} ", text, re.M)

    def flush():
        if cur and " ".join(cur).strip() and not re.fullmatch(r"\s*<[^>]*>\s*", " ".join(cur)):
            prompts.append((None, "\n".join(cur).strip()))
        cur.clear()

    if "**Solicitação:**" in text:
        for l in lines:
            if l.startswith("**Solicitação:**"):
                prompts.append((None, l.split("**Solicitação:**", 1)[1].strip()))
        return "summary", prompts, []
    for l in lines:
        s = l.rstrip()
        if s.startswith("❯ ") or s.startswith("Usuário: "):
            flush()
            cur.append(s.split(" ", 1)[1])
            mode = "inline"
        elif re.match(r"#{2,3} (Usuário|User|Prompt( recebido)?)\b|## \d+\. Prompt do Usuário", s):
            flush()
            mode = "section"
        elif s.startswith("#"):
            flush()
            mode = None
        elif s.startswith("> ") and mode != "section" and quotes_are_turns:
            if mode != "quote":
                flush()
            cur.append(s[2:])
            mode = "quote"
        elif mode == "section":
            cur.append(s[2:] if s.startswith("> ") else s)
        elif mode == "inline" and s.startswith("  ") and s.strip():
            cur.append(s.strip())
        elif mode in ("inline", "quote") and not s.strip():
            flush()
            mode = None
    flush()
    return ("markdown" if prompts else None), prompts, []


def parse_text(path):
    """A .txt holding a single prompt (e.g., kept by hand)."""
    text = open(path, encoding="utf-8", errors="ignore").read().strip()
    if text and len(text.splitlines()) < 60 and "Trabalhou por" not in text:
        return "text", [(None, text)], []
    return None, [], []


NOT_SESSION = re.compile(r"(subagente|subagent|\.meta\.json$|\.log$|MANIFESTO|README|\.gitkeep$)", re.I)


def parse(path):
    if path.endswith((".jsonl", ".jsonl.gz", ".gz")):
        return parse_jsonl(path)
    if path.endswith(".json"):
        return parse_json(path)
    if path.endswith(".md"):
        return parse_markdown(path)
    if path.endswith(".txt"):
        return parse_text(path)
    return None, [], []


# ---------------------------------------------------------------- analysis

def project_sessions(path):
    files = [f for f in git(path, "ls-files", "prompts/sessoes").splitlines()]
    stems = {re.sub(r"\.jsonl(\.gz)?$", "", f) for f in files if ".jsonl" in f}
    out = []
    for f in files:
        if NOT_SESSION.search(os.path.basename(f)):
            continue
        if f.endswith(".md") and f[:-3] in stems:
            continue
        kind, prompts, times = parse(os.path.join(path, f))
        log = git(path, "log", "--diff-filter=A", "--format=%an|%ae", "--", f).splitlines()
        author = log[-1].lower() if log else ""
        day_only = False
        if not times:
            t = name_time(f)
            if t:  # no timestamps in the file: the whole day of the file name is the window
                day = t.replace(hour=0, minute=0)
                times, day_only = [day, day + dt.timedelta(hours=24) - TOLERANCE * 2], True
        out.append(dict(file=f, kind=kind, prompts=prompts, times=times, author=author, day_only=day_only))
    return out


def spec_origin(path, commits, sessions_, spec_rows):
    """For each spec added by an agent, the closest earlier prompt on the same day
    that mentions specifications or words of the spec name."""
    added = {}
    for c in commits:
        for st, p in c["files"]:
            if st == "A" and p not in added:
                added[p] = c
    timed = [(t, txt) for s in sessions_ for t, txt in s["prompts"] if t]
    found = []
    for r in spec_rows:
        if r["author"] != "agent" or r["spec"] not in added:
            continue
        ct = ts(added[r["spec"]]["date"])
        part = [w for w in re.split(r"[^a-z0-9]+", os.path.basename(r["spec"]).lower()[11:-3]) if len(w) > 3]
        best = None
        for t, txt in timed:
            if t <= ct and t.date() == ct.astimezone(t.tzinfo).date() and \
                    (SPEC_WORDS.search(txt) or any(w in txt.lower() for w in part)):
                if best is None or t > best[0]:
                    best = (t, txt)
        if best and ct - best[0] <= TOLERANCE:
            found.append(dict(spec=r["spec"], prompt_words=words(best[1]), spec_words=r["words"]))
    return found


def coverage(commits, sessions_, timestamped_only=False):
    windows = [(min(s["times"]) - TOLERANCE, max(s["times"]) + TOLERANCE)
               for s in sessions_ if s["times"] and s["kind"] and not (timestamped_only and s["day_only"])]
    agent = [ts(c["date"]) for c in commits if authorship(c) == "agent"]
    covered = sum(1 for t in agent if any(a <= t <= b for a, b in windows))
    return covered, len(agent)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("projects", nargs="?", default=os.environ.get("PROJECTS_DIR"))
    ap.add_argument("--survey", action="store_true", help="correlate per-student measures with ownership")
    ap.add_argument("--csv", help="write one row per prompt (contains prompt text; keep private)")
    args = ap.parse_args()
    if not args.projects:
        ap.error("pass PROJECTS_DIR as an argument or environment variable")
    import spec_analysis

    print(f"{'ID':>2} {'Project':14} {'files':>5} {'parsed':>6} {'unparsed':>8} {'prompts':>7} "
          f"{'med.words':>9} {'short':>6} {'covered':>9}")
    allp, origins, by_author, cov, requests = [], [], defaultdict(list), [0, 0], {}
    rows_csv = []
    for pid, name, folder, path in repos(args.projects):
        ss = project_sessions(path)
        parsed = [s for s in ss if s["kind"]]
        prompts = [txt for s in parsed for _, txt in s["prompts"]]
        allp += prompts
        for p in prompts:
            if SPEC_REQUEST.search(p) and not NOT_REQUEST.search(p[:200]):
                requests[(name, p)] = words(p)
        for s in parsed:
            by_author[(folder, s["author"])] += [txt for _, txt in s["prompts"]]
            for t, txt in s["prompts"]:
                rows_csv.append(dict(project=name, file=s["file"], kind=s["kind"],
                                     time=t.isoformat() if t else "", words=words(txt), text=txt))
        commits = load_commits(path)
        spec_rows, _ = spec_analysis.analyze(path)
        origins += [dict(o, project=name) for o in spec_origin(path, commits, parsed, spec_rows)]
        c, n = coverage(commits, parsed)
        cov[0] += c
        cov[1] += n
        cov.append(coverage(commits, parsed, timestamped_only=True)[0])
        w = [words(p) for p in prompts]
        print(f"{pid:>2} {name:14} {len(ss):>5} {len(parsed):>6} {len(ss) - len(parsed):>8} {len(prompts):>7} "
              f"{statistics.median(w) if w else 0:>9.0f} "
              f"{100 * sum(x <= SHORT for x in w) / len(w) if w else 0:>5.0f}% "
              f"{(f'{100 * c / n:.0f}%' if n else '--'):>9}")
    w = [words(p) for p in allp]
    print(f"\nprompts {len(allp)}; median words {statistics.median(w):.0f}; "
          f"short (<= {SHORT} words) {100 * sum(x <= SHORT for x in w) / len(w):.0f}%")
    print(f"agent commits inside a recorded session window (+-{TOLERANCE}): {cov[0]} of {cov[1]} "
          f"({100 * cov[0] / cov[1]:.0f}%); with timestamped sessions only: {sum(cov[2:])} "
          f"({100 * sum(cov[2:]) / cov[1]:.0f}%)")
    n_agent = sum(1 for _, folder, _, path in [(0, f, 0, p) for _, _, f, p in repos(args.projects)]
                  for r in spec_analysis.analyze(path)[0] if r["author"] == "agent")
    if requests:
        rw = sorted(requests.values())
        q = statistics.quantiles(rw, n=4)
        print(f"prompts asking the agent to write a specification (distinct): {len(rw)} in "
              f"{len({k[0] for k in requests})} projects; median {statistics.median(rw):.0f} words "
              f"(Q1 {q[0]:.0f}, Q3 {q[2]:.0f}; min {rw[0]}, max {rw[-1]}); at most 20 words: "
              f"{sum(x <= 20 for x in rw)}")
    if origins:
        print(f"agent-written specs with a spec-related prompt in the {TOLERANCE} before their commit: {len(origins)} of {n_agent} "
              f"({100 * len(origins) / n_agent:.0f}%) in {len({o['project'] for o in origins})} projects; "
              f"median prompt {statistics.median(o['prompt_words'] for o in origins):.0f} words, "
              f"median spec {statistics.median(o['spec_words'] for o in origins):.0f} words, "
              f"median ratio {statistics.median(o['spec_words'] / max(o['prompt_words'], 1) for o in origins):.1f}x")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows_csv[0]))
            wr.writeheader()
            wr.writerows(rows_csv)

    if args.survey:
        import numpy as np
        from scipy import stats
        import survey
        ns = argparse.Namespace(responses=os.environ.get("SURVEY_CSV"),
                                identities=os.environ.get("SURVEY_IDENTITIES"),
                                gender_codebook=os.environ.get("SURVEY_GENDER"))
        data = survey.load(ns)
        pairs = []
        for d in data:
            ps = [p for (folder, author), plist in by_author.items()
                  if folder == d["repo"] and author and re.search(d["author_pattern"], author) for p in plist]
            if ps:
                pairs.append((d, len(ps), float(np.median([words(p) for p in ps]))))
        print(f"\nstudents with attributable sessions: {len(pairs)} of {len(data)}")
        for c in survey.TARGETS:
            for label, k in (("prompts", 1), ("median words", 2)):
                x = [(p[k], p[0][c]) for p in pairs if p[0][c] is not None]
                rho, pv = stats.spearmanr(*zip(*x))
                print(f"  {c} ~ {label}: rho = {rho:+.2f}, p = {pv:.2f}, n = {len(x)}")


if __name__ == "__main__":
    main()
