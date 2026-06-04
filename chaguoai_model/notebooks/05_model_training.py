"""
NOTEBOOK 05 — Model Training
==============================
Purpose : Train, tune, and select the best discontinuation
          prediction model using the training and validation
          sets produced by Notebook 04.

          The test set is NEVER opened in this notebook.
          It is reserved exclusively for Notebook 06.

What this notebook does:
  1.  Load feature matrices from Notebook 04
  2.  Baseline: dummy classifier (always predict majority class)
  3.  Train Logistic Regression (interpretable clinical baseline)
  4.  Train Random Forest (robust non-linear ensemble)
  5.  Train XGBoost (best-in-class tabular gradient boosting)
  6.  Train LightGBM (fast gradient boosting at scale)
  7.  Cross-validation comparison on training set
  8.  Validation set comparison
  9.  Optimal threshold tuning on VALIDATION set only
  10. Select best model
  11. Save trained model and all metadata
  12. Produce training diagnostic plots

WHY THESE FOUR MODELS:
  LogisticRegression — The clinical baseline. If a linear model
    performs comparably, we prefer it for its transparency and
    auditability. Coefficients map directly to odds ratios —
    a clinician can read them. Requires feature scaling.

  RandomForest — Robust ensemble. Handles mixed feature types,
    no scaling needed, native feature importance, resistant to
    outliers. Good before committing to gradient boosting.

  XGBoost — Best-in-class for tabular health data in practice.
    Handles missing values natively (though we have none),
    very accurate, fast, native feature importance. The standard
    choice in medical ML competitions and research.

  LightGBM — Faster than XGBoost on our ~55k training rows,
    comparable accuracy, excellent with categorical features.
    Included for speed and as a sanity check against XGBoost.

WHY NOT DEEP LEARNING:
  With ~55k rows and 21 features, gradient boosting consistently
  outperforms neural networks on tabular data. This is well
  established in the literature (Grinsztajn et al., 2022;
  Gorishniy et al., 2021). Adding neural network complexity
  provides no accuracy benefit here and removes interpretability.

EVALUATION METRICS:
  Primary:   AUC-ROC (model selection)
  Secondary: Average Precision (AP) — more informative when
             positive class is < 50%
  Tertiary:  Recall on discontinued class — we care more about
             catching at-risk women than about precision
  NOT USED:  Accuracy — misleading for even mildly imbalanced
             classes. A model that always predicts 0 gets 58.4%
             accuracy but is clinically useless.

Outputs:
  outputs/models/05_best_model.pkl           — trained best model
  outputs/models/05_best_model_metadata.json — model card
  outputs/reports/05_cv_results.csv          — CV comparison table
  outputs/reports/05_val_results.csv         — val set comparison
  outputs/figures/05_*.png                   — training charts
"""

# ── CELL 1: Imports ────────────────────────────────────────────────────────────
import sys, warnings, json, pickle
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns

from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_validate
from sklearn.metrics import (
    roc_auc_score, average_precision_score,
    precision_recall_curve, RocCurveDisplay,
    classification_report, confusion_matrix,
    ConfusionMatrixDisplay,
)
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

import xgboost as xgb
import lightgbm as lgb

warnings.filterwarnings("ignore")
pd.set_option("display.max_columns", 50)
pd.set_option("display.width", 120)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config import (
    get_paths, PALETTE, PLOT_STYLE,
    RANDOM_SEED, MIN_AUC_ROC, MIN_RECALL,
)

PATHS = get_paths()
MODELS_DIR = PATHS["outputs_dir"] / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

plt.rcParams.update(PLOT_STYLE)

print("Notebook 05: Model Training")
print("=" * 55)
print(f"Random seed:   {RANDOM_SEED}")
print(f"Min AUC-ROC:   {MIN_AUC_ROC}")
print(f"Min Recall:    {MIN_RECALL}")


# ── CELL 2: Load feature matrices ─────────────────────────────────────────────
def load_split(processed_dir: Path, split_name: str) -> tuple:
    """
    Load X and y for one split (train / val / test).
    Returns (X: DataFrame, y: Series).
    """
    X_path = processed_dir / f"04_X_{split_name}.parquet"
    y_path = processed_dir / f"04_y_{split_name}.parquet"

    if not X_path.exists():
        raise FileNotFoundError(
            f"Feature matrix not found: {X_path}\n"
            f"Run Notebook 04 first."
        )

    X = pd.read_parquet(X_path)
    y = pd.read_parquet(y_path).squeeze()

    print(f"  Loaded {split_name}: X={X.shape}  |  "
          f"y positive rate={y.mean():.1%}  |  "
          f"positives={y.sum():,}")
    return X, y


