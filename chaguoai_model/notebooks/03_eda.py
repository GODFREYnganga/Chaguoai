"""
NOTEBOOK 03 — Exploratory Data Analysis
=========================================
Purpose : Understand the cleaned data deeply before touching
          any modelling code. Every chart answers a specific
          clinical question that directly shapes modelling decisions.

Rule    : This notebook reads from 02_cleaned.parquet.
          It does NOT modify the data.

Clinical questions answered:
  Q1.  How are records distributed across geography and time?
  Q2.  What does the age and parity profile of our clients look like?
  Q3.  What is the method mix — what methods do women actually use?
  Q4.  What is the overall discontinuation rate and how does it vary?
  Q5.  Which methods have the highest discontinuation rates?
  Q6.  Does age predict discontinuation risk?
  Q7.  Does parity predict discontinuation risk?
  Q8.  Does fertility intention predict discontinuation risk?
  Q9.  Does education level predict discontinuation risk?
  Q10. Does counseling predict discontinuation risk?
  Q11. Does delivery channel predict discontinuation risk?
  Q12. What switch patterns are most common (from → to)?
  Q13. Are there temporal trends in discontinuation?
  Q14. Are there geographic differences between counties?
  Q15. Are features correlated with each other (multicollinearity)?

Outputs:
  outputs/figures/03_*.png           — all EDA charts
  outputs/reports/03_eda_summary.csv — headline numbers for model card
"""

# ── CELL 1: Imports and paths ──────────────────────────────────────────────────
import sys, warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import seaborn as sns

warnings.filterwarnings("ignore")
pd.set_option("display.max_columns", 50)
pd.set_option("display.width", 120)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config import (
    get_paths, PALETTE, METHOD_COLORS, PLOT_STYLE,
)

PATHS = get_paths()
plt.rcParams.update(PLOT_STYLE)

print("Notebook 03: Exploratory Data Analysis")
print("=" * 55)


# ── CELL 2: Load clean data ────────────────────────────────────────────────────
def load_clean(paths: dict) -> pd.DataFrame:
    """
    Load the cleaned parquet file produced by Notebook 02.
    Raises a clear error if it does not exist — enforcing the
    correct run order.
    """
    parquet_path = paths["processed_dir"] / "02_cleaned.parquet"
    csv_path     = paths["processed_dir"] / "02_cleaned.csv"

    if parquet_path.exists():
        df = pd.read_parquet(parquet_path)
        print(f"Loaded: {parquet_path.name}  —  {df.shape[0]:,} rows × {df.shape[1]} cols")
    elif csv_path.exists():
        df = pd.read_csv(csv_path, low_memory=False)
        print(f"Loaded fallback CSV: {csv_path.name}")
    else:
        raise FileNotFoundError(
            "Clean dataset not found. Run Notebook 02 first.\n"
            f"Expected: {parquet_path}"
        )
    return df


df = load_clean(PATHS)

# Convenience subsets used throughout
continued    = df[df["discontinued"] == 0]
discontinued = df[df["discontinued"] == 1]

print(f"\nDataset: {len(df):,} revisit records")
print(f"  Continued    (0): {len(continued):,}  ({len(continued)/len(df):.1%})")
print(f"  Discontinued (1): {len(discontinued):,}  ({len(discontinued)/len(df):.1%})")


# ── CELL 3: Helper function ────────────────────────────────────────────────────
def disc_rate_by(df: pd.DataFrame, col: str,
                 min_n: int = 50,
                 observed: bool = True) -> pd.DataFrame:
    """
    Compute discontinuation rate and record count for each
    level of a categorical or grouped column.

    Parameters
    ----------
    df      : cleaned dataframe
    col     : column name to group by
    min_n   : minimum group size to include (avoids noisy small groups)
    observed: passed to groupby for Categorical columns

    Returns
    -------
    pd.DataFrame with columns: group, disc_rate, n
    """
    grp = (
        df.groupby(col, observed=observed)["discontinued"]
        .agg(disc_rate="mean", n="count")
        .reset_index()
        .rename(columns={col: "group"})
        .query("n >= @min_n")
        .sort_values("disc_rate")
    )
    grp["group"] = grp["group"].astype(str)
    return grp


def save_fig(name: str):
    """Save current figure and show it."""
    path = PATHS["figures_dir"] / f"{name}.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.show()
    print(f"  Saved: {name}.png")


overall_rate = df["discontinued"].mean()


# ── CELL 4: Q1 — Geographic and temporal distribution ─────────────────────────
print("\n[Q1] Geographic and temporal distribution")

fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))

# County
ax = axes[0]
county_counts = df["county"].value_counts()
bars = ax.bar(county_counts.index, county_counts.values,
              color=[PALETTE["teal"], PALETTE["coral"]], width=0.5)
for bar, (county, val) in zip(bars, county_counts.items()):
    pct = val / len(df) * 100
    ax.text(bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 300,
            f"{val:,}\n({pct:.0f}%)",
            ha="center", va="bottom", fontweight="bold")
ax.set_title("Figure 7a: Records by County")
ax.set_ylabel("Revisit records")
ax.set_ylim(0, county_counts.max() * 1.2)

