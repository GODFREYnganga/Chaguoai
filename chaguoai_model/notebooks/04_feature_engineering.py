"""
NOTEBOOK 04 — Feature Engineering
====================================
Purpose : Transform the clean dataset into a model-ready feature
          matrix. This is the final step before model training.

          Every feature decision here is grounded in two sources:
            1. Clinical reasoning (Kenya FP Guidelines 7th Ed,
               WHO MEC 6th Ed, and family planning literature)
            2. Empirical evidence from Notebook 03 EDA findings

Rule    : This notebook reads from 02_cleaned.parquet.
          It does NOT retrain the model — only builds and saves
          the feature matrix that Notebook 05 will consume.

What this notebook does:
  1.  Load clean data and EDA feature decisions
  2.  Select final feature set with documented rationale
  3.  Encode all categorical features (fit on train, apply to all)
  4.  Handle any remaining edge cases in feature values
  5.  Create the 70/15/15 client-level split (NOT row-level)
  6.  Validate the final feature matrix end-to-end
  7.  Save train / validation / test splits separately
  8.  Plot feature distributions and correlation in final matrix
  9.  Generate a feature engineering report

WHY CLIENT-LEVEL SPLIT (not row-level):
  Each of the 3,838 unique clients appears an average of 20+ times.
  A row-level random split would put the same client's visits in
  both training and test sets — the model would see 'future' visits
  of training clients in the test set. This is data leakage.
  We split by uniqueid: all visits from a client go to exactly one
  of train / val / test. This mirrors real-world deployment where
  the model is used for NEW clients it has never seen.

Outputs:
  outputs/processed/04_X_train.parquet   — training features
  outputs/processed/04_y_train.parquet   — training labels
  outputs/processed/04_X_val.parquet     — validation features
  outputs/processed/04_y_val.parquet     — validation labels
  outputs/processed/04_X_test.parquet    — test features (sealed)
  outputs/processed/04_y_test.parquet    — test labels (sealed)
  outputs/processed/04_encoders.pkl      — fitted encoders
  outputs/processed/04_feature_meta.json — feature documentation
  outputs/reports/04_feature_report.csv  — per-feature statistics
  outputs/figures/04_*.png               — validation charts
"""

# ── CELL 1: Imports ────────────────────────────────────────────────────────────
import sys, warnings, json, pickle
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns

from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split

warnings.filterwarnings("ignore")
pd.set_option("display.max_columns", 50)
pd.set_option("display.width", 120)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config import (
    get_paths, PALETTE, PLOT_STYLE,
    RANDOM_SEED, TRAIN_RATIO, VAL_RATIO, TEST_RATIO,
    METHOD_CATEGORY_MAP,
)

PATHS = get_paths()
plt.rcParams.update(PLOT_STYLE)

print("Notebook 04: Feature Engineering")
print("=" * 55)
print(f"Random seed:   {RANDOM_SEED}")
print(f"Train/Val/Test: {TRAIN_RATIO:.0%} / {VAL_RATIO:.0%} / {TEST_RATIO:.0%}")


# ── CELL 2: Load clean data ────────────────────────────────────────────────────
def load_clean(paths: dict) -> pd.DataFrame:
    """Load the clean parquet. Falls back to CSV if parquet not found."""
    parquet = paths["processed_dir"] / "02_cleaned.parquet"
    csv     = paths["processed_dir"] / "02_cleaned.csv"
    if parquet.exists():
        df = pd.read_parquet(parquet)
        print(f"Loaded: {parquet.name}  —  {df.shape[0]:,} rows × {df.shape[1]} cols")
    elif csv.exists():
        df = pd.read_csv(csv, low_memory=False)
        print(f"Loaded fallback CSV: {csv.name}  —  {df.shape}")
    else:
        raise FileNotFoundError(
            "Clean dataset not found. Run Notebook 02 first.\n"
            f"Expected: {parquet}"
        )
    return df


df = load_clean(PATHS)
print(f"\nUnique clients (uniqueid): {df['uniqueid'].nunique():,}")
print(f"Target positive rate:      {df['discontinued'].mean():.1%}")


# ── CELL 3: Final feature specification ───────────────────────────────────────
print("\n" + "=" * 55)
print("FINAL FEATURE SPECIFICATION")
print("=" * 55)

