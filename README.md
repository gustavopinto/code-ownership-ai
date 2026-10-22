# Replication scripts

These scripts reproduce every number reported in Section II (Methodology) and
in the results of the paper: the table of projects, the tables of gaming and correlations, the figure of the Likert statements, and the numbers quoted in the
text. Each script prints the values in the form used in the paper, including
the LaTeX rows of the tables.

## Layout

```
scripts/
├── Makefile          entry point: one target per part of the paper
├── requirements.txt
├── src/              analysis scripts (common.py holds shared helpers)
├── data/             manual inputs: agents.csv, confirmed.txt
├── vendor/           cloc 1.98, pinned for reproducible line counts
├── docs/scripts.md   what each script computes and the manual steps
└── out/              reports written by make (created on demand)
```

## Requirements

- Python 3.8 or later, `git`, and `perl` (for `cloc`)
- `numpy` and `scipy` for the survey, and `pandas`, `matplotlib`, and `plot_likert` for its figure: `pip install -r requirements.txt`
- Network access, only for the GitHub activity check of the gaming audit

`vendor/cloc-1.98.pl` is included, since line counts depend on the version of `cloc`.

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
| `make adherence` | `src/adherence.py` | Data Collection and Analysis; Participants and Projects; RQ1 |
| `make specs` | `src/spec_analysis.py` | Specification Analysis; RQ2 |
| `make table` | `src/project_table.py` | Table of projects (process and specification measures per project) |
| `make tests` | `src/tests_analysis.py` | Automated tests per project (RQ1; Tests column of the table of projects) |
| `make sessions` | `src/sessions.py` | Prompts extracted from the recorded sessions (RQ1, RQ2) |
| `make gaming` | `src/gaming.py` | Requirement Gaming Analysis; Tables of gaming and of the audit; RQ5 |
| `make survey` | `src/survey.py` | Ownership Survey; Participants; Table of correlations; RQ3; RQ4 |
| `make figures` | `src/likert_figure.py` | Figure of the Likert statements (written to `../figures/survey-likert.pdf`) |

Reports are written to `out/<target>.txt` (`OUT=...` changes the folder).
`make specs` also writes one row per specification to `out/specs.csv`, and
`make gaming` writes every candidate to `out/gaming.json`. A full run takes
about one minute, plus the GitHub queries.

See [`docs/scripts.md`](docs/scripts.md) for what each script computes and
for the steps that are not automated.