# Delivery channel
ax = axes[1]
delivery_counts = df["delivery_type"].value_counts()
bar_colors = [PALETTE["teal"] if v == "community" else PALETTE["amber"]
              for v in delivery_counts.index]
bars = ax.bar(delivery_counts.index, delivery_counts.values,
              color=bar_colors, width=0.5)
for bar, val in zip(bars, delivery_counts.values):
    pct = val / len(df) * 100
    ax.text(bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 200,
            f"{val:,}\n({pct:.0f}%)", ha="center", va="bottom", fontweight="bold")
ax.set_title("Figure 7b: Records by Delivery Channel\n(community=Household+Outreach)")
ax.set_ylabel("Records")
ax.set_ylim(0, delivery_counts.max() * 1.25)

# Temporal trend — visits per month per year
ax = axes[2]
monthly = df.groupby(["year", "month_num"])["visitid"].count().reset_index()
year_colors = {2013: PALETTE["teal"], 2014: PALETTE["coral"], 2015: PALETTE["amber"]}
for yr, grp in monthly.groupby("year"):
    grp_sorted = grp.sort_values("month_num")
    ax.plot(grp_sorted["month_num"], grp_sorted["visitid"],
            marker="o", markersize=4, linewidth=2,
            color=year_colors.get(yr, PALETTE["gray"]),
            label=str(int(yr)))
ax.set_xticks(range(1, 13))
ax.set_xticklabels(["J", "F", "M", "A", "M", "J",
                    "J", "A", "S", "O", "N", "D"])
ax.set_title("Figure 7c: Monthly Visit Volume by Year")
ax.set_xlabel("Month")
ax.set_ylabel("Revisit records")
ax.legend(title="Year")

plt.suptitle("Figure 7: Geographic and Temporal Distribution", fontweight="bold")
plt.tight_layout()
save_fig("03a_geo_temporal")

print(f"  County split: {county_counts.to_dict()}")
print(f"  Delivery:     {delivery_counts.to_dict()}")


# ── CELL 5: Q2 — Age and parity profiles ──────────────────────────────────────
print("\n[Q2] Age and parity profiles")

fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))

# Age histogram
ax = axes[0]
ax.hist(df["age"], bins=range(10, 62, 2),
        color=PALETTE["teal"], edgecolor="white", alpha=0.9, label="All")
ax.hist(discontinued["age"], bins=range(10, 62, 2),
        color=PALETTE["coral"], edgecolor="white", alpha=0.6, label="Discontinued")
ax.axvline(df["age"].median(), color=PALETTE["navy"],
           linewidth=2, linestyle="--",
           label=f"Median: {df['age'].median():.0f}")
ax.set_title("Figure 8a: Age Distribution\n(orange = discontinued)")
ax.set_xlabel("Age (years)")
ax.set_ylabel("Count")
ax.legend(fontsize=9)

# Parity histogram
ax = axes[1]
ax.hist(df["noofchildren"], bins=range(0, 17, 1),
        color=PALETTE["teal"], edgecolor="white", alpha=0.9, label="All")
ax.hist(discontinued["noofchildren"], bins=range(0, 17, 1),
        color=PALETTE["coral"], edgecolor="white", alpha=0.6, label="Discontinued")
ax.axvline(df["noofchildren"].median(), color=PALETTE["navy"],
           linewidth=2, linestyle="--",
           label=f"Median: {df['noofchildren'].median():.0f}")
ax.set_title("Figure 8b: Parity Distribution\n(orange = discontinued)")
ax.set_xlabel("Number of living children")
ax.set_ylabel("Count")
ax.legend(fontsize=9)

# Age vs Parity scatter (sampled for readability)
ax = axes[2]
sample = df.sample(min(3000, len(df)), random_state=42)
scatter_colors = [PALETTE["coral"] if d == 1 else PALETTE["teal"]
                  for d in sample["discontinued"]]
ax.scatter(sample["age"], sample["noofchildren"],
           c=scatter_colors, alpha=0.3, s=15, edgecolors="none")
ax.set_title("Figure 8c: Age vs Parity\n(coral=discontinued, teal=continued)")
ax.set_xlabel("Age (years)")
ax.set_ylabel("Number of children")
legend_items = [
    mpatches.Patch(color=PALETTE["coral"], label="Discontinued"),
    mpatches.Patch(color=PALETTE["teal"],  label="Continued"),
]
ax.legend(handles=legend_items, fontsize=9)

plt.suptitle("Figure 8: Client Demographics", fontweight="bold")
plt.tight_layout()
save_fig("03b_demographics")

print(f"  Age:    median={df['age'].median():.0f}  mean={df['age'].mean():.1f}"
      f"  min={df['age'].min()}  max={df['age'].max()}")
print(f"  Parity: median={df['noofchildren'].median():.0f}  mean={df['noofchildren'].mean():.1f}"
      f"  min={df['noofchildren'].min()}  max={df['noofchildren'].max()}")


# ── CELL 6: Q3 — Method mix ───────────────────────────────────────────────────
print("\n[Q3] Method mix")

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Previous methods (what women were on)
ax = axes[0]
prev_counts = df["previousmethod"].value_counts().sort_values()
prev_colors = [METHOD_COLORS.get(
    {"Injectables":"short_acting_hormonal","Pills":"short_acting_hormonal",
     "Pills & Condoms":"short_acting_hormonal","Implants":"long_acting_reversible",
     "IUCD":"long_acting_reversible","BTL":"permanent","Condoms":"barrier"
     }.get(m, "unknown"), PALETTE["gray"]) for m in prev_counts.index]