# ────────────────────────────────────────────────────────────────────────────
# FEATURE DESIGN DECISIONS
#
# WHAT WE ARE PREDICTING:
#   discontinued = 1 → client switched or stopped method at revisit
#   discontinued = 0 → client continued same method at revisit
#
# GOAL AT INFERENCE TIME:
#   Given a new ChaguoAI user's intake profile, predict the probability
#   that she will discontinue each candidate method within ~90 days.
#   The model ranks methods by predicted adherence.
#
# CRITICAL CONSTRAINT:
#   Features must be available at intake time — BEFORE she starts a
#   method. We cannot use features that reveal the outcome.
#
# DATA LEAKAGE CHECK:
#   current_method_category  → tells us what method she switched TO.
#     This IS available at intake (it is the candidate method we evaluate).
#     We must handle it carefully: at training time it is the adopted method;
#     at inference time it is the candidate method we are scoring.
#     DECISION: Include it. It captures the strongest clinical signal
#     (LARC methods have inherently lower discontinuation). The model
#     learns this mapping from data.
#
#   switch_type              → depends on current AND previous method.
#     Available at inference (previous = prior method, current = candidate).
#     DECISION: Include it.
#
# FEATURES EXCLUDED AFTER EDA (with reasons):
#   counseled_known   → 97.8% known. Near-zero variance. Zero predictive value.
#   is_nulliparous    → Collinear with noofchildren. Low revisit sample.
#   visitid           → Row identifier. No predictive signal.
#   educationlevel    → Text version; education_ordinal encodes it numerically.
#   fertilityintention→ Text version; fertility_ordinal encodes it numerically.
#   counseled         → Text version; counseled_binary encodes it numerically.
#   previousmethod    → Raw text; previous_method_category encodes it cleanly.
#   methodadopted     → Raw text; current_method_category encodes it cleanly.
#   age_group         → Categorical version of age; age is more informative.
#   uniqueid          → Client identifier. Leaks identity, not behaviour.
# ────────────────────────────────────────────────────────────────────────────

# Numeric features — kept as-is, no encoding needed
NUMERIC_FEATURES = [
    "age",                        # Continuous age in years [10–60]
    "noofchildren",               # Parity (capped at 15)
    "education_ordinal",          # 1=Primary Incomplete, 2=Primary, 3=Secondary+
    "fertility_ordinal",          # 1=Within2yr, 2=Later, 3=NoMore
    "month_num",                  # 1–12 seasonal context
    "year",                       # 2013–2015 programme phase
]

# Binary flags — already 0/1 integers
BINARY_FEATURES = [
    "is_young_woman",             # age < 20 (non-linear age effect)
    "is_older_woman",             # age >= 40 (non-linear age effect)
    "has_high_parity",            # noofchildren >= 5
    "wants_child_soon",           # fertilityintention == 'Within 2 Years'
    "wants_no_more",              # fertilityintention == 'No more Children'
    "was_on_larc",                # previous method was LARC
    "adopted_larc",               # current method is LARC
    "counseled_binary",           # was client counseled? (1=Yes, 0=No)
    "fertility_intention_known",  # was fertility intention collected? (missingness signal)
    "education_known",            # was education collected? (Siaya missingness pattern)
]

# Categorical features — require label encoding before modelling
CATEGORICAL_FEATURES = [
    "county",                     # Siaya / Busia (geographic context)
    "delivery_type",              # community / facility
    "previous_method_category",   # short_acting_hormonal / long_acting_reversible / etc.
    "current_method_category",    # same categories for adopted method
    "switch_type",                # same_category / upgraded_to_larc / downgraded_from_larc / etc.
]

# Target variable
TARGET = "discontinued"

# Identifiers — never enter model, kept for audit and post-hoc analysis
IDENTIFIERS = ["uniqueid", "visitid"]

# All feature columns (before encoding)
ALL_FEATURES_RAW = NUMERIC_FEATURES + BINARY_FEATURES + CATEGORICAL_FEATURES

print(f"\nNumeric features    ({len(NUMERIC_FEATURES)}):   {NUMERIC_FEATURES}")
print(f"\nBinary features     ({len(BINARY_FEATURES)}):  {BINARY_FEATURES}")
print(f"\nCategorical features({len(CATEGORICAL_FEATURES)}):   {CATEGORICAL_FEATURES}")
print(f"\nTotal raw features:  {len(ALL_FEATURES_RAW)}")
print(f"Target:              {TARGET}")


# ── CELL 4: Validate all required columns exist ────────────────────────────────
print("\n[Validation] Checking all required columns exist in clean data...")
missing_cols = [c for c in ALL_FEATURES_RAW + [TARGET] + IDENTIFIERS
                if c not in df.columns]
if missing_cols:
    raise ValueError(
        f"These required columns are missing from the clean dataset:\n"
        f"  {missing_cols}\n"
        f"Check that Notebook 02 ran completely and added all derived columns."
    )
print("  ✅ All required columns present.")

# Confirm no NaN in numeric or binary features before encoding
nan_check = df[NUMERIC_FEATURES + BINARY_FEATURES].isna().sum()
cols_with_nan = nan_check[nan_check > 0]
if len(cols_with_nan) > 0:
    print(f"  ⚠️  NaN values found in these columns:")
    print(cols_with_nan)
    print("  Applying fallback median imputation...")
    for col in cols_with_nan.index:
        med = df[col].median()
        df[col] = df[col].fillna(med)
        print(f"    {col}: filled {cols_with_nan[col]} NaN with median={med:.1f}")
else:
    print("  ✅ No NaN values in numeric/binary features.")


# ── CELL 5: Client-level train / val / test split ─────────────────────────────
print("\n" + "=" * 55)
print("CLIENT-LEVEL TRAIN / VALIDATION / TEST SPLIT")
print("=" * 55)
print()
print("WHY CLIENT-LEVEL (not row-level):")
print("  Each client appears avg 20+ times in this dataset.")
print("  Row-level split → same client in train AND test → data leakage.")
print("  Client-level split → model sees only truly new clients at test time.")
print("  This mirrors real deployment: ChaguoAI scores new users only.")
print()

