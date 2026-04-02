# Ghost Repos

Some open source projects have years of steady work behind them — hundreds or thousands of commits, real features, shipped code. But almost nobody knows they exist.

We call them ghost repos.

This repo is the companion to the blog post [**Ghost Repos: The Most Dedicated Projects Nobody's Ever Heard Of**](https://blog.knitli.com/ghost-repos-the-most-dedicated-projects-nobodys-ever-heard-of). It contains the data, the scoring pipeline, and a browser-based explorer.

**[Explore the data →](https://bashandbone.github.io/ghost-repos/)**

---

## What is a ghost repo?

A ghost repo is a GitHub repository where someone (or a very small team) has put in serious, sustained effort over a long time — but the project has almost no stars, forks, or public recognition.

These aren't abandoned side projects. They're repos with:

- **8+ months of active development** (many are years long, some more than a decade)
- **Hundreds or thousands of commits**
- **Real code quality signals** — tests, CI/CD pipelines, proper READMEs, releases
- **Fewer than 50 stars**

The question behind this project: *what would you find if you sorted GitHub by effort instead of popularity?*

---

## Key numbers

| Stat | Value |
|------|-------|
| Ghost repos found | 401 |
| Combined commits | 578,822 |
| Combined stars (all 401 repos) | 5,001 |
| **Commits per star** | **116** |
| Average repo age | 3.7 years |
| Repos with 0 stars | 52 (12%) |
| Repos with ≤ 5 stars | 182 (45%) |
| Repos with tests | 178 (44%) |
| Repos with CI/CD | 385 (96%) |
| Repos with releases | 235 (58%) |

---

## How we found them

We queried the [GitHub Archive](https://www.gharchive.org/) — a public record of all GitHub events — using BigQuery. The query went through **six iterations** (v1–v5, then v6.1) to filter out noise and surface genuinely high-effort projects. v6.1 is the final version — it extended the date range to cover 2025 and early 2026, raised the activity threshold to 8+ active months, and added more noise filter patterns.

See [`queries/README.md`](queries/README.md) for a full description of each iteration and what we learned.

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

If you want to update the dataset (the pipeline is designed to be re-run monthly):

### 1. Get fresh BigQuery data

Run the v6 query (see [`queries/README.md`](queries/README.md)) against the `githubarchive` public dataset in BigQuery. Export the results as a CSV into `data/raw/`.

### 2. Set up the environment

```bash
# Uses uv (fast Python package manager)
uv sync
```

Or with pip:
```bash
pip install httpx rich
```

### 3. Run the scoring pipeline

```bash
python scripts/main.py
```

The script reads from `data/raw/`, hits the GitHub API to verify each repo, filters out noise (bots, mirrors, archived repos, etc.), and writes a new scored CSV to `data/processed/`.

You'll need a GitHub personal access token for API rate limits:
```bash
export GITHUB_TOKEN=your_token_here
```

### 4. Regenerate the site data

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

---

## The scripts

| Script | What it does |
|--------|-------------|
| `scripts/githubtest.py` | v2 pipeline — single-stage GitHub API verification. Simpler, stricter star filter (max 15). |
| `scripts/main.py` | v5 pipeline — two-stage verification with richer quality signals (README length, tests, CI, releases, commit message diversity). |

Both scripts take a CSV of BigQuery results, call the GitHub API for each repo, filter out noise, and write a scored CSV.

---

## License

Data and code in this repository are released under the [MIT License](LICENSE).

GitHub Archive data is subject to its own terms. Repository metadata from the GitHub API belongs to the respective repository owners.

---

Built by [bashandbone](https://github.com/bashandbone) with help from Claude.