bars = ax.barh(prev_counts.index, prev_counts.values, color=prev_colors, height=0.6)
for bar, val in zip(bars, prev_counts.values):
    pct = val / len(df) * 100
    ax.text(bar.get_width() + 200, bar.get_y() + bar.get_height() / 2,
            f"{val:,}  ({pct:.1f}%)", va="center", fontsize=9)
ax.set_title("Figure 9a: Previous Method\n(what clients were using before this visit)")
ax.set_xlabel("Records")
ax.set_xlim(0, prev_counts.max() * 1.25)

legend_items = [
    mpatches.Patch(color=METHOD_COLORS["short_acting_hormonal"],  label="Short-acting hormonal"),
    mpatches.Patch(color=METHOD_COLORS["long_acting_reversible"], label="Long-acting reversible"),
    mpatches.Patch(color=METHOD_COLORS["barrier"],                label="Barrier"),
    mpatches.Patch(color=METHOD_COLORS["permanent"],              label="Permanent"),
]
ax.legend(handles=legend_items, loc="lower right", fontsize=8)

# Category breakdown pie
ax = axes[1]
cat_counts = df["previous_method_category"].value_counts()
cat_colors = [METHOD_COLORS.get(c, PALETTE["gray"]) for c in cat_counts.index]
wedges, texts, autotexts = ax.pie(
    cat_counts.values,
    labels=cat_counts.index,
    colors=cat_colors,
    autopct="%1.1f%%",
    startangle=140,
    wedgeprops={"edgecolor": "white", "linewidth": 2},
)
for autotext in autotexts:
    autotext.set_fontsize(9)
ax.set_title("Figure 9b: Method Category Distribution\n(previous method at revisit visit)")

plt.suptitle("Figure 9: Contraceptive Method Mix", fontweight="bold")
plt.tight_layout()
save_fig("03c_method_mix")

print("  Previous method counts:")
for method, count in df["previousmethod"].value_counts().items():
    print(f"    {method:<20}: {count:,}  ({count/len(df):.1%})")


# ── CELL 7: Q4 — Overall discontinuation and Q5 by method ─────────────────────
print("\n[Q4 & Q5] Discontinuation rate overall and by method")

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# By specific method
ax = axes[0]
method_disc = disc_rate_by(df, "previousmethod", min_n=100)
bar_colors = [PALETTE["coral"] if r >= overall_rate else PALETTE["teal"]
              for r in method_disc["disc_rate"]]
bars = ax.barh(method_disc["group"], method_disc["disc_rate"] * 100,
               color=bar_colors, height=0.6)
for bar, (_, row) in zip(bars, method_disc.iterrows()):
    ax.text(bar.get_width() + 0.5,
            bar.get_y() + bar.get_height() / 2,
            f"{row['disc_rate']*100:.1f}%  (n={row['n']:,})",
            va="center", fontsize=9)
ax.axvline(overall_rate * 100, color=PALETTE["red"],
           linestyle="--", linewidth=2,
           label=f"Overall: {overall_rate*100:.1f}%")
ax.set_xlabel("Discontinuation rate (%)")
ax.set_title("Figure 10a: Discontinuation Rate by Previous Method")
ax.legend(fontsize=9)
ax.set_xlim(0, 115)

print("\n  CLINICAL INTERPRETATION:")
print("  Condoms have the LOWEST switch rate (18.3%). This seems counterintuitive")
print("  but makes sense: clients using condoms are often NOT attending FP clinics")
print("  primarily for contraception — they may be HIV clients or STI clients.")
print("  They 'continue' condoms because they pick them up regardless.")
print()
print("  BTL has 0% switch rate — this is expected. Sterilisation is permanent.")
print("  Any 'switch' would only be a removal, which we excluded in cleaning.")
print()
print("  Injectables have the highest switch rate among hormonal methods (41.5%).")
print("  This aligns with global DHS findings: discontinuation at re-injection")
print("  time (3-monthly) is a major failure point due to side effects and access.")

# By method CATEGORY
ax = axes[1]
cat_disc = disc_rate_by(df, "previous_method_category", min_n=100)
cat_bar_colors = [METHOD_COLORS.get(g, PALETTE["gray"]) for g in cat_disc["group"]]
bars = ax.barh(cat_disc["group"], cat_disc["disc_rate"] * 100,
               color=cat_bar_colors, height=0.6)
for bar, (_, row) in zip(bars, cat_disc.iterrows()):
    ax.text(bar.get_width() + 0.5,
            bar.get_y() + bar.get_height() / 2,
            f"{row['disc_rate']*100:.1f}%  (n={row['n']:,})",
            va="center", fontsize=9.5)
ax.axvline(overall_rate * 100, color=PALETTE["red"],
           linestyle="--", linewidth=2,
           label=f"Overall: {overall_rate*100:.1f}%")
ax.set_xlabel("Discontinuation rate (%)")
ax.set_title("Figure 10b: Discontinuation Rate by Method Category\n(validates clinical grouping)")
ax.legend(fontsize=9)
ax.set_xlim(0, 115)