# Step 1: Get unique clients and their overall discontinuation rate
# We use the FIRST visit's discontinuation status per client for stratification.
# (Using the client's majority class would also work but is overkill here.)
client_summary = (
    df.groupby("uniqueid")
    .agg(
        n_visits=("visitid", "count"),
        disc_rate=("discontinued", "mean"),
        county=("county", "first"),
    )
    .reset_index()
)

# Create stratification label: round disc_rate to 0 or 1 for stratified split
# This ensures each split has a similar proportion of high-discontinuation clients
client_summary["disc_label"] = (client_summary["disc_rate"] >= 0.5).astype(int)

print(f"Unique clients: {len(client_summary):,}")
print(f"  Clients with disc_rate >= 0.5: {client_summary['disc_label'].sum():,}")
print(f"  Clients with disc_rate <  0.5: {(client_summary['disc_label']==0).sum():,}")

# Step 2: Split clients into temp (train+val) and test (15%)
clients_temp, clients_test = train_test_split(
    client_summary["uniqueid"],
    test_size=TEST_RATIO,
    random_state=RANDOM_SEED,
    stratify=client_summary["disc_label"],
)

# Step 3: Split temp into train (70%) and val (15%)
# val fraction of temp = 0.15 / (0.70 + 0.15) = 0.1765
val_frac_of_temp = VAL_RATIO / (TRAIN_RATIO + VAL_RATIO)

temp_labels = (
    client_summary[client_summary["uniqueid"].isin(clients_temp)]
    .set_index("uniqueid")["disc_label"]
)

clients_train, clients_val = train_test_split(
    clients_temp,
    test_size=val_frac_of_temp,
    random_state=RANDOM_SEED,
    stratify=temp_labels,
)

# Step 4: Assign split labels back to the row-level dataframe
client_split_map = {}
for uid in clients_train: client_split_map[uid] = "train"
for uid in clients_val:   client_split_map[uid] = "val"
for uid in clients_test:  client_split_map[uid] = "test"

df["split"] = df["uniqueid"].map(client_split_map)

# Step 5: Verify split
split_counts = df.groupby("split").agg(
    n_records=("visitid", "count"),
    n_clients=("uniqueid", "nunique"),
    disc_rate=("discontinued", "mean"),
).reset_index()

print(f"\nSplit results:")
print(f"  {'Split':<8} {'Records':>10} {'Clients':>9} {'Disc Rate':>10}  {'Share of records':>16}")
print(f"  {'-'*56}")
for _, row in split_counts.iterrows():
    pct = row["n_records"] / len(df) * 100
    print(f"  {row['split']:<8} {row['n_records']:>10,} {row['n_clients']:>9,} "
          f"{row['disc_rate']:>9.1%}  {pct:>14.1f}%")

# Verify no client leaks across splits
all_splits = [set(clients_train), set(clients_val), set(clients_test)]
assert len(all_splits[0] & all_splits[1]) == 0, "LEAK: same client in train and val"
assert len(all_splits[0] & all_splits[2]) == 0, "LEAK: same client in train and test"
assert len(all_splits[1] & all_splits[2]) == 0, "LEAK: same client in val and test"
print("\n  ✅ No client leakage across splits confirmed.")


# ── CELL 6: Label encoding — fit on train only ────────────────────────────────
print("\n" + "=" * 55)
print("CATEGORICAL ENCODING")
print("=" * 55)
print()
print("DESIGN RULE:")
print("  Encoders are fitted ONLY on the training set.")
print("  Then applied (transform-only) to val and test.")
print("  This prevents information from val/test contaminating")
print("  the encoding — a subtle form of data leakage.")
print()
print("  We add 'UNKNOWN' to every encoder's vocabulary so that")
print("  new categories (e.g. a new county in future data) do not")
print("  cause the model to crash at inference time.")
print()

df_train = df[df["split"] == "train"].copy()
df_val   = df[df["split"] == "val"].copy()
df_test  = df[df["split"] == "test"].copy()

encoders = {}

for col in CATEGORICAL_FEATURES:
    # Collect all unique values in train + add UNKNOWN sentinel
    train_values = df_train[col].astype(str).unique().tolist()
    all_values   = sorted(set(train_values + ["UNKNOWN"]))

    le = LabelEncoder()
    le.fit(all_values)
    encoders[col] = le

    # Transform all splits — unseen values → UNKNOWN
    for split_df, split_name in [(df_train, "train"), (df_val, "val"), (df_test, "test")]:
        col_series  = split_df[col].astype(str)
        known_vals  = set(le.classes_)
        col_mapped  = col_series.apply(lambda v: v if v in known_vals else "UNKNOWN")
        encoded_col = col + "_enc"
        split_df[encoded_col] = le.transform(col_mapped)

    # Show encoding
    n_classes = len(le.classes_)
    unseen_val = df_val[col].astype(str)
    unseen_val_test = df_test[col].astype(str)
    n_unseen_val  = unseen_val[~unseen_val.isin(set(le.classes_))].nunique()
    n_unseen_test = unseen_val_test[~unseen_val_test.isin(set(le.classes_))].nunique()

    print(f"  {col:<30}: {n_classes} classes  |  "
          f"unseen in val: {n_unseen_val}  |  unseen in test: {n_unseen_test}")
    class_map = dict(zip(le.classes_, le.transform(le.classes_)))
    print(f"    Encoding: {class_map}")


