# What each script computes


**`src/common.py`** — project list, git access, and the attribution of a commit to
an agent: an `Agent:` trailer naming a tool, a `Co-Authored-By:` trailer naming
an agent, or an agent as author; `Agent: none` marks handwritten commits.

**`src/adherence.py`** — for each project: production URL in the README, dated
specifications in `SPEC/`, specification first (share of specifications named
in `Spec:` trailers that had been added in an earlier commit), recorded
sessions in `prompts/sessoes/`, commits with both trailers, distinct human
committers (after merging the e-mails of the same student with the
mailmap), and lines of code with the command of the assignment and
`cloc` 1.98; totals and medians for the description of the projects and for RQ1. The *Agents* column of
the table of projects was read from each README and is kept in
`data/agents.csv`.

**`src/spec_analysis.py`** — for each specification in the last commit
(Markdown files under `SPEC/`, plus the OpenSpec files of the one team that
used it): authorship of the commit that added it; sections on what and why,
acceptance criteria, and out of scope, identified by heading; number of
acceptance criteria, including those in subsections; whether a commit points
to it through `Spec:` (by file name or, failing that, by the words of the
trailer matched against the specifications present at that commit); whether
it was added together with code (any non-Markdown file outside `SPEC/` and
`prompts/`); whether it was edited after its first implementing commit; and,
per project, the share of added lines traced to a specification.

**`src/tests_analysis.py`** — automated tests, which the assignment did not
require: test files (by folder and name), their lines of code, test cases
(`def test_`, `it(`, `test(`, `@Test`), test frameworks declared in the
manifests, and whether a GitHub Actions workflow runs them. Code confirmed as
gaming (`data/confirmed.txt`) is left out.

**`src/sessions.py`** — extracts the students' prompts from the session exports
in `prompts/sessoes/`, with one parser per tool (Claude Code and Codex
`.jsonl`, Antigravity, OpenCode, DeepSeek, and Copilot `.json`, and Markdown
transcripts); files without speaker marks are reported as unparsed. It counts
prompts and their length, the prompts that ask the agent to write a
specification, and the share of agent commits within two hours of a recorded
session. `--csv` writes the text of the prompts, which must not be
distributed.

**`src/gaming.py`** — an audit in which each check derives from a requirement of
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

**`src/survey.py`** — demographics and prior use of AI; distribution and median of
each Likert statement; Cronbach's alpha, mean, and standard deviation of each
construct; attribution of ideas and code, share of generated code read, and
hours; Wilcoxon test between ideas and code attributed to oneself; the
calibration between the self-attributed share of the code and the origin
declared in one's own commits; Spearman
correlations between ownership and the self-reported and mined variables (the
mined ones come from `common.py` and `spec_analysis.py`); and the comparison
within pairs between the member with more and the member with fewer commits.

**`src/anonymize_survey.py`** — writes `data/survey-anonymized.csv` from the
raw export, keeping the columns of the questionnaire so that `survey.py` and
`likert_figure.py` read it unchanged. The GitHub user becomes a random ID
(`R01`, ...), the repository becomes the project's name in the paper, and the
timestamp, age, and gender are left blank, since with the project known they
would identify respondents. Open answers are replaced by `[omitted]`, which
keeps the count of respondents who answered them. The variables mined from the
repositories (own commits, their declared origin, and the team measures) are
computed per respondent and appended as columns, so the anonymized file needs
neither the clones nor the mapping between respondents and commit authors. On
this file, `survey.py` reproduces every number of the paper except the age and
gender of the participants. `sessions.py --survey` still needs the raw data.

# Steps that are not automated

- The *Agents* column of the table of projects (`data/agents.csv`, read from
  the README of each project) and the stacks mentioned in the text.
- The manual inspection of gaming candidates (`data/confirmed.txt`) and the
  reading of commits and sessions quoted in RQ5.
- The quotes from the open answers of the survey, selected by reading them.