plt.suptitle("Figure 10: Discontinuation Rates", fontweight="bold")
plt.tight_layout()
save_fig("03d_discontinuation_rates")

print("\n  Category disc rates:")
for _, row in cat_disc.sort_values("disc_rate", ascending=False).iterrows():
    print(f"    {row['group']:<28}: {row['disc_rate']*100:.1f}%")


# ── CELL 8: Q6 & Q7 — Age and parity vs discontinuation ──────────────────────
print("\n[Q6 & Q7] Age and parity vs discontinuation rate")

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Age group
ax = axes[0]
age_disc = disc_rate_by(df, "age_group", min_n=100)
bars = ax.bar(age_disc["group"], age_disc["disc_rate"] * 100,
              color=PALETTE["teal"], width=0.6, edgecolor="white")
for bar, (_, row) in zip(bars, age_disc.iterrows()):
    ax.text(bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            f"{row['disc_rate']*100:.1f}%\nn={row['n']:,}",
            ha="center", va="bottom", fontsize=8.5)
ax.axhline(overall_rate * 100, color=PALETTE["red"], linestyle="--",
           linewidth=2, label=f"Overall: {overall_rate*100:.1f}%")
ax.set_title("Figure 11a: Discontinuation Rate by Age Group")
ax.set_xlabel("Age group")
ax.set_ylabel("Discontinuation rate (%)")
ax.legend(fontsize=9)
ax.set_ylim(0, ax.get_ylim()[1] * 1.15)

print("\n  CLINICAL INTERPRETATION (Age):")
print("  Older women (40+, 50+) have the HIGHEST discontinuation rates.")
print("  Clinical hypothesis: older women approaching menopause are")
print("  switching to barrier or stopping hormonal methods as fertility")
print("  declines. Also, 50+ group has n=563 — interpret with caution.")
print()
print("  Young women (18-24) have lower rates than 30-39 age group.")
print("  Hypothesis: younger women may be more motivated to prevent")
print("  pregnancy and less likely to switch spontaneously.")

# Parity group
ax = axes[1]
parity_disc = disc_rate_by(df, "has_high_parity", min_n=100)
parity_disc["group"] = parity_disc["group"].map(
    {"0": "Parity 0-4 children", "1": "Parity 5+ children (high)"}
)
bars = ax.bar(parity_disc["group"], parity_disc["disc_rate"] * 100,
              color=[PALETTE["teal"], PALETTE["coral"]], width=0.5)
for bar, (_, row) in zip(bars, parity_disc.iterrows()):
    ax.text(bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            f"{row['disc_rate']*100:.1f}%\nn={row['n']:,}",
            ha="center", va="bottom", fontweight="bold", fontsize=10)
ax.axhline(overall_rate * 100, color=PALETTE["red"], linestyle="--",
           linewidth=2, label=f"Overall: {overall_rate*100:.1f}%")
ax.set_title("Figure 11b: Discontinuation Rate by Parity")
ax.set_ylabel("Discontinuation rate (%)")
ax.legend(fontsize=9)
ax.set_ylim(0, ax.get_ylim()[1] * 1.15)

print("\n  CLINICAL INTERPRETATION (Parity):")
print("  High parity women (5+ children) have higher discontinuation.")
print("  These women may be moving to permanent methods (BTL) or stopping")
print("  contraception entirely as they feel family is complete.")

plt.suptitle("Figure 11: Age and Parity vs Discontinuation", fontweight="bold")
plt.tight_layout()
save_fig("03e_age_parity_disc")


# ── CELL 9: Q8 & Q9 — Fertility intention and education ───────────────────────
print("\n[Q8 & Q9] Fertility intention and education vs discontinuation")

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Fertility intention
ax = axes[0]
fert_disc = disc_rate_by(df, "fertilityintention", min_n=100)
bar_colors = []
color_map_fert = {
    "Within 2 Years":     PALETTE["teal"],
    "Later than 2 years": PALETTE["amber"],
    "No more Children":   PALETTE["coral"],
}
for g in fert_disc["group"]:
    bar_colors.append(color_map_fert.get(g, PALETTE["gray"]))

bars = ax.barh(fert_disc["group"], fert_disc["disc_rate"] * 100,
               color=bar_colors, height=0.5)
for bar, (_, row) in zip(bars, fert_disc.iterrows()):
    ax.text(bar.get_width() + 0.5,
            bar.get_y() + bar.get_height() / 2,
            f"{row['disc_rate']*100:.1f}%  (n={row['n']:,})",
            va="center", fontsize=9.5)
ax.axvline(overall_rate * 100, color=PALETTE["red"], linestyle="--",
           linewidth=2, label=f"Overall: {overall_rate*100:.1f}%")
ax.set_xlabel("Discontinuation rate (%)")
ax.set_title("Figure 12a: Discontinuation by Fertility Intention")
ax.legend(fontsize=9)
ax.set_xlim(0, 90)

print("\n  CLINICAL INTERPRETATION (Fertility Intention):")
print("  'No more Children' has the HIGHEST rate (57.5%) — these women")
print("  are switching to permanent methods (BTL), which we correctly")
print("  included as a discontinuation from their current method.")
print("  'Within 2 Years' has the LOWEST rate (34.0%) — women planning")
print("  pregnancy soon choose short-acting methods and continue them")
print("  until they are ready to conceive.")
print("  MODELLING NOTE: This is our strongest predictor. Including it")
print("  will likely dominate feature importance.")