# ── CELL 7: Build final feature matrices ──────────────────────────────────────
print("\n" + "=" * 55)
print("BUILDING FINAL FEATURE MATRICES")
print("=" * 55)

# Encoded column names (replace raw categoricals with encoded versions)
ENCODED_CATEGORICAL_FEATURES = [c + "_enc" for c in CATEGORICAL_FEATURES]

# Final model feature columns — all numeric or encoded integer
FINAL_MODEL_FEATURES = NUMERIC_FEATURES + BINARY_FEATURES + ENCODED_CATEGORICAL_FEATURES

print(f"\nFinal model features ({len(FINAL_MODEL_FEATURES)}):")
for i, feat in enumerate(FINAL_MODEL_FEATURES, 1):
    print(f"  {i:2d}. {feat}")


def build_Xy(split_df: pd.DataFrame,
             feature_cols: list,
             target: str) -> tuple:
    """
    Extract X (feature matrix) and y (target series) from a split dataframe.
    Validates for NaN and correct dtypes before returning.

    Parameters
    ----------
    split_df     : dataframe for one split (train / val / test)
    feature_cols : ordered list of final model feature column names
    target       : name of the target column

    Returns
    -------
    (X, y) where X is a DataFrame and y is a Series
    """
    missing = [c for c in feature_cols if c not in split_df.columns]
    if missing:
        raise ValueError(f"Missing feature columns: {missing}")

    X = split_df[feature_cols].copy().reset_index(drop=True)
    y = split_df[target].astype(int).reset_index(drop=True)

    # Final NaN check — must be zero
    n_nan = X.isna().sum().sum()
    if n_nan > 0:
        bad_cols = X.columns[X.isna().any()].tolist()
        raise ValueError(
            f"Feature matrix has {n_nan} NaN values in: {bad_cols}\n"
            f"Fix imputation in Notebook 02 or Cell 4 of this notebook."
        )

    # Dtype check — all must be numeric
    non_numeric = X.select_dtypes(exclude=[np.number]).columns.tolist()
    if non_numeric:
        raise ValueError(
            f"Non-numeric columns in feature matrix: {non_numeric}\n"
            f"Ensure all categoricals are encoded before calling build_Xy()."
        )

    return X, y


X_train, y_train = build_Xy(df_train, FINAL_MODEL_FEATURES, TARGET)
X_val,   y_val   = build_Xy(df_val,   FINAL_MODEL_FEATURES, TARGET)
X_test,  y_test  = build_Xy(df_test,  FINAL_MODEL_FEATURES, TARGET)

print(f"\n  X_train: {X_train.shape}  |  y_train positive rate: {y_train.mean():.1%}")
print(f"  X_val:   {X_val.shape}   |  y_val   positive rate: {y_val.mean():.1%}")
print(f"  X_test:  {X_test.shape}  |  y_test  positive rate: {y_test.mean():.1%}")

# Class balance assessment
print(f"\n  Overall positive rate: {y_train.mean():.1%}")
if y_train.mean() >= 0.30:
    print("  ✅ Class balance GOOD (>30%). No SMOTE or class weighting required.")
elif y_train.mean() >= 0.15:
    print("  ⚠️  Moderate imbalance. Use class_weight='balanced' in models.")
else:
    print("  ❌ Severe imbalance (<15%). Use SMOTE on training set.")


# ── CELL 8: Save encoders and feature matrices ────────────────────────────────
print("\n" + "=" * 55)
print("SAVING OUTPUTS")
print("=" * 55)

# Save encoders — MUST be used at inference time
encoder_path = PATHS["processed_dir"] / "04_encoders.pkl"
with open(encoder_path, "wb") as f:
    pickle.dump(encoders, f)
print(f"  Encoders saved:     {encoder_path}")

# Save feature matrices as parquet (fast, type-safe, small)
for name, X, y in [
    ("train", X_train, y_train),
    ("val",   X_val,   y_val),
    ("test",  X_test,  y_test),
]:
    X_path = PATHS["processed_dir"] / f"04_X_{name}.parquet"
    y_path = PATHS["processed_dir"] / f"04_y_{name}.parquet"
    X.to_parquet(X_path, index=False, engine="pyarrow")
    y.to_frame().to_parquet(y_path, index=False, engine="pyarrow")
    print(f"  X_{name} saved: {X_path.name}  ({X.shape[0]:,} rows × {X.shape[1]} cols)")
    print(f"  y_{name} saved: {y_path.name}  ({y.sum():,} positives / {len(y):,} total)")

