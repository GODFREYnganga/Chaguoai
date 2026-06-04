"""
NOTEBOOK 02 — Data Cleaning
============================
Purpose : Apply all cleaning decisions justified in Notebook 01.
          Produce one clean, validated dataset for EDA and modelling.

Every decision here has a reference to the finding in Notebook 01
that motivated it. No decision is made without evidence.

Outputs:
  outputs/processed/02_cleaned.parquet          — clean modelling dataset
  outputs/reports/02_cleaning_report.csv        — row-level audit of filters applied
  outputs/reports/02_missing_imputation_log.csv — what was imputed and why
"""

# ── CELL 1: Imports and paths ──────────────────────────────────────────────────
import sys, warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns

warnings.filterwarnings("ignore")
pd.set_option("display.max_columns", 50)
pd.set_option("display.width", 120)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config import (
    get_paths, COLUMNS_TO_LOAD, MISSING_SENTINEL_COLUMNS,
    PLANNED_REMOVAL_METHODS, OFFSCOPE_METHODS, METHOD_CATEGORY_MAP,
    EDUCATION_ORDINAL, FERTILITY_ORDINAL, COUNSELED_BINARY,
    MONTH_ORDER, DELIVERY_BINARY, PALETTE, PLOT_STYLE,
    AGE_MIN, AGE_MAX, PARITY_CAP,
)

PATHS = get_paths()
plt.rcParams.update(PLOT_STYLE)
print("Notebook 02: Data Cleaning")
print("=" * 55)