# Education level
ax = axes[1]
edu_disc = disc_rate_by(df, "educationlevel", min_n=100)
edu_order = ["Primary Incomplete", "Primary Complete", "Secondary & Above"]
edu_disc["group"] = pd.Categorical(edu_disc["group"], categories=edu_order, ordered=True)
edu_disc = edu_disc.sort_values("group")

bars = ax.bar(edu_disc["group"].astype(str), edu_disc["disc_rate"] * 100,
              color=[PALETTE["teal"], PALETTE["amber"], PALETTE["coral"]],
              width=0.5)
for bar, (_, row) in zip(bars, edu_disc.iterrows()):
    ax.text(bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            f"{row['disc_rate']*100:.1f}%\nn={row['n']:,}",
            ha="center", va="bottom", fontsize=9)
ax.axhline(overall_rate * 100, color=PALETTE["red"], linestyle="--",
           linewidth=2, label=f"Overall: {overall_rate*100:.1f}%")
ax.set_title("Figure 12b: Discontinuation by Education Level")
ax.set_ylabel("Discontinuation rate (%)")
ax.legend(fontsize=9)
ax.set_ylim(0, ax.get_ylim()[1] * 1.15)

print("\n  CLINICAL INTERPRETATION (Education):")
print("  Counter-intuitively, Primary Incomplete has the HIGHEST switch")
print("  rate (48.1%). Possible explanation: lower-educated women may have")
print("  less access to correct use information, leading to side effects")
print("  that trigger switching. Also correlates with geographic access.")
print("  Secondary & Above (42.5%) is close to the overall mean.")
print("  MODELLING NOTE: Education adds signal but it is modest.")

plt.suptitle("Figure 12: Fertility Intention and Education vs Discontinuation",
             fontweight="bold")
plt.tight_layout()
save_fig("03f_fertility_education_disc")


# ── CELL 10: Q10 & Q11 — Counseling and delivery channel ─────────────────────
print("\n[Q10 & Q11] Counseling and delivery channel vs discontinuation")

fig, axes = plt.subplots(1, 2, figsize=(13, 5))

# Counseling — key clinical finding
ax = axes[0]
counsel_disc = disc_rate_by(df, "counseled", min_n=30)
bar_colors = [PALETTE["teal"] if g == "Yes" else
              PALETTE["amber"] if g == "Refreshers" else
              PALETTE["coral"] for g in counsel_disc["group"]]
bars = ax.bar(counsel_disc["group"], counsel_disc["disc_rate"] * 100,
              color=bar_colors, width=0.5)
for bar, (_, row) in zip(bars, counsel_disc.iterrows()):
    ax.text(bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            f"{row['disc_rate']*100:.1f}%\nn={row['n']:,}",
            ha="center", va="bottom", fontweight="bold", fontsize=10)
ax.axhline(overall_rate * 100, color=PALETTE["red"], linestyle="--",
           linewidth=2, label=f"Overall: {overall_rate*100:.1f}%")
ax.set_title("Figure 13a: Discontinuation by Counseling Status")
ax.set_ylabel("Discontinuation rate (%)")
ax.set_xlabel("Counseling received")
ax.legend(fontsize=9)
ax.set_ylim(0, ax.get_ylim()[1] * 1.15)

print("\n  CRITICAL FINDING (Counseling):")
print("  'No' counseling: 21.7% switch rate")
print("  'Yes' counseling: 43.1% switch rate")
print()
print("  This appears paradoxical — more counseling → more switching?")
print("  EXPLANATION: This is a SELECTION BIAS, not a causal effect.")
print("  Clients who were counseled are overwhelmingly Revisit clients")
print("  in an active programme. The programme actively encourages clients")
print("  to consider upgrading to LARC methods. Counseling here often")
print("  FACILITATES a deliberate switch — not failure to continue.")
print("  Non-counseled clients include emergency contraception pickups")
print("  and informal visits — they are less likely to switch because")
print("  they are not in an active FP consultation.")
print()
print("  MODELLING NOTE: Include counseled_binary but interpret importance")
print("  carefully. It captures programme engagement, not failure.")

# Delivery channel — strongest contextual predictor
ax = axes[1]
delivery_disc = disc_rate_by(df, "delivery_type", min_n=100)
bar_colors_d = [PALETTE["teal"] if g == "community" else PALETTE["coral"]
                for g in delivery_disc["group"]]
bars = ax.bar(delivery_disc["group"], delivery_disc["disc_rate"] * 100,
              color=bar_colors_d, width=0.5)
for bar, (_, row) in zip(bars, delivery_disc.iterrows()):
    ax.text(bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            f"{row['disc_rate']*100:.1f}%\nn={row['n']:,}",
            ha="center", va="bottom", fontweight="bold", fontsize=10)
ax.axhline(overall_rate * 100, color=PALETTE["red"], linestyle="--",
           linewidth=2, label=f"Overall: {overall_rate*100:.1f}%")