# Save feature list (ordered) — notebook 05 reads this to guarantee same order
feature_meta = {
    "final_model_features":       FINAL_MODEL_FEATURES,
    "numeric_features":           NUMERIC_FEATURES,
    "binary_features":            BINARY_FEATURES,
    "categorical_features_raw":   CATEGORICAL_FEATURES,
    "categorical_features_enc":   ENCODED_CATEGORICAL_FEATURES,
    "target":                     TARGET,
    "identifiers":                IDENTIFIERS,
    "n_features":                 len(FINAL_MODEL_FEATURES),
    "n_train":                    int(len(X_train)),
    "n_val":                      int(len(X_val)),
    "n_test":                     int(len(X_test)),
    "positive_rate_train":        float(round(y_train.mean(), 4)),
    "positive_rate_val":          float(round(y_val.mean(), 4)),
    "positive_rate_test":         float(round(y_test.mean(), 4)),
    "n_unique_clients_total":     int(df["uniqueid"].nunique()),
    "n_unique_clients_train":     int(df_train["uniqueid"].nunique()),
    "n_unique_clients_val":       int(df_val["uniqueid"].nunique()),
    "n_unique_clients_test":      int(df_test["uniqueid"].nunique()),
    "split_strategy":             "client_level_stratified",
    "split_ratios":               {
        "train": TRAIN_RATIO,
        "val":   VAL_RATIO,
        "test":  TEST_RATIO,
    },
    "random_seed":                RANDOM_SEED,
    "encoder_file":               "04_encoders.pkl",
    "categorical_encoding": {
        col: {str(k): int(v)
              for k, v in zip(encoders[col].classes_,
                              encoders[col].transform(encoders[col].classes_))}
        for col in CATEGORICAL_FEATURES
    },
}

meta_path = PATHS["processed_dir"] / "04_feature_meta.json"
with open(meta_path, "w") as f:
    json.dump(feature_meta, f, indent=2)
print(f"  Feature metadata:   {meta_path}")


# ── CELL 9: Per-feature statistics report ─────────────────────────────────────
print("\n" + "=" * 55)
print("PER-FEATURE STATISTICS REPORT")
print("=" * 55)

# Compute per-feature statistics on the TRAINING set
feature_report_rows = []
for feat in FINAL_MODEL_FEATURES:
    series = X_train[feat]
    n_unique = series.nunique()
    dtype    = str(series.dtype)
    feat_min = float(series.min())
    feat_max = float(series.max())
    feat_mean= float(series.mean())
    feat_std = float(series.std())
    pct_zero = float((series == 0).mean())

    # Correlation with target in training set (Spearman)
    corr = float(X_train[feat].corr(y_train, method="spearman"))

    # Feature type classification
    if feat in NUMERIC_FEATURES:
        feat_type = "numeric_continuous"
    elif feat in BINARY_FEATURES:
        feat_type = "binary_flag"
    else:
        feat_type = "categorical_encoded"

    feature_report_rows.append({
        "feature":       feat,
        "type":          feat_type,
        "n_unique":      n_unique,
        "dtype":         dtype,
        "min":           round(feat_min, 3),
        "max":           round(feat_max, 3),
        "mean":          round(feat_mean, 3),
        "std":           round(feat_std, 3),
        "pct_zero":      round(pct_zero, 3),
        "corr_with_target": round(corr, 4),
    })

feature_report = pd.DataFrame(feature_report_rows).sort_values(
    "corr_with_target", key=abs, ascending=False
)

print(f"\n  {'Feature':<35} {'Type':<22} {'Unique':>7} {'Min':>6} {'Max':>6} "
      f"{'Mean':>7} {'r_target':>9}")
print(f"  {'-'*95}")
for _, row in feature_report.iterrows():
    print(f"  {row['feature']:<35} {row['type']:<22} {row['n_unique']:>7} "
          f"{row['min']:>6.1f} {row['max']:>6.1f} {row['mean']:>7.3f} "
          f"{row['corr_with_target']:>+9.4f}")

feature_report.to_csv(PATHS["reports_dir"] / "04_feature_report.csv", index=False)
print(f"\n  Report saved: {PATHS['reports_dir'] / '04_feature_report.csv'}")


# ── CELL 10: Validation plot 1 — Split class balance ──────────────────────────
print("\n[Plot 1] Class balance verification across splits")

fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))

for ax, (name, y_split) in zip(axes, [("Train", y_train),
                                        ("Validation", y_val),
                                        ("Test (sealed)", y_test)]):
    counts = y_split.value_counts().sort_index()
    bar_colors = [PALETTE["teal"], PALETTE["coral"]]
    bars = ax.bar(["Continued\n(0)", "Discontinued\n(1)"],
                  counts.values, color=bar_colors, width=0.5)
    for bar, val in zip(bars, counts.values):
        pct = val / len(y_split) * 100
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 50,
                f"{val:,}\n({pct:.1f}%)",
                ha="center", va="bottom", fontweight="bold", fontsize=9.5)
    ax.set_title(f"{name}\n(n={len(y_split):,} records)")
    ax.set_ylabel("Records")
    ax.set_ylim(0, counts.max() * 1.25)

plt.suptitle(
    "Figure 18: Class Balance Across Splits\n"
    "(stratified by client = balanced positive rate in each split)",
    fontweight="bold"
)
plt.tight_layout()
fig_path = PATHS["figures_dir"] / "04a_split_class_balance.png"
plt.savefig(fig_path, dpi=150, bbox_inches="tight")
plt.show()
print(f"  Saved: 04a_split_class_balance.png")


# ── CELL 11: Validation plot 2 — Feature correlation with target ──────────────
print("\n[Plot 2] Feature correlation with target")

corr_df = feature_report.copy()
corr_df = corr_df.sort_values("corr_with_target")

