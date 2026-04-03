<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/ghostrepo-dark-text.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/ghostrepo-light-text.svg">
  <img alt="CodeWeaver logo" src="docs/assets/ghost-repo-dark-text.svg" height="210px" width="400px">
</picture>

</div>

#### Some open source projects have years of steady work behind them. Hundreds, even thousands, of commits. Real features. Shipped code. 

**But no one knows they exist** outside a small circle of dedicated maintainers (often only one person).

**I call them ghost repos.**

This repo, `ghost-repos`, is the companion to the blog post [**Ghost Repos: The Most Dedicated Projects Nobody's Ever Heard Of**](https://blog.knitli.com/ghost-repos-the-most-dedicated-projects-nobodys-ever-heard-of). It contains the data, the scoring pipeline, and a browser-based explorer.

**[Explore the data →](https://bashandbone.github.io/ghost-repos/)**

---

## What is a ghost repo?

**A ghost repo is** a GitHub repository **where someone (or a very small team) has put in *serious*, *sustained* effort over a *long time* — but the project has almost no stars, forks, or public recognition.**

These aren't abandoned side projects. The repos identified by `ghost-repos` have *at least*:

- **8+ months of consistent and active development** (many are years long, some more than a decade)
- **Recent or ongoing activity**
- **Hundreds or thousands of commits**
- **Real code quality signals** — tests, CI/CD pipelines, proper READMEs, releases
- **Fewer than 50 stars**

### The question behind this project: *what would you find if you sorted GitHub by effort instead of popularity?* [^1]

[^1]: More precisely: *what are the highest effort, least recognized, projects on GitHub?*

---

## Key numbers

| Stat | Value |
|------|-------|
| Ghost repos found | 401 |
| Combined commits | 578,822 |
| Combined stars (all 401 repos) | 5,001 |
| **Commits per star** | **116** |
| Average repo age | 3.7 *years* |
| Repos with 0 stars | 52 (12%) |
| Repos with ≤ 5 stars | 182 (45%) |
| Repos with tests | 178 (44%) |
| Repos with CI/CD | 385 (96%) |
| Repos with releases | 235 (58%) |

You read that right: 401 repos, over half a million commits, 5,000 stars.

---

## How I found them

I queried the [GitHub Archive](https://www.gharchive.org/) using Google Cloud BigQuery ([repo](https://github.com/igrigorik/gharchive.org). The GitHub Archive provides a public dataset of all GitHub events since February 2011, available on BigQuery or as raw json from gharchive.org. 

#### The query went through **six iterations** (v1–v5, then v6.1) to filter out noise and surface genuinely high-effort projects. 

v6.1 is the final version — it extended the date range to cover 2025 and early 2026, raised the activity threshold to 8+ active months, and added more noise filter patterns, focusing on repo quality signals like pull requests.

See [`queries/README.md`](queries/README.md) for a full description of each iteration and what I learned.

---

## What's in this repo

```
ghost-repos/
├── data/
│   ├── raw/          # Raw BigQuery export CSVs (different query runs)
│   └── processed/    # Scored and filtered results
│       └── ghost_repos_v5_final.csv   ← main dataset (401 repos, 33 columns)
├── docs/
│   └── index.html    # Browser-based data explorer (served via GitHub Pages)
├── queries/
│   └── README.md     # Six SQL iterations with descriptions (v6.1 is final)
├── scripts/
│   ├── main.py       # v5 scoring pipeline (two-stage GitHub API verification)
│   └── githubtest.py # v2 scoring pipeline (earlier, simpler version)
└── README.md
```

### The main dataset

`data/processed/ghost_repos_v5_final.csv` has 401 repos and 33 columns, including:

- **Effort signals**: push events, total commits, active months, active weeks
- **Team size**: human pusher count (1 = solo dev)
- **Quality signals**: has tests, has CI, README present, readme length, commit message diversity, release count
- **Scores**:
  - `ghost_score` = effort ÷ visibility (push events / log₁₀(stars + 2))
  - `quality_score` = 0–10 composite of quality signals
  - `combined_score` = quality × invisibility × 100
- **Metadata**: language, license, description, creation date, topics

---

## How to re-run the pipeline

If you want to update the dataset, you can run the BigQuery query yourself.

### 1. Clone the Repo

```bash

git clone https://github.com/bashandbone/ghost-repos.git && cd ghost-repos

```

### 2. Get fresh BigQuery data

>[!WARNING]
> **Running the query costs about 25 USD**. I used Google Cloud's new customer credit ($300 for 15 days) to run the queries for free -- I couldn't have afforded it otherwise. Total cost for my iterations was ~100 USD (in credits). It's reasonable for scraping and processing 5TB of data, if you can afford it.

The latest query will always be symlinked to `queries/latest.sql`

Run the v6 query (see [`queries/README.md`](queries/README.md)) against the `githubarchive` public dataset in BigQuery. you don't need to do anything other than copy and paste the query and click `run`, but you can save yourself 10 seconds by copy/pasting this into bash/zsh to get the query at the top of your clipboard:

```bash
# I alias bat as cat which corrupts things with ansi escapes, so we use command here
# this assumes you have clipcopy or xclip installed
# if not, on ubuntu install with: apt update && sudo apt install -y xclip
# or clipcopy (cross platform): npm i -g clipcopy

if command -v xclip >&2; then
  xclip ./queries/latest.sql
elif command -v clipcopy >&2; then
  command cat ./queries/latest.sql | clipcopy
else
  echo 'please install xclip or clipcopy'
fi
```

#### Export the results as a CSV into `data/raw/`.

I plan to further optimize the query based on [lessons](https://github.com/bashandbone/ghost-repos/tree/main/queries#what-didnt-make-it-lessons-on-noise-filtering) from the 'final' query, v6.1. Especially today -- modern AI assisted workflows generate issues and PRs even if a single contributor mostly commits directly to `main`. 

### 3. Set up the environment

**Recommended**: using `uv` ([install uv](https://github.com/astral-sh/uv#installation))

```bash
# Uses uv
# optionally create an environment:
uv venv .venv && source .venv/bin/activate

# sync dependencies:
uv sync
```

Or with pip:
```bash
pip install httpx rich
```

### 4. Run the scoring pipeline

```bash
python scripts/main.py
```

The script reads from `data/raw/`, hits the GitHub API to verify each repo, filters out noise (bots, mirrors, archived repos, etc.), and writes a new scored CSV to `data/processed/`.

You'll need a GitHub personal access token for API rate limits, which you will hit very quickly:

```bash
export GITHUB_TOKEN=your_token_here
```

### 5. Regenerate the site data

After running the pipeline, regenerate the JSON used by the data explorer:

```bash
python -c "
import csv, json
rows = []
with open('data/processed/ghost_repos_v5_final.csv') as f:
    for row in csv.DictReader(f):
        rows.append({k: v for k, v in row.items()})
rows.sort(key=lambda r: float(r.get('combined_score') or 0), reverse=True)
json.dump(rows, open('docs/data/ghost_repos.json', 'w'), separators=(',', ':'))
print(f'Done: {len(rows)} repos')
"
```

(and submit a PR -- I would love to get fresh data :smile:)

---

## The scripts

| Script | What it does |
|--------|-------------|
| `scripts/githubtest.py` | v2 pipeline — single-stage GitHub API verification. Simpler, stricter star filter (max 15). |
| `scripts/main.py` | v5 pipeline — two-stage verification with richer quality signals (README length, tests, CI, releases, commit message diversity). |

Both scripts take a CSV of BigQuery results, call the GitHub API for each repo, filter out noise, and write a scored CSV.

> [!NOTE]
> I included the v2 pipeline script for people who are curious about the difficulty of filtering GitHub data for actual repos that produce actual code.  **I don't recommend it for anyone looking to get meaningful results -- use `main.py` for that.**
---

## License

Data and code in this repository are released under the [MIT License](LICENSE).

GitHub Archive data is subject to its own terms (code under MIT license, website CC-by-4.0). Repository metadata from the GitHub API belongs to the respective repository owners.

---

Built by [bashandbone](https://github.com/bashandbone) with help from Claude. Why? I wondered how many projects like [CodeWeaver](https://github.com/knitli/codeweaver) were out there and how much more extreme they might be. Results exceeded expectations.