print("Loading feature matrices...")
X_train, y_train = load_split(PATHS["processed_dir"], "train")
X_val,   y_val   = load_split(PATHS["processed_dir"], "val")

# Load feature metadata
meta_path = PATHS["processed_dir"] / "04_feature_meta.json"
with open(meta_path) as f:
    feature_meta = json.load(f)

FEATURE_NAMES = feature_meta["final_model_features"]

print(f"\n  Training features:  {len(FEATURE_NAMES)}")
print(f"  Feature names: {FEATURE_NAMES}")

# ── CELL 3: Class balance decision ────────────────────────────────────────────
print("\n" + "=" * 55)
print("CLASS BALANCE DECISION")
print("=" * 55)

pos_rate = y_train.mean()
print(f"\n  Training positive rate: {pos_rate:.1%}")

if pos_rate >= 0.30:
    BALANCE_STRATEGY = "none"
    CLASS_WEIGHT     = None
    print("  Assessment: GOOD balance (>30%).")
    print("  Decision:   No resampling. class_weight=None for all models.")
elif pos_rate >= 0.15:
    BALANCE_STRATEGY = "class_weight"
    CLASS_WEIGHT     = "balanced"
    print("  Assessment: Moderate imbalance.")
    print("  Decision:   Use class_weight='balanced' for all models.")
else:
    BALANCE_STRATEGY = "smote"
    CLASS_WEIGHT     = "balanced"
    print("  Assessment: Severe imbalance (<15%).")
    print("  Decision:   Apply SMOTE to training set.")

print(f"\n  Strategy applied: {BALANCE_STRATEGY}")

# Apply SMOTE only if needed
X_train_fit = X_train.copy()
y_train_fit = y_train.copy()

if BALANCE_STRATEGY == "smote":
    from imblearn.over_sampling import SMOTE
    smote = SMOTE(random_state=RANDOM_SEED, k_neighbors=5)
    X_train_fit, y_train_fit = smote.fit_resample(X_train, y_train)
    print(f"  After SMOTE: {len(X_train_fit):,} rows | "
          f"positive rate: {y_train_fit.mean():.1%}")


# ── CELL 4: Cross-validation setup ────────────────────────────────────────────
CV = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_SEED)

print("\n" + "=" * 55)
print("CROSS-VALIDATION SETUP")
print("=" * 55)
print(f"  Folds:    5-fold Stratified K-Fold")
print(f"  Metric:   AUC-ROC and Average Precision")
print(f"  Applied to training set only")
print(f"  Validation set is separate — used for final model selection")


# ── CELL 5: Define candidate models ───────────────────────────────────────────
print("\n" + "=" * 55)
print("CANDIDATE MODELS")
print("=" * 55)

# Logistic Regression needs scaling — we wrap it in a Pipeline
# so the scaler is re-fitted on each CV fold correctly
lr_pipeline = Pipeline([
    ("scaler", StandardScaler()),
    ("model",  LogisticRegression(
        class_weight=CLASS_WEIGHT,
        max_iter=1000,
        random_state=RANDOM_SEED,
        solver="lbfgs",
        C=1.0,
    )),
])

candidate_models = {
    "dummy_majority": DummyClassifier(
        strategy="most_frequent", random_state=RANDOM_SEED
    ),
    "logistic_regression": lr_pipeline,
    "random_forest": RandomForestClassifier(
        n_estimators=300,
        max_depth=8,
        min_samples_leaf=5,
        max_features="sqrt",
        class_weight=CLASS_WEIGHT,
        random_state=RANDOM_SEED,
        n_jobs=-1,
    ),
    "xgboost": xgb.XGBClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        gamma=0.1,
        eval_metric="logloss",
        random_state=RANDOM_SEED,
        n_jobs=-1,
        verbosity=0,
    ),
    "lightgbm": lgb.LGBMClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.05,
        num_leaves=31,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_samples=10,
        class_weight=CLASS_WEIGHT,
        random_state=RANDOM_SEED,
        n_jobs=-1,
        verbose=-1,
    ),
}

for name in candidate_models:
    print(f"  {name}")