fig, ax = plt.subplots(figsize=(10, 9))
bar_colors = [PALETTE["coral"] if r > 0 else PALETTE["teal"]
              for r in corr_df["corr_with_target"]]
bars = ax.barh(corr_df["feature"], corr_df["corr_with_target"],
               color=bar_colors, height=0.65)
for bar, (_, row) in zip(bars, corr_df.iterrows()):
    x_pos = row["corr_with_target"]
    ha = "left" if x_pos >= 0 else "right"
    offset = 0.002 if x_pos >= 0 else -0.002
    ax.text(x_pos + offset, bar.get_y() + bar.get_height() / 2,
            f"{x_pos:+.3f}", va="center", ha=ha, fontsize=8.5)
ax.axvline(0, color="black", linewidth=0.8)
ax.set_xlabel("Spearman correlation with discontinued (training set)")
ax.set_title(
    "Figure 19: Feature Correlation with Target (training set)\n"
    "Coral = positive correlation (feature increases disc risk)\n"
    "Teal  = negative correlation (feature decreases disc risk)"
)

legend_items = [
    mpatches.Patch(color=PALETTE["coral"], label="Positive correlation"),
    mpatches.Patch(color=PALETTE["teal"],  label="Negative correlation"),
]
ax.legend(handles=legend_items, loc="lower right", fontsize=9)
plt.tight_layout()
fig_path = PATHS["figures_dir"] / "04b_feature_correlation_target.png"
plt.savefig(fig_path, dpi=150, bbox_inches="tight")
plt.show()
print("  Saved: 04b_feature_correlation_target.png")

print("\n  TOP POSITIVE CORRELATIONS (increase discontinuation risk):")
top_pos = corr_df[corr_df["corr_with_target"] > 0].tail(5)[::-1]
for _, row in top_pos.iterrows():
    print(f"    {row['feature']:<38}: r = {row['corr_with_target']:+.4f}")

print("\n  TOP NEGATIVE CORRELATIONS (reduce discontinuation risk):")
top_neg = corr_df[corr_df["corr_with_target"] < 0].head(5)
for _, row in top_neg.iterrows():
    print(f"    {row['feature']:<38}: r = {row['corr_with_target']:+.4f}")


# ── CELL 12: Validation plot 3 — Feature distribution in train vs val vs test ──
print("\n[Plot 3] Feature distribution consistency across splits")
print("  (Check that train/val/test are statistically similar)")

# Plot top 6 most predictive features
top_features = feature_report.head(6)["feature"].tolist()

fig, axes = plt.subplots(2, 3, figsize=(16, 9))
axes = axes.flat

split_dfs  = {"Train": X_train, "Val": X_val, "Test": X_test}
split_cols = [PALETTE["teal"], PALETTE["coral"], PALETTE["amber"]]

for ax, feat in zip(axes, top_features):
    for (split_name, X_split), color in zip(split_dfs.items(), split_cols):
        series = X_split[feat]
        n_unique = series.nunique()

        if n_unique <= 10:
            # Categorical / binary — bar chart of proportions
            prop = series.value_counts(normalize=True).sort_index()
            x_pos = np.arange(len(prop))
            ax.bar(x_pos, prop.values * 100,
                   alpha=0.6, color=color, label=split_name, width=0.25,
                   align="center")
            ax.set_xticks(x_pos)
            ax.set_xticklabels(prop.index, fontsize=8)
            ax.set_ylabel("% of records")
        else:
            # Continuous — KDE
            series.plot.kde(ax=ax, color=color, linewidth=2,
                            label=split_name, alpha=0.8)
            ax.set_ylabel("Density")

    ax.set_title(f"{feat}", fontsize=10, fontweight="bold")
    ax.legend(fontsize=7)

plt.suptitle(
    "Figure 20: Feature Distributions Across Train / Val / Test\n"
    "(Distributions should be similar — confirms good split stratification)",
    fontweight="bold", y=1.01
)
plt.tight_layout()
fig_path = PATHS["figures_dir"] / "04c_feature_distributions_splits.png"
plt.savefig(fig_path, dpi=150, bbox_inches="tight")
plt.show()
print("  Saved: 04c_feature_distributions_splits.png")


# ── CELL 13: Validation plot 4 — Feature correlation matrix (final features) ──
print("\n[Plot 4] Final feature inter-correlation matrix (multicollinearity check)")

corr_final = X_train.corr(method="spearman")

fig, ax = plt.subplots(figsize=(14, 12))
mask = np.zeros_like(corr_final, dtype=bool)
np.fill_diagonal(mask, True)  # mask diagonal (self-correlation)

sns.heatmap(
    corr_final,
    ax=ax,
    cmap="RdBu_r",
    center=0,
    vmin=-1, vmax=1,
    annot=True,
    fmt=".2f",
    annot_kws={"size": 7},
    linewidths=0.3,
    mask=mask,
    cbar_kws={"label": "Spearman r", "shrink": 0.8},
)
ax.set_title(
    "Figure 21: Feature Inter-Correlation Matrix (Training Set)\n"
    "Values > 0.70 indicate potential multicollinearity\n"
    "Diagonal masked (self-correlation = 1.0 by definition)",
    pad=12, fontsize=11
)
plt.tight_layout()
fig_path = PATHS["figures_dir"] / "04d_feature_intercorrelation.png"
plt.savefig(fig_path, dpi=150, bbox_inches="tight")
plt.show()
print("  Saved: 04d_feature_intercorrelation.png")

