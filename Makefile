# Reproduces every number of Section II (Methodology) and of the results.
#
#   make all PROJECTS_DIR=... COMMITTERS_MAILMAP=... SURVEY_CSV=... SURVEY_IDENTITIES=... SURVEY_GENDER=... GITHUB_LIST=...
#
# Each target writes its report to $(OUT)/<target>.txt. See README.md.

PYTHON  ?= python3 -I
OUT     ?= out
CLOC    ?= $(CURDIR)/cloc-1.98.pl
UNTIL   ?= 2026-10-07
CONFIRMED ?= data/confirmed.txt
API_CACHE ?= $(OUT)/github-api-cache.json

export PROJECTS_DIR
export COMMITTERS_MAILMAP

.PHONY: all repos adherence specs table tests sessions gaming survey figures check-projects check-survey check-github clean help

help:
	@echo "make adherence  # Adherence, projects, RQ1         (needs PROJECTS_DIR)"
	@echo "make table      # Table of projects (RQ1 + RQ2)     (needs PROJECTS_DIR)"
	@echo "make specs      # Specifications, RQ2              (needs PROJECTS_DIR)"
	@echo "make tests      # Automated tests per project, RQ1  (needs PROJECTS_DIR)"
	@echo "make sessions   # Prompts in the sessions, RQ1/RQ2  (needs PROJECTS_DIR)"
	@echo "make gaming     # Gaming audit and table, RQ5        (needs PROJECTS_DIR, GITHUB_LIST)"
	@echo "make survey     # Participants, RQ3, RQ4, tables     (needs PROJECTS_DIR, SURVEY_*)"
	@echo "make figures    # Likert figure of the survey        (needs SURVEY_*)"
	@echo "make repos      # adherence + specs + gaming"
	@echo "make all        # everything"

all: repos survey figures

repos: adherence specs table tests sessions gaming

$(OUT):
	@mkdir -p $(OUT)

check-projects:
	@test -n "$(PROJECTS_DIR)" || { echo "error: set PROJECTS_DIR to the folder with the 18 clones"; exit 1; }
	@test -d "$(PROJECTS_DIR)" || { echo "error: $(PROJECTS_DIR) does not exist"; exit 1; }

check-survey:
	@test -n "$(SURVEY_CSV)" -a -n "$(SURVEY_IDENTITIES)" -a -n "$(SURVEY_GENDER)" || \
	  { echo "error: set SURVEY_CSV, SURVEY_IDENTITIES and SURVEY_GENDER"; exit 1; }

check-github:
	@test -n "$(GITHUB_LIST)" || { echo "error: set GITHUB_LIST (lines '<folder> <owner>/<repo>')"; exit 1; }

adherence: check-projects | $(OUT)
	$(PYTHON) adherence.py "$(PROJECTS_DIR)" --latex | tee $(OUT)/adherence.txt

specs: check-projects | $(OUT)
	$(PYTHON) spec_analysis.py "$(PROJECTS_DIR)" --latex --csv $(OUT)/specs.csv | tee $(OUT)/specs.txt

table: check-projects | $(OUT)
	$(PYTHON) project_table.py "$(PROJECTS_DIR)" | tee $(OUT)/table.txt

tests: check-projects | $(OUT)
	$(PYTHON) tests_analysis.py "$(PROJECTS_DIR)" | tee $(OUT)/tests.txt

sessions: check-projects | $(OUT)
	$(PYTHON) sessions.py "$(PROJECTS_DIR)" | tee $(OUT)/sessions.txt

gaming: check-projects check-github | $(OUT)
	$(PYTHON) gaming.py "$(PROJECTS_DIR)" --cloc "$(CLOC)" --github "$(GITHUB_LIST)" \
	  --until $(UNTIL) --confirmed $(CONFIRMED) --api-cache $(API_CACHE) \
	  --json $(OUT)/gaming.json | tee $(OUT)/gaming.txt

survey: check-projects check-survey | $(OUT)
	$(PYTHON) survey.py --responses "$(SURVEY_CSV)" --identities "$(SURVEY_IDENTITIES)" \
	  --gender-codebook "$(SURVEY_GENDER)" --projects "$(PROJECTS_DIR)" | tee $(OUT)/survey.txt

FIGURE ?= ../figures/survey-likert.pdf

figures: check-survey
	$(PYTHON) likert_figure.py --responses "$(SURVEY_CSV)" --identities "$(SURVEY_IDENTITIES)" \
	  --gender-codebook "$(SURVEY_GENDER)" --out "$(FIGURE)"

clean:
	rm -rf $(OUT) __pycache__