# ── CELL 6: Cross-validation comparison ───────────────────────────────────────
print("\n" + "=" * 55)
print("CROSS-VALIDATION COMPARISON (5-fold, training set only)")
print("=" * 55)
print()
print(f"  {'Model':<25} {'CV AUC':>10} {'±Std':>8} {'CV AP':>10} {'±Std':>8}")
print(f"  {'-'*65}")

cv_results_rows = []

for name, model in candidate_models.items():
    cv_scores = cross_validate(
        model, X_train_fit, y_train_fit,
        cv=CV,
        scoring={"auc_roc": "roc_auc", "avg_precision": "average_precision"},
        n_jobs=-1,
        return_train_score=False,
    )

    mean_auc = cv_scores["test_auc_roc"].mean()
    std_auc  = cv_scores["test_auc_roc"].std()
    mean_ap  = cv_scores["test_avg_precision"].mean()
    std_ap   = cv_scores["test_avg_precision"].std()

    cv_results_rows.append({
        "model":    name,
        "cv_auc_mean":   round(mean_auc, 4),
        "cv_auc_std":    round(std_auc, 4),
        "cv_ap_mean":    round(mean_ap, 4),
        "cv_ap_std":     round(std_ap, 4),
    })

    flag = "✅" if mean_auc >= MIN_AUC_ROC else "❌"
    print(f"  {flag} {name:<25} {mean_auc:>10.4f} {std_auc:>8.4f} "
          f"{mean_ap:>10.4f} {std_ap:>8.4f}")

cv_results_df = pd.DataFrame(cv_results_rows)
cv_results_df.to_csv(PATHS["reports_dir"] / "05_cv_results.csv", index=False)
print(f"\n  CV results saved: {PATHS['reports_dir'] / '05_cv_results.csv'}")


# ── CELL 7: Train on full training set and evaluate on validation ─────────────
print("\n" + "=" * 55)
print("VALIDATION SET COMPARISON")
print("  (All models trained on full training set)")
print("=" * 55)
print()
print(f"  {'Model':<25} {'Val AUC':>10} {'Val AP':>10} {'Val Recall':>12}")
print(f"  {'-'*60}")

val_results_rows = []
trained_models   = {}

# Default threshold for recall computation
DEFAULT_THRESHOLD = 0.50

for name, model in candidate_models.items():
    # Train on full training set
    model.fit(X_train_fit, y_train_fit)
    trained_models[name] = model

    # Predict on validation set
    y_val_prob = model.predict_proba(X_val)[:, 1]
    y_val_pred = (y_val_prob >= DEFAULT_THRESHOLD).astype(int)

    val_auc    = roc_auc_score(y_val, y_val_prob)
    val_ap     = average_precision_score(y_val, y_val_prob)

    cm = confusion_matrix(y_val, y_val_pred)
    if cm.shape == (2, 2):
        tn, fp, fn, tp = cm.ravel()
        val_recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    else:
        val_recall = 0.0

    val_results_rows.append({
        "model":          name,
        "val_auc":        round(val_auc, 4),
        "val_ap":         round(val_ap, 4),
        "val_recall":     round(val_recall, 4),
    })

    flag = "✅" if val_auc >= MIN_AUC_ROC else "❌"
    print(f"  {flag} {name:<25} {val_auc:>10.4f} {val_ap:>10.4f} {val_recall:>12.4f}")

val_results_df = pd.DataFrame(val_results_rows)
val_results_df.to_csv(PATHS["reports_dir"] / "05_val_results.csv", index=False)
print(f"\n  Validation results saved: {PATHS['reports_dir'] / '05_val_results.csv'}")


# ── CELL 8: Select best model ──────────────────────────────────────────────────
print("\n" + "=" * 55)
print("MODEL SELECTION")
print("=" * 55)

# Exclude the dummy classifier from selection
eligible = val_results_df[val_results_df["model"] != "dummy_majority"]
best_row  = eligible.loc[eligible["val_auc"].idxmax()]
BEST_NAME = best_row["model"]
best_model = trained_models[BEST_NAME]

print(f"\n  Best model:       {BEST_NAME}")
print(f"  Validation AUC:   {best_row['val_auc']:.4f}")
print(f"  Validation AP:    {best_row['val_ap']:.4f}")
print(f"  Validation Recall:{best_row['val_recall']:.4f}")