# Flag high-correlation pairs
print("\n  HIGH INTER-CORRELATION PAIRS (|r| > 0.60):")
high_corr_found = False
for i in range(len(corr_final.columns)):
    for j in range(i + 1, len(corr_final.columns)):
        r = corr_final.iloc[i, j]
        if abs(r) > 0.60:
            c1 = corr_final.columns[i]
            c2 = corr_final.columns[j]
            print(f"    {c1:<35} ↔ {c2:<35} r = {r:+.3f}")
            high_corr_found = True

if not high_corr_found:
    print("    None found above 0.60 threshold. ✅")

print("\n  DESIGN NOTE: High correlation between derived flags and their")
print("  parent numeric columns (e.g. age ↔ is_young_woman) is EXPECTED")
print("  and INTENTIONAL. They capture non-linear effects that linear")
print("  models cannot detect. Tree-based models handle this naturally.")
print("  Only true multicollinearity (r > 0.90 between independent features)")
print("  would require removal.")


# ── CELL 14: Inference function — how to use encoders on new data ─────────────
print("\n" + "=" * 55)
print("INFERENCE FUNCTION")
print("=" * 55)
print("This function is what Notebook 05 and the ChaguoAI")
print("orchestrator will call to score new users at runtime.")


def load_feature_assets(processed_dir: Path) -> dict:
    """
    Load all feature engineering assets produced by this notebook.

    Returns
    -------
    dict with keys: encoders, feature_meta, FINAL_MODEL_FEATURES
    """
    enc_path  = processed_dir / "04_encoders.pkl"
    meta_path = processed_dir / "04_feature_meta.json"

    if not enc_path.exists() or not meta_path.exists():
        raise FileNotFoundError(
            "Feature assets not found. Run Notebook 04 first.\n"
            f"Expected: {enc_path}\n         {meta_path}"
        )

    with open(enc_path, "rb") as f:
        loaded_encoders = pickle.load(f)

    with open(meta_path) as f:
        loaded_meta = json.load(f)

    return {
        "encoders":             loaded_encoders,
        "feature_meta":         loaded_meta,
        "final_model_features": loaded_meta["final_model_features"],
    }


def encode_user_profile_for_inference(
    user_profile_dict: dict,
    candidate_method: str,
    previous_method: str,
    assets: dict,
) -> pd.DataFrame:
    """
    Transform a raw user profile from ChaguoAI intake into a
    model-ready feature vector for ONE candidate method.

    Called once per candidate method during recommendation ranking.

    Parameters
    ----------
    user_profile_dict : dict
        Keys match intake question outputs:
          age_years, number_of_children, education_level,
          fertility_intention, counseled, county, delivery_type,
          year, month_num
    candidate_method : str
        Method being evaluated e.g. 'Injectables', 'Implants'
    previous_method : str
        User's prior method e.g. 'Pills', 'unknown'
    assets : dict
        Output from load_feature_assets()

    Returns
    -------
    pd.DataFrame
        Single-row DataFrame with features in exact order
        expected by the model.
    """
    from config import (
        EDUCATION_ORDINAL, FERTILITY_ORDINAL, COUNSELED_BINARY,
        METHOD_CATEGORY_MAP,
    )

    enc   = assets["encoders"]
    feats = assets["final_model_features"]

    age      = int(user_profile_dict.get("age_years", 25))
    children = int(user_profile_dict.get("number_of_children", 1))
    edu_text = user_profile_dict.get("education_level", "Primary Complete")
    fert_text= user_profile_dict.get("fertility_intention", "Later than 2 years")
    cou_text = user_profile_dict.get("counseled", "Yes")
    county   = str(user_profile_dict.get("county", "UNKNOWN"))
    delivery = str(user_profile_dict.get("delivery_type", "facility"))
    year     = int(user_profile_dict.get("year", 2024))
    month_num= int(user_profile_dict.get("month_num", 6))

    prev_cat = METHOD_CATEGORY_MAP.get(previous_method, "unknown")
    curr_cat = METHOD_CATEGORY_MAP.get(candidate_method, "unknown")

    def get_switch_type(curr, prev):
        if prev in ("unknown",):             return "unknown"
        if curr == prev:                     return "same_category"
        if (prev == "long_acting_reversible"
                and curr != "long_acting_reversible"): return "downgraded_from_larc"
        if (curr == "long_acting_reversible"
                and prev != "long_acting_reversible"): return "upgraded_to_larc"
        if curr == "permanent":              return "moved_to_permanent"
        if curr == "barrier":                return "moved_to_barrier"
        return "lateral_switch"

    row = {
        # Numeric
        "age":                       age,
        "noofchildren":              min(children, 15),
        "education_ordinal":         EDUCATION_ORDINAL.get(edu_text, 2),
        "fertility_ordinal":         FERTILITY_ORDINAL.get(fert_text, 2),
        "month_num":                 month_num,
        "year":                      year,
        # Binary flags
        "is_young_woman":            int(age < 20),
        "is_older_woman":            int(age >= 40),
        "has_high_parity":           int(children >= 5),
        "wants_child_soon":          int(fert_text == "Within 2 Years"),
        "wants_no_more":             int(fert_text == "No more Children"),
        "was_on_larc":               int(prev_cat == "long_acting_reversible"),
        "adopted_larc":              int(curr_cat == "long_acting_reversible"),
        "counseled_binary":          COUNSELED_BINARY.get(cou_text, 1),
        "fertility_intention_known": 1,
        "education_known":           1,
        # Categoricals (raw — will be encoded below)
        "county":                    county,
        "delivery_type":             delivery,
        "previous_method_category":  prev_cat,
        "current_method_category":   curr_cat,
        "switch_type":               get_switch_type(curr_cat, prev_cat),
    }

    df_row = pd.DataFrame([row])

    # Encode categoricals using saved encoders
    for col in ["county", "delivery_type", "previous_method_category",
                "current_method_category", "switch_type"]:
        le  = enc.get(col)
        if le is None:
            df_row[col + "_enc"] = 0
            continue
        val = str(df_row[col].iloc[0])
        if val not in set(le.classes_):
            val = "UNKNOWN"
        df_row[col + "_enc"] = int(le.transform([val])[0])

    # Select features in the exact trained order
    available = [f for f in feats if f in df_row.columns]
    missing   = [f for f in feats if f not in df_row.columns]
    if missing:
        for m in missing:
            df_row[m] = 0  # conservative fallback for missing features

    return df_row[feats].fillna(0)


