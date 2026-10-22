#!/usr/bin/env python3
"""Writes the anonymized survey responses (data/survey-anonymized.csv).

Usage:
  python3 -I src/anonymize_survey.py --responses RESPONSES.csv --identities IDENTITIES.json \
      --gender-codebook CODEBOOK.csv [--projects PROJECTS_DIR] --out data/survey-anonymized.csv

Takes the same private inputs as survey.py and keeps the columns of the
questionnaire, so that survey.py and likert_figure.py read the output as they
read the raw export. Each row:

  timestamp      blank
  GitHub user    random ID (R01, R02, ...), not derived from the user
  repository     name of the project in the paper (common.PROJECTS)
  age, gender    blank: with the project known, they would identify respondents
  open answers   "[omitted]" when answered, blank otherwise
  other answers  unchanged

and appends REPO_COLUMNS of survey.py, the variables mined from the
repositories for that respondent, so that the anonymized file needs neither the
clones nor the mapping between respondents and commit authors. Rows are sorted
by project, in a random order within each project.
"""
import argparse
import csv
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import PROJECTS  # noqa: E402
from survey import OPEN, REPO_COLUMNS, add_repository_variables, load  # noqa: E402

BLANK = [0, 3, 4]  # timestamp, age, gender


def cell(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    return repr(v) if isinstance(v, float) else str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--responses", default=os.environ.get("SURVEY_CSV"))
    ap.add_argument("--identities", default=os.environ.get("SURVEY_IDENTITIES"))
    ap.add_argument("--gender-codebook", default=os.environ.get("SURVEY_GENDER"))
    ap.add_argument("--projects", default=os.environ.get("PROJECTS_DIR"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if not (args.responses and args.identities and args.gender_codebook and args.projects):
        ap.error("--responses, --identities, --gender-codebook, and --projects are required")

    header, *rows = list(csv.reader(open(args.responses, encoding="utf-8")))
    data = load(args)
    add_repository_variables(data, args.projects)

    rng = random.SystemRandom()
    order = sorted(range(len(rows)), key=lambda k: (PROJECTS[data[k]["repo"]][0], rng.random()))
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(header + REPO_COLUMNS)
        for n, k in enumerate(order, 1):
            x, d = list(rows[k]), data[k]
            for i in BLANK:
                x[i] = ""
            x[1] = f"R{n:02d}"
            x[2] = PROJECTS[d["repo"]][1]
            for i in OPEN.values():
                x[i] = "[omitted]" if x[i].strip() else ""
            wr.writerow(x + [cell(d[c]) for c in REPO_COLUMNS])
    print(f"wrote {len(rows)} respondents to {args.out}")


if __name__ == "__main__":
    main()