# Compare against dummy baseline
dummy_row = val_results_df[val_results_df["model"] == "dummy_majority"]
if not dummy_row.empty:
    dummy_auc = dummy_row["val_auc"].values[0]
    lift = best_row["val_auc"] - dummy_auc
    print(f"\n  Dummy baseline AUC: {dummy_auc:.4f}")
    print(f"  Lift over dummy:    +{lift:.4f}")
    if lift > 0.05:
        print("  ✅ Model provides meaningful lift over baseline.")
    else:
        print("  ⚠️  Lift is small. Review features and data quality.")


# ── CELL 9: Threshold optimisation on VALIDATION set ─────────────────────────
print("\n" + "=" * 55)
print("THRESHOLD OPTIMISATION")
print("=" * 55)
print()
print("  The default 0.50 threshold is almost never optimal.")
print("  We find the threshold that maximises F1 on the VALIDATION set.")
print("  This threshold is then applied at test time and at inference.")
print("  It is NEVER tuned using test set performance.")
print()

y_val_prob_best = best_model.predict_proba(X_val)[:, 1]
precisions, recalls, thresholds = precision_recall_curve(y_val, y_val_prob_best)

# F1 score at each threshold
f1_scores = np.where(
    (precisions[:-1] + recalls[:-1]) > 0,
    2 * precisions[:-1] * recalls[:-1] / (precisions[:-1] + recalls[:-1]),
    0.0,
)

best_thresh_idx  = int(np.argmax(f1_scores))
OPTIMAL_THRESHOLD = float(thresholds[best_thresh_idx])
opt_precision     = float(precisions[best_thresh_idx])
opt_recall        = float(recalls[best_thresh_idx])
opt_f1            = float(f1_scores[best_thresh_idx])

print(f"  Optimal threshold: {OPTIMAL_THRESHOLD:.4f}  "
      f"(default was {DEFAULT_THRESHOLD:.2f})")
print(f"  At optimal threshold:")
print(f"    Precision: {opt_precision:.4f}")
print(f"    Recall:    {opt_recall:.4f}")
print(f"    F1:        {opt_f1:.4f}")

if opt_recall < MIN_RECALL:
    print(f"\n  ⚠️  Recall {opt_recall:.4f} is below minimum {MIN_RECALL}.")
    print("  Consider lowering threshold further if recall is more important")
    print("  than precision in your deployment context.")
    print()
    # Find threshold that achieves MIN_RECALL
    recall_idx = np.searchsorted(recalls[::-1], MIN_RECALL)
    if recall_idx < len(thresholds):
        min_recall_thresh = thresholds[-(recall_idx + 1)]
        min_recall_prec   = precisions[-(recall_idx + 1)]
        print(f"  To achieve recall={MIN_RECALL:.0%}:")
        print(f"    Threshold: {min_recall_thresh:.4f}")
        print(f"    Precision at that threshold: {min_recall_prec:.4f}")
else:
    print(f"\n  ✅ Recall {opt_recall:.4f} meets minimum {MIN_RECALL}.")


# ── CELL 10: Plot 1 — CV comparison ───────────────────────────────────────────
print("\n[Plot 1] Cross-validation AUC comparison")

# Merge cv and val results
compare_df = pd.merge(cv_results_df, val_results_df, on="model")
compare_df = compare_df[compare_df["model"] != "dummy_majority"]

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Left: CV AUC with error bars
ax = axes[0]
bar_colors = [PALETTE["coral"] if n == BEST_NAME else PALETTE["teal"]
              for n in compare_df["model"]]
bars = ax.barh(compare_df["model"], compare_df["cv_auc_mean"],
               xerr=compare_df["cv_auc_std"],
               color=bar_colors, height=0.5, capsize=4,
               error_kw={"linewidth": 2})
ax.axvline(MIN_AUC_ROC, color=PALETTE["red"], linestyle="--",
           linewidth=1.5, label=f"Min acceptable: {MIN_AUC_ROC}")
ax.axvline(0.50, color=PALETTE["gray"], linestyle=":", linewidth=1,
           label="Random baseline: 0.50")
for bar, (_, row) in zip(bars, compare_df.iterrows()):
    ax.text(bar.get_width() + row["cv_auc_std"] + 0.003,
            bar.get_y() + bar.get_height() / 2,
            f"{row['cv_auc_mean']:.4f}", va="center", fontsize=9)
ax.set_title("Cross-Validation AUC-ROC (5-fold)\n± standard deviation")
ax.set_xlabel("AUC-ROC")
ax.set_xlim(0.40, 1.02)
ax.legend(fontsize=8)

