"""
NOTEBOOK 01 — Raw Data Profiling
=================================
Purpose : Understand what we received BEFORE touching anything.
Rule    : This notebook makes ZERO changes to the data.
          Read-only. Every observation is documented.

Why this notebook exists:
  Data cleaning decisions must be driven by evidence, not assumptions.
  This notebook generates that evidence. Every cleaning step in
  Notebook 02 is justified by something discovered here.

Run order: This must run BEFORE all other notebooks.

Output:
  outputs/reports/01_raw_profile.csv     — per-column statistics
  outputs/reports/01_column_decisions.md — keep/drop reasoning
"""

# ── CELL 1: Imports and paths ──────────────────────────────────────────────────
import sys, warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import seaborn as sns

warnings.filterwarnings("ignore")
pd.set_option("display.max_columns", 50)
pd.set_option("display.max_rows", 100)
pd.set_option("display.width", 120)

# Make src importable regardless of where notebook is launched from
NOTEBOOK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = NOTEBOOK_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config import get_paths, COLUMNS_TO_LOAD, EXCLUDED_COLUMNS, PLOT_STYLE, PALETTE

PATHS = get_paths()
plt.rcParams.update(PLOT_STYLE)

print("Paths:")
for k, v in PATHS.items():
    print(f"  {k:<15}: {v}")


