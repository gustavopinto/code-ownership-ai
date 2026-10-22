# Replication scripts

These scripts reproduce every number reported in Section II (Methodology) and
in the results of the paper: the table of projects, the tables of gaming and correlations, the figure of the Likert statements, and the numbers quoted in the
text. Each script prints the values in the form used in the paper, including
the LaTeX rows of the tables.

## Requirements

- Python 3.8 or later, `git`, and `perl` (for `cloc`)
- `numpy` and `scipy` for the survey, and `pandas`, `matplotlib`, and `plot_likert` for its figure: `pip install -r requirements.txt`
- Network access, only for the GitHub activity check of the gaming audit

`cloc-1.98.pl` is included, since line counts depend on the version of `cloc`.

## Inputs

None of the inputs is part of this folder. Paths are passed through
environment variables (or `make` variables).

| Variable | Content |
|---|---|
| `PROJECTS_DIR` | One full `git clone` per team, named after the repository (the folder names listed in `common.py`), at the state collected for the paper. |
| `COMMITTERS_MAILMAP` | git mailmap (`<canonical e-mail> <alias e-mail>` per line) that merges the e-mails of students who committed with more than one address, such as a personal one and GitHub's no-reply one. Without it, authors are counted by e-mail. |
| `GITHUB_LIST` | Text file with one line per project: `<folder> <owner>/<repo>`. Used only to query GitHub's activity API. |
| `SURVEY_CSV` | Export of the questionnaire: one row per respondent, columns in the order of the questionnaire. |
| `SURVEY_IDENTITIES` | JSON file `{"fix_repo": {user: repo}, "author_patterns": {user: regex}}` with repository corrections and the patterns that match a respondent to their commit author when the name differs from the username. |
| `SURVEY_GENDER` | CSV with columns `resposta_original,codigo,n`: coding of the open gender question. |

The mailmap and the survey inputs contain personal data and are not distributed; the scripts
print aggregates only.

## Running

```
make all  PROJECTS_DIR=... COMMITTERS_MAILMAP=... GITHUB_LIST=... \
          SURVEY_CSV=... SURVEY_IDENTITIES=... SURVEY_GENDER=...
```

or one target at a time:

| Target | Script | Paper |
|---|---|---|
| `make adherence` | `adherence.py` | Data Collection and Analysis; Participants and Projects; RQ1 |
| `make specs` | `spec_analysis.py` | Specification Analysis; RQ2 |
| `make table` | `project_table.py` | Table of projects (process and specification measures per project) |
| `make tests` | `tests_analysis.py` | Automated tests per project (RQ1; Tests column of the table of projects) |
| `make sessions` | `sessions.py` | Prompts extracted from the recorded sessions (RQ1, RQ2) |
| `make gaming` | `gaming.py` | Requirement Gaming Analysis; Tables of gaming and of the audit; RQ5 |
| `make survey` | `survey.py` | Ownership Survey; Participants; Table of correlations; RQ3; RQ4 |
| `make figures` | `likert_figure.py` | Figure of the Likert statements (written to `../figures/survey-likert.pdf`) |

Reports are written to `out/<target>.txt` (`OUT=...` changes the folder).
`make specs` also writes one row per specification to `out/specs.csv`, and
`make gaming` writes every candidate to `out/gaming.json`. A full run takes
about one minute, plus the GitHub queries.

## What each script computes

**`common.py`** — project list, git access, and the attribution of a commit to
an agent: an `Agent:` trailer naming a tool, a `Co-Authored-By:` trailer naming
an agent, or an agent as author; `Agent: none` marks handwritten commits.

**`adherence.py`** — for each project: production URL in the README, dated
specifications in `SPEC/`, specification first (share of specifications named
in `Spec:` trailers that had been added in an earlier commit), recorded
sessions in `prompts/sessoes/`, commits with both trailers, distinct human
committers (after merging the e-mails of the same student with the
mailmap), and lines of code with the command of the assignment and
`cloc` 1.98; totals and medians for the description of the projects and for RQ1. The *Agents* column of
the table of projects was read from each README and is kept in
`data/agents.csv`.

**`spec_analysis.py`** — for each specification in the last commit
(Markdown files under `SPEC/`, plus the OpenSpec files of the one team that
used it): authorship of the commit that added it; sections on what and why,
acceptance criteria, and out of scope, identified by heading; number of
acceptance criteria, including those in subsections; whether a commit points
to it through `Spec:` (by file name or, failing that, by the words of the
trailer matched against the specifications present at that commit); whether
it was added together with code (any non-Markdown file outside `SPEC/` and
`prompts/`); whether it was edited after its first implementing commit; and,
per project, the share of added lines traced to a specification.

**`tests_analysis.py`** — automated tests, which the assignment did not
require: test files (by folder and name), their lines of code, test cases
(`def test_`, `it(`, `test(`, `@Test`), test frameworks declared in the
manifests, and whether a GitHub Actions workflow runs them. Code confirmed as
gaming (`data/confirmed.txt`) is left out.

**`sessions.py`** — extracts the students' prompts from the session exports
in `prompts/sessoes/`, with one parser per tool (Claude Code and Codex
`.jsonl`, Antigravity, OpenCode, DeepSeek, and Copilot `.json`, and Markdown
transcripts); files without speaker marks are reported as unparsed. It counts
prompts and their length, the prompts that ask the agent to write a
specification, and the share of agent commits within two hours of a recorded
session. `--csv` writes the text of the prompts, which must not be
distributed.

**`gaming.py`** — an audit in which each check derives from a requirement of
the assignment and runs on every project:

| Requirement | Checks |
|---|---|
| 100,000 lines | unreachable code files; duplicated code (windows of 100 normalized tokens); generator scripts; tests that import no application code; duplicated code that the application never uses |
| Specification first | force pushes and branch events (GitHub activity API); specification commits with seconds equal to zero (binomial test, rate 1/60); file-name date different from commit date; specifications declared retroactive |
| Complete record | commits declaring an agent on days without a recorded session; sessions mentioning the size target |

Checks produce candidates, which we inspected manually. `data/confirmed.txt`
lists the candidates confirmed by that inspection; the script uses it only to
sum the inflated lines of the confirmed cases. The unauthenticated GitHub API
allows 60 requests per hour and one run uses about 40: set `GITHUB_TOKEN` or
keep the cache (`out/github-api-cache.json`) between runs. If the API is not
reachable, the script says so and the force-push check is left empty.

**`survey.py`** — demographics and prior use of AI; distribution and median of
each Likert statement; Cronbach's alpha, mean, and standard deviation of each
construct; attribution of ideas and code, share of generated code read, and
hours; Wilcoxon test between ideas and code attributed to oneself; the
calibration between the self-attributed share of the code and the origin
declared in one's own commits; Spearman
correlations between ownership and the self-reported and mined variables (the
mined ones come from `common.py` and `spec_analysis.py`); and the comparison
within pairs between the member with more and the member with fewer commits.

## Steps that are not automated

- The *Agents* column of the table of projects (`data/agents.csv`, read from
  the README of each project) and the stacks mentioned in the text.
- The manual inspection of gaming candidates (`data/confirmed.txt`) and the
  reading of commits and sessions quoted in RQ5.
- The quotes from the open answers of the survey, selected by reading them.