# Right: Validation AUC vs AP
ax = axes[1]
x_pos = np.arange(len(compare_df))
width = 0.35
bars1 = ax.bar(x_pos - width / 2, compare_df["val_auc"],
               width=width, color=PALETTE["teal"], label="Val AUC-ROC")
bars2 = ax.bar(x_pos + width / 2, compare_df["val_ap"],
               width=width, color=PALETTE["coral"], label="Val Avg Precision")
for bars, col in [(bars1, "val_auc"), (bars2, "val_ap")]:
    for bar, (_, row) in zip(bars, compare_df.iterrows()):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.005,
                f"{row[col]:.3f}", ha="center", va="bottom", fontsize=8)
ax.set_xticks(x_pos)
ax.set_xticklabels([n.replace("_", "\n") for n in compare_df["model"]], fontsize=8)
ax.set_title("Validation Set AUC-ROC vs Average Precision")
ax.set_ylabel("Score")
ax.axhline(MIN_AUC_ROC, color=PALETTE["red"], linestyle="--",
           linewidth=1.5, label=f"Min AUC: {MIN_AUC_ROC}")
ax.set_ylim(0, 1.08)
ax.legend(fontsize=8)

plt.suptitle(
    f"Figure 22: Model Comparison\n"
    f"Best model: {BEST_NAME} (highlighted in coral)",
    fontweight="bold"
)
plt.tight_layout()
plt.savefig(PATHS["figures_dir"] / "05a_model_comparison.png",
            dpi=150, bbox_inches="tight")
plt.show()
print("  Saved: 05a_model_comparison.png")


# ── CELL 11: Plot 2 — ROC and PR curves for all models on validation ──────────
print("\n[Plot 2] ROC and PR curves on validation set")

fig, axes = plt.subplots(1, 2, figsize=(14, 6))

model_colors = {
    "logistic_regression": PALETTE["sage"],
    "random_forest":       PALETTE["amber"],
    "xgboost":             PALETTE["coral"],
    "lightgbm":            PALETTE["purple"],
}

# ROC curves
ax = axes[0]
for name, model in trained_models.items():
    if name == "dummy_majority":
        continue
    y_prob = model.predict_proba(X_val)[:, 1]
    auc    = roc_auc_score(y_val, y_prob)
    color  = model_colors.get(name, PALETTE["gray"])
    lw     = 3 if name == BEST_NAME else 1.5
    ls     = "-" if name == BEST_NAME else "--"
    label  = f"{name} (AUC={auc:.3f})"
    if name == BEST_NAME:
        label = f"★ {label}"
    RocCurveDisplay.from_predictions(
        y_val, y_prob, ax=ax, name=label,
        color=color, lw=lw, linestyle=ls,
    )
ax.plot([0, 1], [0, 1], "k:", linewidth=1, label="Random (0.50)")
ax.set_title("Figure 23a: ROC Curve — Validation Set")
ax.legend(fontsize=8, loc="lower right")

# PR curves
ax = axes[1]
for name, model in trained_models.items():
    if name == "dummy_majority":
        continue
    y_prob  = model.predict_proba(X_val)[:, 1]
    ap      = average_precision_score(y_val, y_prob)
    prec, rec, _ = precision_recall_curve(y_val, y_prob)
    color   = model_colors.get(name, PALETTE["gray"])
    lw      = 3 if name == BEST_NAME else 1.5
    ls      = "-" if name == BEST_NAME else "--"
    label   = f"{name} (AP={ap:.3f})"
    if name == BEST_NAME:
        label = f"★ {label}"
    ax.plot(rec, prec, color=color, lw=lw, linestyle=ls, label=label)

baseline = y_val.mean()
ax.axhline(baseline, color="black", linestyle=":", linewidth=1,
           label=f"No-skill baseline ({baseline:.2f})")
ax.set_xlabel("Recall")
ax.set_ylabel("Precision")
ax.set_title("Figure 23b: Precision-Recall Curve — Validation Set")
ax.legend(fontsize=8, loc="upper right")
ax.set_xlim(0, 1)
ax.set_ylim(0, 1.05)

plt.suptitle("Figure 23: ROC and PR Curves (Validation Set)", fontweight="bold")
plt.tight_layout()
plt.savefig(PATHS["figures_dir"] / "05b_roc_pr_curves.png",
            dpi=150, bbox_inches="tight")
plt.show()
print("  Saved: 05b_roc_pr_curves.png")