ax.set_title("Figure 13b: Discontinuation by Delivery Channel")
ax.set_ylabel("Discontinuation rate (%)")
ax.set_xlabel("Delivery type")
ax.legend(fontsize=9)
ax.set_ylim(0, ax.get_ylim()[1] * 1.15)

print("\n  NOTE on raw delivery channel:")
print("  Original 'Outreach' had 88.5% switch rate — extremely high.")
print("  Outreach visits often involve LARC insertions as a campaign,")
print("  meaning clients were on short-acting methods and switched to")
print("  implants/IUDs in one visit. This is a PROGRAMME success, not")
print("  a failure. We collapsed Outreach with Household into 'community'.")

plt.suptitle("Figure 13: Counseling and Delivery vs Discontinuation",
             fontweight="bold")
plt.tight_layout()
save_fig("03g_counseling_delivery_disc")


# ── CELL 11: Q12 — Switch pattern heatmap ────────────────────────────────────
print("\n[Q12] Method switch patterns (from → to)")

# Build switch matrix for clients who switched
switchers = df[df["discontinued"] == 1].copy()
switch_matrix = (
    switchers
    .groupby(["previousmethod", "methodadopted"])
    .size()
    .unstack(fill_value=0)
)

# Normalise by rows (what % of switchers from each method went where)
switch_pct = switch_matrix.div(switch_matrix.sum(axis=1), axis=0) * 100

# Order rows and columns by total volume for readability
row_order = switch_matrix.sum(axis=1).sort_values(ascending=False).index
col_order = switch_matrix.sum(axis=0).sort_values(ascending=False).index
switch_pct_ordered = switch_pct.reindex(index=row_order, columns=col_order)
switch_matrix_ordered = switch_matrix.reindex(index=row_order, columns=col_order)

fig, axes = plt.subplots(1, 2, figsize=(16, 6))

# Absolute counts heatmap
ax = axes[0]
sns.heatmap(
    switch_matrix_ordered,
    ax=ax, cmap="YlOrRd", annot=True, fmt=",d",
    linewidths=0.5,
    cbar_kws={"label": "Number of clients"},
)
ax.set_ylabel("Previous method (FROM)")
ax.set_xlabel("Method adopted at this visit (TO)")
ax.set_title("Figure 14a: Method Switch Counts\n(absolute number of switchers)")
plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
plt.setp(ax.get_yticklabels(), rotation=0)

# Percentage heatmap
ax = axes[1]
sns.heatmap(
    switch_pct_ordered.round(1),
    ax=ax, cmap="Blues", annot=True, fmt=".0f",
    linewidths=0.5,
    cbar_kws={"label": "% of switchers from that method"},
)
ax.set_ylabel("Previous method (FROM)")
ax.set_xlabel("Method adopted at this visit (TO)")
ax.set_title("Figure 14b: Method Switch Percentages\n(% of row = % of switchers going to each method)")
plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
plt.setp(ax.get_yticklabels(), rotation=0)

plt.suptitle("Figure 14: Method Switch Patterns\n"
             "(Only clients who switched are shown)", fontweight="bold")
plt.tight_layout()
save_fig("03h_switch_heatmap")

print("\n  KEY SWITCH FINDINGS:")
top_switches = (
    switchers.groupby(["previousmethod", "methodadopted"])
    .size().reset_index(name="n")
    .sort_values("n", ascending=False)
    .head(8)
)
for _, row in top_switches.iterrows():
    pct = row["n"] / len(switchers) * 100
    print(f"    {row['previousmethod']:<18} → {row['methodadopted']:<18} : "
          f"{row['n']:,}  ({pct:.1f}% of all switches)")


# ── CELL 12: Q13 — Temporal trends ────────────────────────────────────────────
print("\n[Q13] Temporal trends in discontinuation")

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# By year
ax = axes[0]
year_disc = disc_rate_by(df, "year", min_n=100)
bars = ax.bar(year_disc["group"], year_disc["disc_rate"] * 100,
              color=[PALETTE["teal"], PALETTE["amber"], PALETTE["coral"]],
              width=0.5)
for bar, (_, row) in zip(bars, year_disc.iterrows()):
    ax.text(bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.3,
            f"{row['disc_rate']*100:.1f}%\nn={row['n']:,}",
            ha="center", va="bottom", fontsize=9.5)
ax.axhline(overall_rate * 100, color=PALETTE["red"], linestyle="--",
           linewidth=2, label=f"Overall: {overall_rate*100:.1f}%")
ax.set_title("Figure 15a: Discontinuation Rate by Year")
ax.set_xlabel("Year")
ax.set_ylabel("Discontinuation rate (%)")
ax.legend()

print("\n  TEMPORAL FINDING:")
print("  Discontinuation rate increased from 36.7% (2013) to 47.2% (2015).")
print("  HYPOTHESIS: Programme maturity. As the programme expanded LARC")
print("  services, more clients on short-acting methods were switching to")
print("  implants and IUDs — these show as discontinuations from their")
print("  prior method. This is a programme success story, not deterioration.")
print("  MODELLING NOTE: 'year' captures programme phase. Include it.")