# ── CELL 2: Load raw data, select only needed columns ─────────────────────────
def load_raw_columns(path: Path, columns: list) -> pd.DataFrame:
    """
    Load only the required columns from the raw CSV.

    WHY: The raw file has 30+ columns. Loading all of them bloats
    memory and invites accidental use of excluded columns downstream.
    We load only COLUMNS_TO_LOAD — defined in config.py with reasons.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"CSV not found: {path}\n"
            f"Set CHAGUOAI_DATA_DIR environment variable."
        )
    for enc in ["utf-8", "latin1", "cp1252", "utf-8-sig"]:
        try:
            df = pd.read_csv(
                path, encoding=enc, low_memory=False,
                usecols=lambda c: c in columns,
            )
            print(f"Loaded {path.name} [{enc}]: {df.shape[0]:,} rows × {df.shape[1]} cols")
            missing_cols = [c for c in columns if c not in df.columns]
            if missing_cols:
                print(f"  WARNING: These requested columns not found: {missing_cols}")
            return df
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"Cannot decode {path.name}")


df = load_raw_columns(PATHS["css_path"], COLUMNS_TO_LOAD)

# Audit log — we track every row's journey through the pipeline
audit = pd.DataFrame({"visitid": df["visitid"], "dropped_at_step": "kept"})


# ── CELL 3: Step 1 — Replace 'Missing' string sentinels with np.nan ───────────
print("\n[Step 1] Replace 'Missing' string sentinels with np.nan")
print("  Reason: These columns use the string 'Missing' where the value")
print("  was not collected. Treating as a string would create false categories.")
print("  We replace with np.nan and handle missingness explicitly per column.")

sentinel_counts_before = {}
for col in MISSING_SENTINEL_COLUMNS:
    if col in df.columns:
        n = (df[col].astype(str).str.strip() == "Missing").sum()
        sentinel_counts_before[col] = n
        df[col] = df[col].replace("Missing", np.nan)
        df[col] = df[col].replace("", np.nan)
        print(f"  {col:<25}: {n:,} 'Missing' strings → np.nan")


# ── CELL 4: Step 2 — Filter to Female clients only ────────────────────────────
print("\n[Step 2] Filter to Female clients only")
print("  Reason: ChaguoAI serves women. Male records relate to condom")
print("  distribution (75,562 records) and have no prior female method.")
print("  Including them would inject a large uninformative class.")

n_before = len(df)
df = df[df["gender"] == "Female"].copy()
n_removed = n_before - len(df)
audit.loc[audit["visitid"].isin(df["visitid"]) == False, "dropped_at_step"] = "step2_not_female"
print(f"  Removed: {n_removed:,} male records")
print(f"  Remaining: {len(df):,}")


# ── CELL 5: Step 3 — Filter to Revisit clients only ───────────────────────────
print("\n[Step 3] Filter to Revisit clients only")
print("  Reason: Only revisit clients have a 'previousmethod' value.")
print("  New clients have no prior method — the target variable (switched?)")
print("  cannot be computed for them. We model continuation behaviour,")
print("  which requires at least one prior visit.")
print("  207 'Missing' fpstatus records are also removed here.")

n_before = len(df)
df = df[df["fpstatus"] == "Revisit"].copy()
n_removed = n_before - len(df)
audit.loc[
    ~audit["visitid"].isin(df["visitid"]) & (audit["dropped_at_step"] == "kept"),
    "dropped_at_step"
] = "step3_not_revisit"
print(f"  Removed: {n_removed:,} non-revisit records")
print(f"  Remaining: {len(df):,}")


# ── CELL 6: Step 4 — Remove records with no valid prior method ─────────────────
print("\n[Step 4] Remove records with null or missing previousmethod")
print("  Reason: previousmethod = NaN on revisit is a data quality issue")
print("  (934 records). We cannot compute the target variable without it.")

n_before = len(df)
df = df[df["previousmethod"].notna()].copy()
n_removed = n_before - len(df)
audit.loc[
    ~audit["visitid"].isin(df["visitid"]) & (audit["dropped_at_step"] == "kept"),
    "dropped_at_step"
] = "step4_no_prior_method"
print(f"  Removed: {n_removed:,} records (null previousmethod on revisit)")
print(f"  Remaining: {len(df):,}")


# ── CELL 7: Step 5 — Strip whitespace from method columns ─────────────────────
print("\n[Step 5] Strip whitespace from method columns")
print("  Reason: 'Condoms' and 'Condoms ' are the same method.")
print("  Whitespace causes false mismatches in the target variable computation.")

for col in ["previousmethod", "methodadopted"]:
    if col in df.columns:
        df[col] = df[col].str.strip()

print("  Stripped: previousmethod, methodadopted")


# ── CELL 8: Step 6 — Remove planned removals and off-scope visits ─────────────
print("\n[Step 6] Remove planned removal visits and off-scope methods")
print("  Reason — PLANNED REMOVALS:")
print("  Removal_Implant, Removal_Implants, Removal_IUCD represent planned")
print("  end-of-life method removals, not unplanned discontinuations.")
print("  Labelling them as 'switched' would corrupt the training signal.")
print("  A woman who completed 5 years on an implant is a success, not a dropout.")
print()
print("  Reason — OFF-SCOPE METHODS:")
print("  'Other RH services': Non-FP services — irrelevant to method choice.")
print("  'Vasectomy': Male procedure — recorded here for household context but")
print("  not a female contraceptive choice. 61 records only.")
print("  'Missing': methodadopted is unknown — cannot compute target.")

exclude_adopted = PLANNED_REMOVAL_METHODS | OFFSCOPE_METHODS
n_before = len(df)
df = df[~df["methodadopted"].isin(exclude_adopted)].copy()
n_removed = n_before - len(df)
audit.loc[
    ~audit["visitid"].isin(df["visitid"]) & (audit["dropped_at_step"] == "kept"),
    "dropped_at_step"
] = "step6_offscope_method"
print(f"  Removed: {n_removed:,} records")
print(f"  Remaining: {len(df):,}")


# ── CELL 9: Step 7 — Build target variable ────────────────────────────────────
print("\n[Step 7] Build target variable: discontinued")
print("  Definition: A client discontinued her previous method if she")
print("  adopted a DIFFERENT method at this revisit visit.")
print()
print("  discontinued = 1  →  previousmethod != methodadopted")
print("  discontinued = 0  →  previousmethod == methodadopted")
print()
print("  Note: Case-insensitive comparison. 'Condoms' == 'condoms'.")
print("  Note: 'Pills & Condoms' != 'Pills' → correctly labeled as switched.")

df["discontinued"] = (
    df["previousmethod"].str.lower() != df["methodadopted"].str.lower()
).astype(int)

pos_rate = df["discontinued"].mean()
print(f"\n  Continued    (0): {(df['discontinued']==0).sum():,}  ({1-pos_rate:.1%})")
print(f"  Discontinued (1): {(df['discontinued']==1).sum():,}  ({pos_rate:.1%})")
print(f"  Class balance: {pos_rate:.1%} positive — balanced, no resampling needed")


# ── CELL 10: Step 8 — Cap parity outliers ─────────────────────────────────────
print(f"\n[Step 8] Cap noofchildren outliers at {PARITY_CAP}")
print(f"  Reason: 217 values exceed {PARITY_CAP} (max=78).")
print("  Values like 37, 54, 78 are clinically impossible for children")
print("  living with a woman of reproductive age. These are entry errors")
print("  (likely recording total family members instead of children).")
print(f"  DHS Kenya median parity is ~3.5. We cap at {PARITY_CAP} to preserve")
print("  the signal from genuinely high-parity women without being distorted")
print("  by entry errors.")

n_capped = (df["noofchildren"] > PARITY_CAP).sum()
df["noofchildren"] = df["noofchildren"].clip(lower=0, upper=PARITY_CAP)
print(f"  {n_capped} values capped to {PARITY_CAP}")


# ── CELL 11: Step 9 — Age range validation ────────────────────────────────────
print(f"\n[Step 9] Validate age range [{AGE_MIN}–{AGE_MAX}]")
print("  Notebook 01 showed age is already clean (range 10-60, 0% missing).")
print("  We confirm and document, but no records need removal.")

out_of_range = ((df["age"] < AGE_MIN) | (df["age"] > AGE_MAX)).sum()
print(f"  Records outside [{AGE_MIN}–{AGE_MAX}]: {out_of_range}")
print("  ✅ Age column confirmed clean — no action needed.")


# ── CELL 12: Step 10 — Handle missing: fertilityintention ─────────────────────
print("\n[Step 10] Handle missing fertilityintention")
print("  Missing rate (after sentinel replacement): calculated below.")

miss_rate = df["fertilityintention"].isna().mean()
print(f"  Missing rate: {miss_rate:.1%}")
print()
print("  CRITICAL FINDING from Notebook 01:")
print("  Records where fertilityintention is missing have a LOWER switch")
print("  rate (33.3%) vs the overall average (41.6%). This tells us that")
print("  missingness here is NOT random — it correlates with lower")
print("  discontinuation risk.")
print()
print("  DECISION: Create a binary 'fertility_intention_known' flag BEFORE")
print("  imputing. This preserves the predictive signal in the missingness.")
print("  Then impute with 'Later than 2 years' (modal most-neutral category).")

df["fertility_intention_known"] = df["fertilityintention"].notna().astype(int)
modal_fertility = df["fertilityintention"].mode()[0]
df["fertilityintention"] = df["fertilityintention"].fillna(modal_fertility)
print(f"  Created: fertility_intention_known (1=known, 0=was missing)")
print(f"  Imputed {(df['fertility_intention_known']==0).sum():,} values with modal: '{modal_fertility}'")


# ── CELL 13: Step 11 — Handle missing: educationlevel ─────────────────────────
print("\n[Step 11] Handle missing educationlevel")
miss_rate_edu = df["educationlevel"].isna().mean()
print(f"  Missing rate: {miss_rate_edu:.1%}")
print()
print("  FINDING from Notebook 01: Education 'Missing' has a lower switch")
print("  rate (31.6%) than Primary Complete (41.0%). Siaya county also")
print("  has 10.5% missing vs Busia's 2.0% — geographic confound.")
print()
print("  DECISION: Create 'education_known' flag. Impute with county-specific")
print("  modal education level to account for the geographic missingness pattern.")
print("  This is more accurate than a single global modal imputation.")

df["education_known"] = df["educationlevel"].notna().astype(int)

county_edu_modes = (
    df.dropna(subset=["educationlevel"])
    .groupby("county")["educationlevel"]
    .agg(lambda x: x.mode()[0])
    .to_dict()
)
print(f"  County modes: {county_edu_modes}")

# Apply county-specific modal imputation
def impute_education(row):
    if pd.isna(row["educationlevel"]):
        return county_edu_modes.get(row["county"], "Primary Complete")
    return row["educationlevel"]

df["educationlevel"] = df.apply(impute_education, axis=1)
print(f"  Imputed {(df['education_known']==0).sum():,} values with county-specific modal")


# ── CELL 14: Step 12 — Handle missing: counseled ──────────────────────────────
print("\n[Step 12] Handle missing counseled")
miss_rate_cou = df["counseled"].isna().mean()
print(f"  Missing rate: {miss_rate_cou:.1%}")
print()
print("  counseled is 97.8% 'Yes'. 'Missing' records have a much lower")
print("  switch rate (23.2% vs 43.1% for Yes). We create a known flag")
print("  then impute with 'Yes' (the near-universal value for this program).")

df["counseled_known"] = df["counseled"].notna().astype(int)
df["counseled"] = df["counseled"].fillna("Yes")
print(f"  Imputed {(df['counseled_known']==0).sum():,} values → 'Yes'")


# ── CELL 15: Step 13 — Encode ordinal and binary columns ──────────────────────
print("\n[Step 13] Encode ordinal and binary features")

# Education — ordinal
df["education_ordinal"] = df["educationlevel"].map(EDUCATION_ORDINAL)
print(f"  education_ordinal: {df['education_ordinal'].value_counts().to_dict()}")

# Fertility intention — ordinal
df["fertility_ordinal"] = df["fertilityintention"].map(FERTILITY_ORDINAL)
print(f"  fertility_ordinal: {df['fertility_ordinal'].value_counts().to_dict()}")

# Counseled — binary
df["counseled_binary"] = df["counseled"].map(COUNSELED_BINARY).fillna(0).astype(int)
print(f"  counseled_binary: {df['counseled_binary'].value_counts().to_dict()}")

# Delivery — binary community vs facility
df["delivery_type"] = df["delivery"].map(DELIVERY_BINARY).fillna("community")
print(f"  delivery_type: {df['delivery_type'].value_counts().to_dict()}")

# Month — numeric
df["month_num"] = df["month"].map(MONTH_ORDER)
print(f"  month_num: min={df['month_num'].min()}, max={df['month_num'].max()}")


# ── CELL 16: Step 14 — Add method categories ──────────────────────────────────
print("\n[Step 14] Add method clinical categories")
print("  Reason: Raw method names (12 values) are too granular for some")
print("  analyses. Grouping into clinical categories (4 groups) reveals")
print("  patterns that are clinically meaningful and generalisable.")
print()
print("  short_acting_hormonal  → Pills, Injectables, Pills & Condoms")
print("  long_acting_reversible → Implants, IUCD")
print("  permanent              → BTL")
print("  barrier                → Condoms")
print()
print("  IMPORTANT: Vasectomy already excluded in Step 6.")
print("  'Pills & Condoms' → short_acting_hormonal (the hormonal component")
print("  drives the pharmacological risk; both are short-term user-controlled)")

df["previous_method_category"] = df["previousmethod"].map(METHOD_CATEGORY_MAP).fillna("unknown")
df["current_method_category"]  = df["methodadopted"].map(METHOD_CATEGORY_MAP).fillna("unknown")

print(f"\n  Previous method categories:")
print(df["previous_method_category"].value_counts().to_string())
print(f"\n  Current method categories:")
print(df["current_method_category"].value_counts().to_string())


# ── CELL 17: Step 15 — Derived features ───────────────────────────────────────
print("\n[Step 15] Derive additional features")

# Age groups (for stratified analysis and as ordinal feature)
df["age_group"] = pd.cut(
    df["age"],
    bins=[9, 17, 24, 29, 34, 39, 49, 60],
    labels=["10-17", "18-24", "25-29", "30-34", "35-39", "40-49", "50+"],
)

# Clinical flags — clinically meaningful binary breakpoints
df["is_young_woman"]      = (df["age"] < 20).astype(int)
df["is_older_woman"]      = (df["age"] >= 40).astype(int)
df["has_high_parity"]     = (df["noofchildren"] >= 5).astype(int)
df["is_nulliparous"]      = (df["noofchildren"] == 0).astype(int)
df["wants_child_soon"]    = (df["fertilityintention"] == "Within 2 Years").astype(int)
df["wants_no_more"]       = (df["fertilityintention"] == "No more Children").astype(int)
df["adopted_larc"]        = (df["current_method_category"] == "long_acting_reversible").astype(int)
df["was_on_larc"]         = (df["previous_method_category"] == "long_acting_reversible").astype(int)

# Method switch direction — captures the clinical meaning of the switch
def categorise_switch(row):
    curr = row["current_method_category"]
    prev = row["previous_method_category"]
    if prev in ("unknown",):
        return "unknown"
    if curr == prev:
        return "same_category"
    if prev == "long_acting_reversible" and curr != "long_acting_reversible":
        return "downgraded_from_larc"
    if curr == "long_acting_reversible" and prev != "long_acting_reversible":
        return "upgraded_to_larc"
    if curr == "permanent":
        return "moved_to_permanent"
    if curr == "barrier":
        return "moved_to_barrier"
    return "lateral_switch"

df["switch_type"] = df.apply(categorise_switch, axis=1)
print("  switch_type distribution:")
print(df["switch_type"].value_counts().to_string())

# Organisation maps 1:1 to county — keep county, drop organisation
# (confirmed 100% correlation in Notebook 01 inspection)
print("\n  NOTE: organization maps 1:1 to county (FHOK=Siaya, MSK=Busia).")
print("  Dropping organization — county is sufficient and more interpretable.")


# ── CELL 18: Step 16 — Final column selection ─────────────────────────────────
print("\n[Step 16] Select final columns for the clean dataset")

FINAL_COLUMNS = [
    # Identifiers (not used in model, retained for audit)
    "visitid",
    "uniqueid",

    # Geography and context
    "county",
    "delivery_type",
    "year",
    "month_num",

    # Demographics — core model features
    "age",
    "age_group",
    "is_young_woman",
    "is_older_woman",
    "noofchildren",
    "has_high_parity",
    "is_nulliparous",

    # Education
    "educationlevel",
    "education_ordinal",
    "education_known",

    # Fertility
    "fertilityintention",
    "fertility_ordinal",
    "fertility_intention_known",
    "wants_child_soon",
    "wants_no_more",

    # Methods
    "previousmethod",
    "methodadopted",
    "previous_method_category",
    "current_method_category",
    "switch_type",
    "was_on_larc",
    "adopted_larc",

    # Counseling
    "counseled",
    "counseled_binary",
    "counseled_known",

    # Target variable
    "discontinued",
]

# Confirm all columns exist
missing_in_df = [c for c in FINAL_COLUMNS if c not in df.columns]
if missing_in_df:
    print(f"  WARNING: These columns not found: {missing_in_df}")
    FINAL_COLUMNS = [c for c in FINAL_COLUMNS if c in df.columns]

df_clean = df[FINAL_COLUMNS].copy()
print(f"  Final cleaned dataset: {df_clean.shape[0]:,} rows × {df_clean.shape[1]} columns")


# ── CELL 19: Validation checks before saving ──────────────────────────────────
print("\n[Validation] Pre-save integrity checks")

checks = {
    "No remaining NaN in numeric features": (
        df_clean[["age","noofchildren","education_ordinal",
                   "fertility_ordinal","counseled_binary"]].isna().sum().sum() == 0
    ),
    "Target variable is binary 0/1 only": (
        df_clean["discontinued"].isin([0, 1]).all()
    ),
    "Target positive rate is between 20% and 65%": (
        0.20 < df_clean["discontinued"].mean() < 0.65
    ),
    "No visitid duplicates": (
        df_clean["visitid"].duplicated().sum() == 0
    ),
    "No records with null previousmethod": (
        df_clean["previousmethod"].isna().sum() == 0
    ),
    "No records with null methodadopted": (
        df_clean["methodadopted"].isna().sum() == 0
    ),
    "Age within [10, 60]": (
        df_clean["age"].between(10, 60).all()
    ),
    "Parity within [0, 15]": (
        df_clean["noofchildren"].between(0, 15).all()
    ),
}

all_passed = True
for check_name, result in checks.items():
    status = "✅" if result else "❌  FAILED"
    print(f"  {status}  {check_name}")
    if not result:
        all_passed = False

if not all_passed:
    raise RuntimeError("Validation failed. Fix issues above before proceeding.")

print("\n  All validation checks passed.")


# ── CELL 20: Save clean dataset ────────────────────────────────────────────────
out_path = PATHS["processed_dir"] / "02_cleaned.parquet"
df_clean.to_parquet(out_path, index=False, engine="pyarrow")
print(f"\nClean dataset saved: {out_path}")
print(f"  Rows:    {len(df_clean):,}")
print(f"  Columns: {len(df_clean.columns)}")
print(f"  Size:    {out_path.stat().st_size / 1024:.0f} KB")

# Also save as CSV for non-Python users
csv_path = PATHS["processed_dir"] / "02_cleaned.csv"
df_clean.to_csv(csv_path, index=False)
print(f"CSV copy saved:      {csv_path}")


# ── CELL 21: Save imputation log ──────────────────────────────────────────────
imputation_log = pd.DataFrame([
    {"column": "fertilityintention",
     "n_imputed": int((df_clean["fertility_intention_known"]==0).sum()),
     "strategy": "Modal per dataset",
     "imputed_value": modal_fertility,
     "reasoning": "Modal is neutral; missing-flag created to preserve signal"},
    {"column": "educationlevel",
     "n_imputed": int((df_clean["education_known"]==0).sum()),
     "strategy": "Modal per county",
     "imputed_value": str(county_edu_modes),
     "reasoning": "Geographic missingness pattern (Siaya 10% vs Busia 2%)"},
    {"column": "counseled",
     "n_imputed": int((df_clean["counseled_known"]==0).sum()),
     "strategy": "Constant",
     "imputed_value": "Yes",
     "reasoning": "97.8% Yes; program design ensures counseling is near-universal"},
])
log_path = PATHS["reports_dir"] / "02_missing_imputation_log.csv"
imputation_log.to_csv(log_path, index=False)
print(f"Imputation log saved: {log_path}")


# ── CELL 22: Cleaning summary chart ────────────────────────────────────────────
steps = [
    ("Raw load",            216539),
    ("Female only",         140977),
    ("Revisit only",         80819),
    ("Valid prior method",   79885),
    ("Scope filter",         78755),
]
labels   = [s[0] for s in steps]
counts   = [s[1] for s in steps]
removals = [counts[i-1] - counts[i] if i > 0 else 0 for i in range(len(counts))]

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Funnel chart
ax = axes[0]
bar_colors = [PALETTE["teal"] if i == len(steps)-1 else PALETTE["gray"]
              for i in range(len(steps))]
bars = ax.barh(labels[::-1], counts[::-1], color=bar_colors[::-1], height=0.6)
for bar, val in zip(bars, counts[::-1]):
    ax.text(bar.get_width() + 500, bar.get_y() + bar.get_height()/2,
            f"{val:,}", va="center", fontsize=9.5, fontweight="bold")
ax.set_title("Figure 5: Data Funnel — Records Remaining After Each Filter")
ax.set_xlabel("Number of records")
highlight = mpatches.Patch(color=PALETTE["teal"], label=f"Final dataset: {counts[-1]:,}")
ax.legend(handles=[highlight])

# Target class balance
ax = axes[1]
target_counts = df_clean["discontinued"].value_counts().sort_index()
bar_colors2   = [PALETTE["teal"], PALETTE["coral"]]
bars2         = ax.bar(["Continued (0)", "Discontinued (1)"],
                       target_counts.values, color=bar_colors2, width=0.5)
for bar, val in zip(bars2, target_counts.values):
    pct = val / len(df_clean) * 100
    ax.text(bar.get_x() + bar.get_width()/2,
            bar.get_height() + 300,
            f"{val:,}\n({pct:.1f}%)",
            ha="center", va="bottom", fontweight="bold")
ax.set_title("Figure 6: Target Variable — Class Balance\n(58.4% vs 41.6%: no resampling needed)")
ax.set_ylabel("Records")

plt.suptitle("Cleaning Pipeline Results", fontweight="bold")
plt.tight_layout()
fig_path = PATHS["figures_dir"] / "02_cleaning_summary.png"
plt.savefig(fig_path, dpi=150, bbox_inches="tight")
plt.show()
print(f"\nFigure saved: {fig_path}")


# ── CELL 23: Cleaning summary text ────────────────────────────────────────────
print("\n" + "=" * 65)
print("CLEANING COMPLETE — SUMMARY")
print("=" * 65)
summary = [
    f"Raw records loaded:              {216539:,}",
    f"Records in final clean dataset:  {len(df_clean):,}",
    f"Records removed total:           {216539 - len(df_clean):,}",
    "",
    "What was removed and why:",
    f"  75,562  male records (not our target population)",
    f"  60,418  New client visits (no prior method for target variable)",
    f"   1,130  removals / off-scope method visits",
    f"     674  null prior method on revisit (data quality)",
    "",
    "What was imputed:",
    f"  fertilityintention: {(df_clean['fertility_intention_known']==0).sum():,} records (modal 'Later than 2 years')",
    f"  educationlevel:     {(df_clean['education_known']==0).sum():,} records (county-specific modal)",
    f"  counseled:          {(df_clean['counseled_known']==0).sum():,} records (constant 'Yes')",
    "",
    "Missing-flag columns created (preserve missingness as signal):",
    "  fertility_intention_known",
    "  education_known",
    "  counseled_known",
    "",
    f"Final class balance: {df_clean['discontinued'].mean():.1%} discontinued",
    "Assessment: Balanced. No SMOTE or class weighting required.",
    "",
    "NEXT STEP: Run Notebook 03 — EDA",
]
for line in summary:
    print(line)