# ── CELL 12: Plot 3 — Threshold analysis ──────────────────────────────────────
print("\n[Plot 3] Threshold optimisation curve")

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# F1, Precision, Recall vs threshold
ax = axes[0]
ax.plot(thresholds, f1_scores, color=PALETTE["teal"],
        linewidth=2, label="F1 Score")
ax.plot(thresholds, precisions[:-1], color=PALETTE["coral"],
        linewidth=2, label="Precision")
ax.plot(thresholds, recalls[:-1], color=PALETTE["amber"],
        linewidth=2, label="Recall")
ax.axvline(OPTIMAL_THRESHOLD, color=PALETTE["red"], linestyle="--",
           linewidth=2, label=f"Optimal: {OPTIMAL_THRESHOLD:.3f}")
ax.axvline(0.50, color=PALETTE["gray"], linestyle=":",
           linewidth=1.5, label="Default: 0.50")
ax.set_xlabel("Decision threshold")
ax.set_ylabel("Score")
ax.set_title(
    f"Figure 24a: Precision / Recall / F1 vs Threshold\n"
    f"Optimal threshold: {OPTIMAL_THRESHOLD:.3f}  "
    f"(F1={opt_f1:.3f}, P={opt_precision:.3f}, R={opt_recall:.3f})"
)
ax.legend(fontsize=9)
ax.set_xlim(0, 1)
ax.set_ylim(0, 1.05)

# Score distribution — how well separated are the probabilities?
ax = axes[1]
ax.hist(y_val_prob_best[y_val == 0], bins=40, alpha=0.6,
        color=PALETTE["teal"], label="Continued (y=0)", density=True)
ax.hist(y_val_prob_best[y_val == 1], bins=40, alpha=0.6,
        color=PALETTE["coral"], label="Discontinued (y=1)", density=True)
ax.axvline(OPTIMAL_THRESHOLD, color=PALETTE["red"], linestyle="--",
           linewidth=2, label=f"Threshold: {OPTIMAL_THRESHOLD:.3f}")
ax.set_xlabel("Predicted probability of discontinuation")
ax.set_ylabel("Density")
ax.set_title(
    "Figure 24b: Predicted Probability Distribution\n"
    "(Good separation = well-calibrated model)"
)
ax.legend(fontsize=9)

plt.suptitle("Figure 24: Threshold Analysis", fontweight="bold")
plt.tight_layout()
plt.savefig(PATHS["figures_dir"] / "05c_threshold_analysis.png",
            dpi=150, bbox_inches="tight")
plt.show()
print("  Saved: 05c_threshold_analysis.png")


# ── CELL 13: Plot 4 — Feature importance ──────────────────────────────────────
print("\n[Plot 4] Feature importance of best model")

fig, ax = plt.subplots(figsize=(11, 8))

if hasattr(best_model, "feature_importances_"):
    # Tree-based model: native feature importance
    imp_series = pd.Series(
        best_model.feature_importances_,
        index=FEATURE_NAMES
    ).sort_values(ascending=True)
    title_note = "(Mean Decrease in Impurity)"
    bar_color  = PALETTE["teal"]

elif hasattr(best_model, "named_steps"):
    # Pipeline (LogisticRegression): use absolute coefficients
    coefs = best_model.named_steps["model"].coef_[0]
    imp_series = pd.Series(
        np.abs(coefs), index=FEATURE_NAMES
    ).sort_values(ascending=True)
    title_note = "(Absolute coefficient |β|)"
    bar_color  = PALETTE["coral"]
else:
    print("  Model does not expose feature importances.")
    imp_series = None

if imp_series is not None:
    bars = ax.barh(imp_series.index, imp_series.values,
                   color=bar_color, height=0.7)
    # Add value labels
    for bar, val in zip(bars, imp_series.values):
        ax.text(bar.get_width() + imp_series.max() * 0.01,
                bar.get_y() + bar.get_height() / 2,
                f"{val:.4f}", va="center", fontsize=8.5)
    ax.set_xlabel("Importance score")
    ax.set_title(
        f"Figure 25: Feature Importance — {BEST_NAME}\n"
        f"{title_note}\n"
        f"(Training set — tells us which features drive predictions)"
    )
    # Highlight top 5
    top5 = imp_series.tail(5).index
    for label in ax.get_yticklabels():
        if label.get_text() in top5:
            label.set_fontweight("bold")
            label.set_color(PALETTE["red"])

plt.tight_layout()
plt.savefig(PATHS["figures_dir"] / "05d_feature_importance.png",
            dpi=150, bbox_inches="tight")