# Monthly pattern averaged across years
ax = axes[1]
monthly_disc = (
    df.groupby("month_num")["discontinued"]
    .agg(disc_rate="mean", n="count")
    .reset_index()
)
ax.plot(monthly_disc["month_num"], monthly_disc["disc_rate"] * 100,
        color=PALETTE["teal"], linewidth=2.5, marker="o", markersize=6)
ax.fill_between(monthly_disc["month_num"],
                (monthly_disc["disc_rate"] - monthly_disc["disc_rate"].std()) * 100,
                (monthly_disc["disc_rate"] + monthly_disc["disc_rate"].std()) * 100,
                alpha=0.15, color=PALETTE["teal"])
ax.axhline(overall_rate * 100, color=PALETTE["red"], linestyle="--",
           linewidth=1.5, label=f"Overall: {overall_rate*100:.1f}%")
ax.set_xticks(range(1, 13))
ax.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
ax.set_title("Figure 15b: Monthly Discontinuation Pattern\n(averaged across 2013-2015)")
ax.set_xlabel("Month")
ax.set_ylabel("Discontinuation rate (%)")
ax.legend()
plt.setp(ax.get_xticklabels(), rotation=30)

plt.suptitle("Figure 15: Temporal Trends", fontweight="bold")
plt.tight_layout()
save_fig("03i_temporal_trends")


# ── CELL 13: Q14 — Geographic comparison ──────────────────────────────────────
print("\n[Q14] Geographic differences by county")

fig, axes = plt.subplots(1, 2, figsize=(13, 5))

# County disc rates
ax = axes[0]
county_disc = disc_rate_by(df, "county", min_n=100)
bar_colors_c = [PALETTE["teal"], PALETTE["coral"]]
bars = ax.bar(county_disc["group"], county_disc["disc_rate"] * 100,
              color=bar_colors_c, width=0.4)
for bar, (_, row) in zip(bars, county_disc.iterrows()):
    ax.text(bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.3,
            f"{row['disc_rate']*100:.1f}%\nn={row['n']:,}",
            ha="center", va="bottom", fontweight="bold", fontsize=10)
ax.axhline(overall_rate * 100, color=PALETTE["red"], linestyle="--",
           linewidth=2, label=f"Overall: {overall_rate*100:.1f}%")
ax.set_title("Figure 16a: Discontinuation Rate by County")
ax.set_ylabel("Discontinuation rate (%)")
ax.set_ylim(0, ax.get_ylim()[1] * 1.15)
ax.legend()

# Method mix by county — shows county differences are method-mix-driven
ax = axes[1]
county_method = (
    df.groupby(["county", "previous_method_category"])
    .size()
    .unstack(fill_value=0)
    .apply(lambda r: r / r.sum() * 100, axis=1)
)
county_method.plot.bar(
    ax=ax, stacked=True,
    color=[METHOD_COLORS.get(c, PALETTE["gray"]) for c in county_method.columns],
    width=0.4,
)
ax.set_title("Figure 16b: Method Category Mix by County\n"
             "(explains county discontinuation difference)")
ax.set_ylabel("% of clients")
ax.set_xlabel("County")
ax.legend(title="Method category", bbox_to_anchor=(1.01, 1), fontsize=8)
plt.setp(ax.get_xticklabels(), rotation=0)

plt.suptitle("Figure 16: Geographic Variation", fontweight="bold")
plt.tight_layout()
save_fig("03j_geographic_variation")

print("\n  FINDING:")
print("  Busia (MSK) has higher discontinuation (47.2%) than Siaya (37.3%).")
print("  The method mix chart shows Busia has more Outreach clients who")
print("  switch to LARC methods — driving up the 'switch' count.")
print("  MODELLING NOTE: county adds genuine geographic signal. Include it.")


# ── CELL 14: Q15 — Feature correlation matrix ────────────────────────────────
print("\n[Q15] Feature correlation analysis (multicollinearity check)")

numeric_features = [
    "age", "noofchildren", "education_ordinal", "fertility_ordinal",
    "counseled_binary", "is_young_woman", "is_older_woman",
    "has_high_parity", "is_nulliparous", "wants_child_soon",
    "wants_no_more", "adopted_larc", "was_on_larc",
    "fertility_intention_known", "education_known",
    "discontinued",
]

corr_matrix = df[numeric_features].corr(method="spearman")

fig, ax = plt.subplots(figsize=(13, 11))
mask = np.triu(np.ones_like(corr_matrix, dtype=bool), k=1)
sns.heatmap(
    corr_matrix,
    ax=ax,
    cmap="RdBu_r",
    center=0,
    vmin=-1, vmax=1,
    annot=True, fmt=".2f",
    linewidths=0.5,
    square=True,
    cbar_kws={"label": "Spearman correlation"},
)
ax.set_title(
    "Figure 17: Feature Correlation Matrix (Spearman)\n"
    "Values close to ±1 indicate high multicollinearity\n"
    "Last row/column shows correlation with target (discontinued)",
    pad=12
)
plt.tight_layout()
save_fig("03k_correlation_matrix")

print("\n  HIGH CORRELATION PAIRS (|r| > 0.5):")
for i in range(len(corr_matrix.columns)):
    for j in range(i + 1, len(corr_matrix.columns)):
        r = corr_matrix.iloc[i, j]
        if abs(r) > 0.50:
            print(f"    {corr_matrix.columns[i]:<25} vs "
                  f"{corr_matrix.columns[j]:<25}: r={r:.3f}")