# Test the inference function with a representative user profile
assets = load_feature_assets(PATHS["processed_dir"])

test_profile = {
    "age_years":          22,
    "number_of_children": 1,
    "education_level":    "Primary Complete",
    "fertility_intention":"Later than 2 years",
    "counseled":          "Yes",
    "county":             "Siaya",
    "delivery_type":      "facility",
    "year":               2024,
    "month_num":          6,
}

print("\n  Inference test — 22yr old woman, 1 child, Siaya, previously on Injectables:")
print(f"  {'Candidate Method':<20} {'Feature vector shape':<25} {'All numeric?':>12}")
for method in ["Injectables", "Implants", "Pills", "Condoms", "IUCD", "BTL"]:
    X_inf = encode_user_profile_for_inference(
        test_profile, method, "Injectables", assets
    )
    all_num = X_inf.select_dtypes(exclude=[np.number]).shape[1] == 0
    nan_cnt = X_inf.isna().sum().sum()
    print(f"  {method:<20} {str(X_inf.shape):<25} {'✅' if all_num and nan_cnt==0 else '❌'}")

print("\n  ✅ Inference function validated. Ready for Notebook 05.")


# ── CELL 15: Final summary ────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("FEATURE ENGINEERING COMPLETE — SUMMARY")
print("=" * 65)

summary = [
    f"Final feature count:          {len(FINAL_MODEL_FEATURES)}",
    f"  Numeric continuous:         {len(NUMERIC_FEATURES)}",
    f"  Binary flags:               {len(BINARY_FEATURES)}",
    f"  Categorical (encoded):      {len(ENCODED_CATEGORICAL_FEATURES)}",
    "",
    f"Split strategy:               Client-level (by uniqueid), stratified",
    f"  Training:   {len(X_train):,} records  ({len(X_train)/len(df)*100:.0f}%)  "
    f"| {df_train['uniqueid'].nunique():,} unique clients",
    f"  Validation: {len(X_val):,} records  ({len(X_val)/len(df)*100:.0f}%)   "
    f"| {df_val['uniqueid'].nunique():,} unique clients",
    f"  Test:       {len(X_test):,} records  ({len(X_test)/len(df)*100:.0f}%)   "
    f"| {df_test['uniqueid'].nunique():,} unique clients",
    "",
    f"Target positive rate:",
    f"  Train: {y_train.mean():.1%}  |  Val: {y_val.mean():.1%}  |  Test: {y_test.mean():.1%}",
    f"  Assessment: {'Balanced — no resampling needed' if y_train.mean() > 0.30 else 'Imbalanced — use class_weight'}",
    "",
    "Strongest features (|Spearman r| with target):",
]

for _, row in feature_report.head(5).iterrows():
    summary.append(f"  {row['feature']:<38}: r = {row['corr_with_target']:+.4f}")

summary += [
    "",
    "Files saved to outputs/processed/:",
    "  04_X_train.parquet, 04_y_train.parquet",
    "  04_X_val.parquet,   04_y_val.parquet",
    "  04_X_test.parquet,  04_y_test.parquet  ← SEALED until final evaluation",
    "  04_encoders.pkl     ← MUST be used at inference time",
    "  04_feature_meta.json",
    "",
    "NEXT STEP: Run Notebook 05 — Model Training",
    "  Input: 04_X_train, 04_y_train, 04_X_val, 04_y_val",
    "  The test set is NOT opened in Notebook 05.",
    "  It is opened ONCE in Notebook 06 (Final Evaluation).",
]

for line in summary:
    print(line)

print(f"\nFigures saved to: {PATHS['figures_dir']}")
print(f"Reports saved to: {PATHS['reports_dir']}")