plt.show()
print("  Saved: 05d_feature_importance.png")

if imp_series is not None:
    print("\n  Top 5 most important features:")
    for feat, val in imp_series.tail(5)[::-1].items():
        print(f"    {feat:<38}: {val:.5f}")
    print("\n  Bottom 5 least important features:")
    for feat, val in imp_series.head(5).items():
        print(f"    {feat:<38}: {val:.5f}")


# ── CELL 14: Validation confusion matrix ──────────────────────────────────────
print("\n[Plot 5] Confusion matrix on validation set at optimal threshold")

y_val_pred_opt = (y_val_prob_best >= OPTIMAL_THRESHOLD).astype(int)
cm_val = confusion_matrix(y_val, y_val_pred_opt)

fig, axes = plt.subplots(1, 2, figsize=(13, 5))

# Confusion matrix
ax = axes[0]
ConfusionMatrixDisplay(
    cm_val, display_labels=["Continued", "Discontinued"]
).plot(ax=ax, cmap="Blues", colorbar=False)
ax.set_title(
    f"Figure 26a: Confusion Matrix (Validation)\n"
    f"Threshold = {OPTIMAL_THRESHOLD:.3f}"
)

# Per-class metrics table
ax = axes[1]
ax.axis("off")
report = classification_report(
    y_val, y_val_pred_opt,
    target_names=["Continued", "Discontinued"],
    output_dict=True,
)
table_data = []
for class_name in ["Continued", "Discontinued", "macro avg"]:
    d = report[class_name]
    table_data.append([
        class_name,
        f"{d['precision']:.3f}",
        f"{d['recall']:.3f}",
        f"{d['f1-score']:.3f}",
        f"{d.get('support', '—'):,.0f}" if isinstance(d.get("support"), (int, float)) else "—",
    ])
table = ax.table(
    cellText=table_data,
    colLabels=["Class", "Precision", "Recall", "F1", "Support"],
    loc="center",
    cellLoc="center",
)
table.auto_set_font_size(False)
table.set_fontsize(10)
table.scale(1.2, 2.0)
# Header row styling
for j in range(5):
    table[0, j].set_facecolor(PALETTE["navy"])
    table[0, j].set_text_props(color="white", fontweight="bold")
# Highlight the discontinued row
for j in range(5):
    table[2, j].set_facecolor("#FFF3E0")
ax.set_title(
    f"Figure 26b: Classification Report\n"
    f"(Validation set, threshold={OPTIMAL_THRESHOLD:.3f})"
)

plt.suptitle("Figure 26: Validation Set Evaluation", fontweight="bold")
plt.tight_layout()
plt.savefig(PATHS["figures_dir"] / "05e_confusion_matrix.png",
            dpi=150, bbox_inches="tight")
plt.show()
print("  Saved: 05e_confusion_matrix.png")

# Metrics at optimal threshold
tn, fp, fn, tp = cm_val.ravel()
val_prec_opt = tp / (tp + fp) if (tp + fp) > 0 else 0.0
val_rec_opt  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
val_f1_opt   = (2 * val_prec_opt * val_rec_opt /
                (val_prec_opt + val_rec_opt)
                if (val_prec_opt + val_rec_opt) > 0 else 0.0)

print(f"\n  Validation metrics at threshold={OPTIMAL_THRESHOLD:.3f}:")
print(f"    True  Negatives:  {tn:,}")
print(f"    False Positives:  {fp:,}")
print(f"    False Negatives:  {fn:,}  ← women at risk we missed")
print(f"    True  Positives:  {tp:,}  ← at-risk women correctly identified")
print(f"    Precision:        {val_prec_opt:.4f}")
print(f"    Recall:           {val_rec_opt:.4f}")
print(f"    F1 Score:         {val_f1_opt:.4f}")


# ── CELL 15: Save best model and model card ────────────────────────────────────
print("\n" + "=" * 55)
print("SAVING BEST MODEL")
print("=" * 55)

timestamp = datetime.now().strftime("%Y%m%d_%H%M")

model_path = MODELS_DIR / f"05_best_model_{BEST_NAME}_{timestamp}.pkl"
with open(model_path, "wb") as f:
    pickle.dump(best_model, f)
print(f"  Model saved:    {model_path}")

# Also save as the canonical 'best model' file for Notebook 06
canonical_path = MODELS_DIR / "05_best_model.pkl"
with open(canonical_path, "wb") as f:
    pickle.dump(best_model, f)