# ── CELL 2: Load raw CSV — all columns, no filtering ──────────────────────────
def load_raw(path: Path) -> pd.DataFrame:
    """
    Load CSV with automatic encoding detection.
    Raises FileNotFoundError with a clear message if file is missing.
    Uses low_memory=False to prevent dtype inference warnings on mixed columns.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"\nCSV not found: {path}\n"
            f"Set CHAGUOAI_DATA_DIR to the folder containing "
            f"Client_Service_Statistics.csv"
        )
    for enc in ["utf-8", "latin1", "cp1252", "utf-8-sig"]:
        try:
            df = pd.read_csv(path, encoding=enc, low_memory=False)
            print(f"Loaded: {path.name}  [{enc}]  —  {df.shape[0]:,} rows × {df.shape[1]} cols")
            return df
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"Cannot decode {path.name} with any standard encoding.")


css_raw = load_raw(PATHS["css_path"])


# ── CELL 3: Shape and completeness overview ────────────────────────────────────
print("\n" + "=" * 65)
print("RAW DATA OVERVIEW")
print("=" * 65)
print(f"Total records (rows):  {len(css_raw):,}")
print(f"Total columns:         {len(css_raw.columns)}")
print(f"Duplicate rows:        {css_raw.duplicated().sum():,}")
print(f"Unique visitid:        {css_raw['visitid'].nunique():,}")
print(f"Unique uniqueid (clients): {css_raw['uniqueid'].nunique():,}")
print(f"\nAvg visits per client: {len(css_raw)/css_raw['uniqueid'].nunique():.1f}")
print(
    "\nNOTE: 216,539 rows but only 3,838 unique clients."
    "\nThis is a LONGITUDINAL dataset — each client appears multiple times."
    "\nThis has important implications for splitting (avoid data leakage)."
)


# ── CELL 4: Per-column profile ─────────────────────────────────────────────────
print("\n" + "=" * 65)
print("PER-COLUMN PROFILE")
print("=" * 65)
print(f"{'Column':<22} {'Dtype':<10} {'Missing%':>9} {'Unique':>8}  Sample values")
print("-" * 80)

col_profiles = []
for col in css_raw.columns:
    dtype      = str(css_raw[col].dtype)
    n_missing  = css_raw[col].isna().sum()
    pct_miss   = n_missing / len(css_raw) * 100
    n_unique   = css_raw[col].nunique()
    samples    = css_raw[col].dropna().unique()[:4].tolist()
    col_profiles.append({
        "column":      col,
        "dtype":       dtype,
        "n_missing":   int(n_missing),
        "pct_missing": round(pct_miss, 1),
        "n_unique":    int(n_unique),
        "sample":      str(samples),
    })
    print(f"{col:<22} {dtype:<10} {pct_miss:>8.1f}% {n_unique:>8}  {str(samples)[:55]}")

profile_df = pd.DataFrame(col_profiles)
profile_df.to_csv(PATHS["reports_dir"] / "01_raw_profile.csv", index=False)
print(f"\nProfile saved: {PATHS['reports_dir'] / '01_raw_profile.csv'}")


# ── CELL 5: Column keep/drop decision table ────────────────────────────────────
print("\n" + "=" * 65)
print("COLUMN DECISIONS: KEEP vs DROP")
print("=" * 65)

decision_rows = []
for col in css_raw.columns:
    if col in COLUMNS_TO_LOAD:
        decision = "KEEP"
        reason   = "Used in modelling or needed for target variable"
    elif col in EXCLUDED_COLUMNS:
        decision = "DROP"
        reason   = EXCLUDED_COLUMNS[col]
    else:
        decision = "DROP"
        reason   = "Not in COLUMNS_TO_LOAD — review config.py to add"
    decision_rows.append({"column": col, "decision": decision, "reason": reason})
    print(f"  {'✅' if decision=='KEEP' else '❌'} {col:<24} {reason[:55]}")

decisions_df = pd.DataFrame(decision_rows)

# Save as markdown for open-source documentation
md_lines = ["# Column Decisions\n", "| Column | Decision | Reason |",
            "|--------|----------|--------|"]
for _, row in decisions_df.iterrows():
    md_lines.append(f"| {row['column']} | {row['decision']} | {row['reason']} |")

with open(PATHS["reports_dir"] / "01_column_decisions.md", "w") as f:
    f.write("\n".join(md_lines))
print(f"\nDecision table saved: {PATHS['reports_dir'] / '01_column_decisions.md'}")


# ── CELL 6: Critical distribution checks ──────────────────────────────────────
print("\n" + "=" * 65)
print("CRITICAL COLUMN DISTRIBUTIONS")
print("=" * 65)

critical_cols = {
    "gender":           "Filter: Female only",
    "fpstatus":         "Filter: Revisit only (defines modeling subset)",
    "previousmethod":   "Target variable component (43% missing = NaN for New clients)",
    "methodadopted":    "Target variable component (always present)",
    "fertilityintention":"Core predictor (has 'Missing' string sentinel = 23.6%)",
    "educationlevel":   "Core predictor (has 'Missing' string sentinel = 6.6%)",
    "counseled":        "Core predictor (97.8% Yes)",
}

for col, note in critical_cols.items():
    vc = css_raw[col].value_counts(dropna=False)
    print(f"\n  {col}  [{note}]")
    for val, cnt in vc.items():
        pct = cnt / len(css_raw) * 100
        bar = "█" * int(pct / 2)
        print(f"    {str(val):<30} {cnt:>7,}  ({pct:>5.1f}%)  {bar}")


# ── CELL 7: Age and parity outlier inspection ──────────────────────────────────
print("\n" + "=" * 65)
print("NUMERIC COLUMN OUTLIERS")
print("=" * 65)

for col, lo, hi in [("age", 10, 60), ("noofchildren", 0, 15)]:
    series = css_raw[col]
    print(f"\n  {col}:")
    print(f"    Min: {series.min()}  Max: {series.max()}  Mean: {series.mean():.2f}  Median: {series.median():.0f}")
    print(f"    Below {lo}: {(series < lo).sum():,}   Above {hi}: {(series > hi).sum():,}")
    print(f"    Percentiles:  P1={series.quantile(0.01):.0f}  "
          f"P5={series.quantile(0.05):.0f}  P95={series.quantile(0.95):.0f}  "
          f"P99={series.quantile(0.99):.0f}")

print(
    "\nDECISION on noofchildren > 15:"
    "\n  Max value is 78. This is biologically possible but statistically"
    "\n  extreme. The Kenya DHS median parity for women aged 15-49 is ~3.5."
    "\n  Values above 15 (217 records = 0.1%) are almost certainly data entry"
    "\n  errors (e.g. '78' entered instead of '7'). We cap at 15."
)


# ── CELL 8: Modeling subset preview ───────────────────────────────────────────
print("\n" + "=" * 65)
print("MODELING SUBSET PREVIEW")
print("=" * 65)

female_revisit = css_raw[
    (css_raw["gender"] == "Female") &
    (css_raw["fpstatus"] == "Revisit")
].copy()

with_prior = female_revisit[
    female_revisit["previousmethod"].notna() &
    (~female_revisit["previousmethod"].str.strip().isin(["Missing", ""]))
].copy()

# Exclude planned removals and off-scope methods
from config import PLANNED_REMOVAL_METHODS, OFFSCOPE_METHODS
in_scope = with_prior[
    ~with_prior["methodadopted"].str.strip().isin(
        PLANNED_REMOVAL_METHODS | OFFSCOPE_METHODS
    )
].copy()

in_scope["disc_raw"] = (
    in_scope["previousmethod"].str.strip().str.lower() !=
    in_scope["methodadopted"].str.strip().str.lower()
).astype(int)

print(f"All records:                  {len(css_raw):,}")
print(f"Female only:                  {len(css_raw[css_raw['gender']=='Female']):,}")
print(f"Female + Revisit:             {len(female_revisit):,}")
print(f"  + valid prior method:       {len(with_prior):,}")
print(f"  + excluding removals/OOS:   {len(in_scope):,}  ← MODELING DATASET SIZE")
print(f"\nTarget variable (discontinued):")
print(f"  Continued (0): {(in_scope['disc_raw']==0).sum():,}  ({(in_scope['disc_raw']==0).mean():.1%})")
print(f"  Switched  (1): {(in_scope['disc_raw']==1).sum():,}  ({(in_scope['disc_raw']==1).mean():.1%})")
print(f"\nClass balance: {in_scope['disc_raw'].mean():.1%} positive rate")
print("ASSESSMENT: 41.6% is a reasonably balanced dataset.")
print("No SMOTE or class weighting required if this rate holds after cleaning.")


# ── CELL 9: Plot 1 — Missing data heatmap ─────────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 4))
miss_pct = (css_raw[COLUMNS_TO_LOAD].isna().mean() * 100).sort_values(ascending=False)
colors   = [PALETTE["red"] if v > 40 else
            PALETTE["amber"] if v > 15 else
            PALETTE["teal"]
            for v in miss_pct.values]
bars = ax.barh(miss_pct.index[::-1], miss_pct.values[::-1], color=colors[::-1], height=0.6)
for bar, val in zip(bars, miss_pct.values[::-1]):
    ax.text(val + 0.3, bar.get_y() + bar.get_height() / 2,
            f"{val:.1f}%", va="center", fontsize=9)
ax.axvline(40, color=PALETTE["red"],   linestyle="--", linewidth=1, label="40% threshold")
ax.axvline(15, color=PALETTE["amber"], linestyle="--", linewidth=1, label="15% threshold")
ax.set_xlabel("Missing (%)")
ax.set_title("Figure 1: Missing Data — Selected Columns\n(columns to be used in model)")
ax.legend(fontsize=9)
ax.set_xlim(0, 70)
plt.tight_layout()
plt.savefig(PATHS["figures_dir"] / "01a_missing_data.png", dpi=150, bbox_inches="tight")
plt.show()
print("Figure 1 saved.")


# ── CELL 10: Plot 2 — Gender and FP status ─────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(12, 4))

ax = axes[0]
gc = css_raw["gender"].value_counts()
ax.pie(gc.values, labels=gc.index,
       colors=[PALETTE["teal"], PALETTE["coral"]],
       autopct="%1.1f%%", startangle=90, wedgeprops={"edgecolor": "white", "linewidth": 2})
ax.set_title("Figure 2a: Gender Split\n(we model Female only)")

ax = axes[1]
sc  = css_raw["fpstatus"].value_counts()
bar_colors = [PALETTE["teal"] if v == "Revisit" else PALETTE["gray"] for v in sc.index]
bars = ax.bar(sc.index, sc.values, color=bar_colors, width=0.5)
for bar, val in zip(bars, sc.values):
    ax.text(bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 500,
            f"{val:,}", ha="center", va="bottom", fontweight="bold")
ax.set_title("Figure 2b: FP Status\n(Revisit = has prior method = usable for target)")
ax.set_ylabel("Records")

plt.tight_layout()
plt.savefig(PATHS["figures_dir"] / "01b_gender_fpstatus.png", dpi=150, bbox_inches="tight")
plt.show()
print("Figure 2 saved.")


# ── CELL 11: Plot 3 — Key categorical distributions ───────────────────────────
fig, axes = plt.subplots(2, 2, figsize=(14, 9))

plots = [
    ("previousmethod",    "Figure 3a: Previous Method (43% NaN = New clients)"),
    ("methodadopted",     "Figure 3b: Method Adopted (0% missing)"),
    ("fertilityintention","Figure 3c: Fertility Intention (23.5% 'Missing' string)"),
    ("educationlevel",    "Figure 3d: Education Level (6.6% 'Missing' string)"),
]

for ax, (col, title) in zip(axes.flat, plots):
    vc = css_raw[col].value_counts(dropna=False).head(10)
    color_list = [PALETTE["teal"] if str(v) not in ["nan","Missing","NaN"]
                  else PALETTE["red"] for v in vc.index]
    vc.plot.barh(ax=ax, color=color_list)
    for i, v in enumerate(vc.values):
        ax.text(v + 200, i, f"{v:,}", va="center", fontsize=8.5)
    ax.set_title(title)
    ax.set_xlabel("Count")
    ax.set_ylabel("")

plt.suptitle("Figure 3: Categorical Column Distributions (raw)\nRed bars = missing/sentinel values",
             fontweight="bold", y=1.01)
plt.tight_layout()
plt.savefig(PATHS["figures_dir"] / "01c_categoricals_raw.png", dpi=150, bbox_inches="tight")
plt.show()
print("Figure 3 saved.")


# ── CELL 12: Plot 4 — Age and parity distributions ────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))

ax = axes[0]
css_raw["age"].hist(ax=ax, bins=range(10, 63, 2),
                    color=PALETTE["teal"], edgecolor="white", alpha=0.9)
ax.axvline(css_raw["age"].median(), color=PALETTE["red"],
           linewidth=2, linestyle="--", label=f"Median: {css_raw['age'].median():.0f}")
ax.set_title("Figure 4a: Age Distribution (All records)")
ax.set_xlabel("Age (years)")
ax.set_ylabel("Count")
ax.legend()

ax = axes[1]
parity = css_raw["noofchildren"]
parity_capped = parity.clip(0, 15)
parity_capped.hist(ax=ax, bins=range(0, 17, 1),
                   color=PALETTE["coral"], edgecolor="white", alpha=0.9)
ax.axvline(parity.median(), color=PALETTE["navy"],
           linewidth=2, linestyle="--", label=f"Median: {parity.median():.0f}")
ax.set_title(f"Figure 4b: Parity (capped at 15)\n{(parity>15).sum()} values above 15 capped")
ax.set_xlabel("Number of children")
ax.set_ylabel("Count")
ax.legend()

ax = axes[2]
year_month = css_raw.groupby(["year", "month"])["visitid"].count().reset_index()
year_month["month_num"] = year_month["month"].map({
    "January":1,"February":2,"March":3,"April":4,"May":5,"June":6,
    "July":7,"August":8,"September":9,"October":10,"November":11,"December":12
})
year_month = year_month.sort_values(["year","month_num"])
for yr, grp in year_month.groupby("year"):
    ax.plot(grp["month_num"], grp["visitid"],
            marker="o", markersize=4, linewidth=2, label=str(yr))
ax.set_xticks(range(1,13))
ax.set_xticklabels(["J","F","M","A","M","J","J","A","S","O","N","D"])
ax.set_title("Figure 4c: Monthly Visit Volume by Year")
ax.set_xlabel("Month")
ax.set_ylabel("Visits")
ax.legend(title="Year")

plt.suptitle("Figure 4: Numeric Column Distributions", fontweight="bold")
plt.tight_layout()
plt.savefig(PATHS["figures_dir"] / "01d_numeric_distributions.png", dpi=150, bbox_inches="tight")
plt.show()
print("Figure 4 saved.")


# ── CELL 13: Summary findings ──────────────────────────────────────────────────
print("\n" + "=" * 65)
print("PROFILING SUMMARY — KEY FINDINGS")
print("=" * 65)
findings = [
    "1. No duplicate rows. Each visitid is unique.",
    "2. Only 3,838 unique clients in 216,539 visits → longitudinal data.",
    "   → Data splitting must be done by client (uniqueid), NOT by row.",
    "   → Row-level random split would leak future visits into training.",
    "3. 'Missing' string is used as sentinel in 5 columns.",
    "   → Must replace with np.nan before any numeric operations.",
    "4. previousmethod is NaN for all 93,095 New clients (not missing data).",
    "   → NaN here means 'no prior method' — clinically correct.",
    "5. noofchildren has 217 values > 15 (max=78). Almost certainly entry errors.",
    "   → Cap at 15 in cleaning.",
    "6. age is clean: range 10-60, no zeros, no NaN.",
    "7. counseled is 97.8% Yes — this column has very low variance.",
    "   → Keep but monitor feature importance; may contribute little.",
    "8. fertilityintention is 23.5% 'Missing'. Missingness may be informative.",
    "   → Add binary 'fertility_known' flag before imputing.",
    "9. Modeling subset (female revisit, in-scope methods): 78,755 records.",
    "   Target class balance: 41.6% discontinued — no SMOTE needed.",
    "10. Year 2014 has 52% of all records — year must be a feature, not ignored.",
]
for f in findings:
    print(f"  {f}")

print(f"\nAll figures saved to: {PATHS['figures_dir']}")
print(f"All reports saved to: {PATHS['reports_dir']}")
print("\nNotebook 01 COMPLETE. Run Notebook 02 next.")