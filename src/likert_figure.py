#!/usr/bin/env python3
"""Figure with the answers to the Likert statements of the ownership survey.

Usage:
  python3 -I src/likert_figure.py --responses RESPONSES.csv --identities IDENTITIES.json \
      --gender-codebook CODEBOOK.csv --out FIGURE.pdf

Inputs are the same as survey.py (or SURVEY_CSV, SURVEY_IDENTITIES, SURVEY_GENDER).
One panel per construct, one diverging bar per statement, with the share of
respondents at each point of the scale. Requires pandas, matplotlib, and
plot_likert.
"""
import argparse
import os
import sys
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plot_likert  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from survey import CONSTRUCTS, REVERSE, STATEMENTS, alpha, load  # noqa: E402

SCALE = ["Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree"]
COLORS = plot_likert.colors.likert5
LABEL_MIN = 8  # label segments of at least this percentage


def plain(text):
    return text.replace("\\texttt{", "").replace("}", "")


def percentages(data):
    """One row per statement, preceded by an empty row that names the construct."""
    rows, headers = [], []
    for construct, items in CONSTRUCTS.items():
        mean = np.mean([d[construct] for d in data if d[construct] is not None])
        rows.append((f"{construct} ($\\alpha$ = {alpha(data, items):.2f}; mean = {mean:.2f})",
                     {k: 0.0 for k in SCALE}))
        headers.append(len(rows) - 1)
        for i in items:
            x = [d["L"][i] for d in data if d["L"][i] is not None]
            label = textwrap.fill(plain(STATEMENTS[i]) + (" (R)" if i in REVERSE else ""), 120)
            rows.append((label, {SCALE[k - 1]: 100 * sum(a == k for a in x) / len(x) for k in range(1, 6)}))
    df = pd.DataFrame([r for _, r in rows], index=[l for l, _ in rows])[SCALE]
    return df, headers


def thin_labels(ax):
    """Keeps only the labels of segments wide enough to hold them."""
    for t in list(ax.texts):
        try:
            value = float(t.get_text().rstrip("%"))
        except ValueError:
            continue
        if value < LABEL_MIN:
            t.remove()
        else:
            t.set_text(f"{value:.0f}")
            t.set_fontsize(6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--responses", default=os.environ.get("SURVEY_CSV"))
    ap.add_argument("--identities", default=os.environ.get("SURVEY_IDENTITIES"))
    ap.add_argument("--gender-codebook", default=os.environ.get("SURVEY_GENDER"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if not (args.responses and args.identities and args.gender_codebook):
        ap.error("--responses, --identities, and --gender-codebook are required")
    data = load(args)

    plt.rcParams.update({"font.size": 7, "font.family": "serif"})
    df, headers = percentages(data)
    ax = plot_likert.plot_counts(df, SCALE, plot_percentage=True, colors=COLORS, bar_labels=True,
                                 bar_labels_color="black",
                                 figsize=(7.16, 0.155 * len(df) + 0.5), width=0.7, legend=False, xtick_interval=20)
    thin_labels(ax)
    fig = ax.get_figure()
    labels = ax.get_yticklabels()
    n = len(df)
    for k, t in enumerate(labels):  # plot_likert draws the first row at the top
        if (n - 1 - k) in headers or t.get_text() in [df.index[h] for h in headers]:
            t.set_fontstyle("italic")
            t.set_fontweight("bold")
    ax.set_xlabel("Share of respondents (%)")
    ax.tick_params(axis="y", length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    handles, names = ax.get_legend_handles_labels()
    keep = [(h, l) for h, l in zip(handles, names) if l in SCALE]
    fig.legend(*zip(*keep), loc="upper center", ncol=5, frameon=False, bbox_to_anchor=(0.6, 1.0))
    fig.tight_layout(rect=(0, 0, 1, 0.985))
    fig.savefig(args.out, bbox_inches="tight")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
