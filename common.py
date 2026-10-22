"""Shared helpers: project list, git access, and attribution of commits to agents."""
import os
import re
import subprocess

# Folder name -> (ID, name used in the paper)
PROJECTS = {
    "dsai-ap1-reservei": (1, "BookIt"),
    "dsai-ap1-eduquest": (2, "EduQuest"),
    "dsai-ap1-trim": (3, "Trim"),
    "dsai-ap1-kapitrace": (4, "KapiTrace"),
    "dsai-ap1-GameLog": (5, "GameLog"),
    "dsai-ap1-EstiloMarcado": (6, "SalonBook"),
    "dsai-ap1-serviceflow": (7, "ServiceFlow"),
    "dsai_ap1-Reprodutor-Media-Play": (8, "MediaPlay"),
    "dsai-ap1-financas": (9, "Finances"),
    "dsai-ap1--HealthOS-": (10, "HealthOS"),
    "dsai-ap1-delivery": (11, "DeliveryFast"),
    "dsai-ap1-sigrestaurant": (12, "ClearTable"),
    "dsai-ap1-proj-leiloes-judiciais": (13, "CourtAuctions"),
    "dasi-ap1-election-ops-plataform": (14, "ElectionOps"),
    "dsai-ap1-circuitcrash": (15, "CircuitCrash"),
    "dsai-ap1--FilmeCerto-": (16, "RightMovie"),
    "dsai-ap1-2Drogue": (17, "UmbraTrail"),
    "dsai-ap1-consultas": (18, "ClinicBooking"),
}

# ---------------------------------------------------------------- discovery

OPENSPEC = re.compile(r"^openspec/changes/[^/]+/specs/[^/]+/spec\.md$")


def is_spec(path):
    return (path.startswith("SPEC/") and path.endswith(".md")) or bool(OPENSPEC.match(path))


def is_openspec(path):
    return bool(OPENSPEC.match(path))


def excluded_from_lines(path):
    """Paths outside the code count of traced lines."""
    return path.startswith("SPEC/") or path.startswith("prompts/") or is_openspec(path)


def is_code(path):
    """A file that counts as code when deciding if a spec came with code."""
    return not excluded_from_lines(path) and not path.lower().endswith(".md")


# ---------------------------------------------------------------- git

SEP_C, SEP_F = "\x1e", "\x1f"


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def load_commits(repo):
    """Commits oldest first, with author, message, changed files and added lines."""
    fmt = SEP_C + SEP_F.join(["%H", "%an", "%ae", "%aI", "%B"]) + SEP_F
    commits = {}
    order = []
    for block in git(repo, "log", "--reverse", "--no-renames", "--name-status",
                     "--format=" + fmt).split(SEP_C)[1:]:
        h, an, ae, date, body, rest = block.split(SEP_F, 5)
        files = []
        for line in rest.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                files.append((parts[0][0], parts[-1]))
        commits[h] = dict(hash=h, author=an, email=ae, date=date, body=body,
                          files=files, added={})
        order.append(h)
    for block in git(repo, "log", "--no-renames", "--numstat",
                     "--format=" + SEP_C + "%H").split(SEP_C)[1:]:
        lines = block.strip().splitlines()
        if not lines:
            continue
        h = lines[0].strip()
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) == 3 and parts[0].isdigit():
                commits[h]["added"][parts[2]] = int(parts[0])
    return [commits[h] for h in order]


# ---------------------------------------------------------------- authorship

AGENTS = re.compile(r"claude|anthropic|codex|openai|chatgpt|gpt|copilot|gemini|antigravity|"
                    r"cursor|opencode|deepseek|devin|aider|windsurf|kiro|jules|cline|qwen|"
                    r"mimo|\[bot\]", re.I)
NONE_VALUES = re.compile(r"^(none|nenhum|nenhuma|n/?a|-+)$", re.I)


def trailer_values(body, key):
    return [m.group(1).strip() for m in
            re.finditer(r"^\s*" + key + r"\s*:\s*(.+?)\s*$", body, re.I | re.M)]


def authorship(commit):
    agent_values = trailer_values(commit["body"], "Agent")
    if any(not NONE_VALUES.match(re.split(r"[\s.,;:]+", v)[0]) for v in agent_values if v):
        return "agent"
    if any(AGENTS.search(v) for v in trailer_values(commit["body"], "Co-Authored-By")):
        return "agent"
    if AGENTS.search(commit["author"]) or AGENTS.search(commit["email"]):
        return "agent"
    if agent_values:
        return "human"
    return "undeclared"



def trailer_value_list(body, key):
    return trailer_values(body, key)


def sessions(repo):
    """Files under prompts/sessoes/ in the last commit."""
    return [p for p in git(repo, "ls-files", "prompts/sessoes").splitlines()
            if os.path.basename(p) not in (".gitkeep", "README.md")]


def default_projects_dir():
    """Directory with one git clone per team, from the environment variable PROJECTS_DIR."""
    path = os.environ.get("PROJECTS_DIR")
    if not path:
        raise SystemExit("set PROJECTS_DIR (or pass the directory as an argument)")
    return path


def repos(projects_dir):
    """(id, name, folder, path) for the 18 projects, in the order of the paper."""
    for folder, (pid, name) in sorted(PROJECTS.items(), key=lambda kv: kv[1][0]):
        yield pid, name, folder, os.path.join(projects_dir, folder)