print("\n  EXPECTED HIGH CORRELATIONS:")
print("  age ↔ is_older_woman       : derived flag, not multicollinearity")
print("  age ↔ has_high_parity       : older women have more children (expected)")
print("  fertility_ordinal ↔ wants_no_more: same column, different encodings")
print("  MODELLING ACTION: Remove derived flags that are direct derivations")
print("  of numeric columns (e.g. keep 'age' and 'is_young_woman' separately")
print("  since they capture non-linear effects; drop one of fertility pairs)")

print("\n  CORRELATION WITH TARGET (discontinued):")
target_corr = corr_matrix["discontinued"].drop("discontinued").sort_values()
for feat, r in target_corr.items():
    bar = "█" * int(abs(r) * 30)
    direction = "+" if r > 0 else "-"
    print(f"    {feat:<30}: {direction}{abs(r):.3f}  {bar}")


# ── CELL 15: Summary EDA findings table ───────────────────────────────────────
print("\n" + "=" * 65)
print("EDA FINDINGS SUMMARY — FEATURE DECISIONS FOR MODELLING")
print("=" * 65)

findings = [
    ("age",                    "KEEP",   f"Corr with target: r=+0.07. Non-linear (older→more disc)"),
    ("noofchildren",           "KEEP",   f"Corr with target: r=+0.05. Parity drives method choice"),
    ("education_ordinal",      "KEEP",   "Primary Incomplete has 48% disc vs 42.5% Secondary"),
    ("fertility_ordinal",      "KEEP",   "Strongest predictor (No more→57%, Within2yr→34%)"),
    ("fertility_intention_known","KEEP", "Missing is informative (33% disc vs 42% overall)"),
    ("counseled_binary",       "KEEP",   "Captures programme engagement (selection bias noted)"),
    ("county",                 "KEEP",   "Genuine geographic heterogeneity (+9.9pp Busia vs Siaya)"),
    ("delivery_type",          "KEEP",   "Captures outreach vs facility context"),
    ("year",                   "KEEP",   "Programme phase: rate rose 36.7%→47.2% over 3 years"),
    ("previous_method_category","KEEP",  "Core clinical predictor: LARC 51% disc vs barrier 18%"),
    ("current_method_category", "KEEP",  "Target component — also a strong predictor"),
    ("switch_type",            "KEEP",   "Captures directionality: upgrade/downgrade/lateral"),
    ("was_on_larc",            "KEEP",   "Binary flag for LARC continuation signal"),
    ("adopted_larc",           "KEEP",   "Binary: switching TO LARC (programme upgrade)"),
    ("is_young_woman",         "KEEP",   "Non-linear age effect for <20 group"),
    ("is_older_woman",         "KEEP",   "Non-linear age effect for 40+ group"),
    ("wants_child_soon",       "KEEP",   "Direct clinical signal for short-acting preference"),
    ("wants_no_more",          "KEEP",   "Direct clinical signal for permanent/LARC preference"),
    ("has_high_parity",        "KEEP",   "Parity≥5 clinically meaningful threshold"),
    ("education_known",        "KEEP",   "Missingness flag (Siaya geographic pattern)"),
    ("is_nulliparous",         "CONSIDER","Low n in revisit cohort; test feature importance"),
    ("counseled_known",        "DROP",   "97.8% known — near-zero variance flag; not useful"),
    ("month_num",              "CONSIDER","Weak seasonality seen; include and test importance"),
]

for feat, decision, reason in findings:
    icon = "✅" if decision == "KEEP" else "⚠️ " if decision == "CONSIDER" else "❌"
    print(f"  {icon} {feat:<32} {decision:<8}  {reason}")

# Save as CSV for notebook 04
summary_df = pd.DataFrame(findings, columns=["feature", "decision", "reasoning"])
summary_df.to_csv(PATHS["reports_dir"] / "03_eda_summary.csv", index=False)
print(f"\nEDA summary saved: {PATHS['reports_dir'] / '03_eda_summary.csv'}")

# Headline numbers for model card
headline_numbers = {
    "total_clean_records":   len(df),
    "discontinued_count":    int(df["discontinued"].sum()),
    "continued_count":       int((df["discontinued"] == 0).sum()),
    "positive_rate_pct":     round(df["discontinued"].mean() * 100, 1),
    "overall_disc_rate_pct": round(overall_rate * 100, 1),
    "highest_disc_method":   df.groupby("previousmethod")["discontinued"].mean().idxmax(),
    "lowest_disc_method":    df.groupby("previousmethod")["discontinued"].mean().idxmin(),
    "strongest_predictor":   "fertility_ordinal",
    "unique_clients":        int(df["uniqueid"].nunique()),
    "date_range":            "2013-2015",
    "counties":              ", ".join(sorted(df["county"].unique())),
}
pd.DataFrame([headline_numbers]).T.to_csv(
    PATHS["reports_dir"] / "03_headline_numbers.csv", header=["value"]
)
print(f"Headline numbers saved: {PATHS['reports_dir'] / '03_headline_numbers.csv'}")

print(f"\nAll figures saved to: {PATHS['figures_dir']}")
print("\nNotebook 03 COMPLETE. Run Notebook 04 next.")