print(f"  Canonical copy: {canonical_path}")

# Model card
model_metadata = {
    "model_name":               BEST_NAME,
    "model_version":            timestamp,
    "trained_at":               datetime.now().isoformat(),
    "framework":                "scikit-learn / xgboost / lightgbm",

    "training_data": {
        "primary_source":       "Client_Service_Statistics.csv",
        "geography":            "Siaya and Busia counties, Western Kenya",
        "time_period":          "2013–2015",
        "n_train_records":      int(len(X_train)),
        "n_val_records":        int(len(X_val)),
        "positive_rate_train":  float(round(y_train.mean(), 4)),
        "positive_rate_val":    float(round(y_val.mean(), 4)),
        "population":           "Female FP revisit clients aged 10–60",
        "split_strategy":       "client-level stratified 70/15/15",
    },

    "features": {
        "n_features":           len(FEATURE_NAMES),
        "feature_names":        FEATURE_NAMES,
        "feature_meta_file":    "04_feature_meta.json",
        "encoder_file":         "04_encoders.pkl",
    },

    "validation_performance": {
        "auc_roc":              float(round(roc_auc_score(y_val, y_val_prob_best), 4)),
        "average_precision":    float(round(average_precision_score(y_val, y_val_prob_best), 4)),
        "optimal_threshold":    float(round(OPTIMAL_THRESHOLD, 4)),
        "precision_at_threshold": float(round(val_prec_opt, 4)),
        "recall_at_threshold":  float(round(val_rec_opt, 4)),
        "f1_at_threshold":      float(round(val_f1_opt, 4)),
        "true_positives":       int(tp),
        "false_negatives":      int(fn),
        "true_negatives":       int(tn),
        "false_positives":      int(fp),
    },

    "all_models_val_auc": {
        row["model"]: row["val_auc"]
        for _, row in val_results_df.iterrows()
    },

    "class_balance_strategy":   BALANCE_STRATEGY,
    "cv_folds":                 5,

    "target_variable": {
        "name":     "discontinued",
        "meaning_1":"Client switched or stopped contraceptive method at revisit",
        "meaning_0":"Client continued same contraceptive method at revisit",
    },

    "intended_use": (
        "Rank candidate contraceptive methods by predicted adherence "
        "probability for a specific woman's profile. A high predicted "
        "discontinuation probability for a method means the model expects "
        "this woman is less likely to continue that method. Use the inverse "
        "(1 - probability) as the adherence score for ranking. MUST be "
        "combined with WHO MEC safety filter — never used standalone."
    ),

    "known_limitations": [
        "Trained on 2 counties in Western Kenya (Siaya, Busia) 2013-2015.",
        "Does not capture women who stopped and never returned to a clinic.",
        "No attitudinal features (partner support, side-effect history) in CSS.",
        "Temporal drift: 2013-2015 method mix may differ from current programmes.",
        "Disaggregated performance by age group and method should be validated "
        "locally before deployment in a new geography.",
    ],

    "test_set_status": "SEALED — opened only in Notebook 06 (Final Evaluation)",
    "model_file":      str(canonical_path),
}

meta_path = MODELS_DIR / "05_best_model_metadata.json"
with open(meta_path, "w") as f:
    json.dump(model_metadata, f, indent=2, default=str)
print(f"  Metadata saved: {meta_path}")


# ── CELL 16: Final summary ─────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("MODEL TRAINING COMPLETE — SUMMARY")
print("=" * 65)

print(f"\n  Models compared:       {list(candidate_models.keys())}")
print(f"  Best model:            {BEST_NAME}")
print(f"  Val AUC-ROC:           {model_metadata['validation_performance']['auc_roc']:.4f}")
print(f"  Val Average Precision: {model_metadata['validation_performance']['average_precision']:.4f}")
print(f"  Optimal threshold:     {OPTIMAL_THRESHOLD:.4f}")
print(f"  Val Recall:            {val_rec_opt:.4f}  "
      f"{'✅' if val_rec_opt >= MIN_RECALL else '❌ Below minimum'}")
print(f"\n  Class balance:         {BALANCE_STRATEGY}")
print(f"  Test set:              SEALED — not opened in this notebook")
print(f"\n  Files saved:")
print(f"    {canonical_path}")
print(f"    {meta_path}")
print(f"\nNEXT STEP: Run Notebook 06 — Final Evaluation")
print("  The test set will be opened ONCE for final reported numbers.")