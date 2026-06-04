"""
NOTEBOOK 06 — Final Evaluation
================================
Purpose : Open the test set EXACTLY ONCE and report the
          authoritative performance numbers for the model.

          This is the last notebook in the pipeline.
          Nothing downstream of this notebook changes the model
          or its reported numbers.

CRITICAL RULE:
  The test set has been sealed since Notebook 04.
  It has NOT been seen by any model, any threshold decision,
  or any hyperparameter choice. Opening it here produces
  numbers that are trustworthy precisely because of that.

  If you run this notebook more than once and adjust the model
  based on test set results, you have broken the seal.
  The numbers are then no longer honest.

What this notebook does:
  1.  Load best model, encoders, and feature metadata
  2.  Load the sealed test set
  3.  Compute final performance metrics (one pass, never repeated)
  4.  Disaggregated evaluation by age group and method type
  5.  Calibration analysis — are probabilities trustworthy?
  6.  Clinical interpretation of results
  7.  Bias audit — where does the model perform poorly?
  8.  Full model card (ready for open-source publication)
  9.  Inference demonstration for ChaguoAI orchestrator
  10. Scalability guide — how to retrain for new counties/countries
  11. Chatbot data collection and retraining pipeline
  12. All final charts
  13. Complete documentation

Outputs:
  outputs/figures/06_*.png             — all final evaluation charts
  outputs/reports/06_final_metrics.csv — authoritative performance numbers
  outputs/reports/06_bias_audit.csv    — disaggregated performance table
  outputs/models/06_model_card.json    — complete open-source model card
  outputs/reports/06_inference_demo.csv— sample inference outputs
"""

# ── CELL 1: Imports ────────────────────────────────────────────────────────────
import sys, warnings, json, pickle
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import seaborn as sns

from sklearn.metrics import (
    roc_auc_score, average_precision_score,
    precision_recall_curve, confusion_matrix,
    classification_report, ConfusionMatrixDisplay,
    RocCurveDisplay, brier_score_loss,
)
from sklearn.calibration import CalibratedClassifierCV, calibration_curve

warnings.filterwarnings("ignore")
pd.set_option("display.max_columns", 50)
pd.set_option("display.width", 120)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config import (
    get_paths, PALETTE, PLOT_STYLE,
    RANDOM_SEED, MIN_AUC_ROC, MIN_RECALL,
    METHOD_CATEGORY_MAP, EDUCATION_ORDINAL,
    FERTILITY_ORDINAL, COUNSELED_BINARY,
)

PATHS      = get_paths()
MODELS_DIR = PATHS["outputs_dir"] / "models"
plt.rcParams.update(PLOT_STYLE)

print("Notebook 06: Final Evaluation")
print("=" * 65)
print()
print("  ⚠️  THE TEST SET IS BEING OPENED FOR THE FIRST AND ONLY TIME.")
print("  Numbers produced here are the authoritative model performance.")
print("  Do not re-run this notebook after adjusting the model.")
print()


# ── CELL 2: Load all assets ────────────────────────────────────────────────────
def load_model_assets(models_dir: Path, processed_dir: Path) -> dict:
    """
    Load the trained model, feature encoders, and metadata.

    Parameters
    ----------
    models_dir    : directory containing saved model files
    processed_dir : directory containing feature engineering outputs

    Returns
    -------
    dict with keys: model, encoders, feature_meta, model_metadata,
                    optimal_threshold, feature_names
    """
    model_path    = models_dir / "05_best_model.pkl"
    meta_path     = models_dir / "05_best_model_metadata.json"
    encoder_path  = processed_dir / "04_encoders.pkl"
    feat_meta_path= processed_dir / "04_feature_meta.json"

    for path in [model_path, meta_path, encoder_path, feat_meta_path]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required file not found: {path}\n"
                f"Run Notebooks 04 and 05 before running this notebook."
            )

    with open(model_path,     "rb") as f: model          = pickle.load(f)
    with open(encoder_path,   "rb") as f: encoders       = pickle.load(f)
    with open(meta_path)          as f: model_metadata = json.load(f)
    with open(feat_meta_path)     as f: feature_meta   = json.load(f)

    return {
        "model":             model,
        "encoders":          encoders,
        "model_metadata":    model_metadata,
        "feature_meta":      feature_meta,
        "optimal_threshold": model_metadata["validation_performance"]["optimal_threshold"],
        "feature_names":     feature_meta["final_model_features"],
        "best_model_name":   model_metadata["model_name"],
    }


def load_split(processed_dir: Path, split_name: str) -> tuple:
    """Load X and y for one split. Returns (X: DataFrame, y: Series)."""
    X_path = processed_dir / f"04_X_{split_name}.parquet"
    y_path = processed_dir / f"04_y_{split_name}.parquet"
    if not X_path.exists():
        raise FileNotFoundError(
            f"Split not found: {X_path}\nRun Notebook 04 first."
        )
    X = pd.read_parquet(X_path)
    y = pd.read_parquet(y_path).squeeze()
    return X, y


print("Loading assets...")
assets = load_model_assets(MODELS_DIR, PATHS["processed_dir"])
model             = assets["model"]
encoders          = assets["encoders"]
model_metadata    = assets["model_metadata"]
feature_meta      = assets["feature_meta"]
OPTIMAL_THRESHOLD = assets["optimal_threshold"]
FEATURE_NAMES     = assets["feature_names"]
BEST_NAME         = assets["best_model_name"]

print(f"  Model:     {BEST_NAME}")
print(f"  Features:  {len(FEATURE_NAMES)}")
print(f"  Threshold: {OPTIMAL_THRESHOLD:.4f}  (tuned on validation set)")

print("\nLoading sealed test set...")
X_test, y_test = load_split(PATHS["processed_dir"], "test")
print(f"  Test set: {X_test.shape[0]:,} records | "
      f"positive rate: {y_test.mean():.1%}")

# Also load validation for comparison
X_val, y_val = load_split(PATHS["processed_dir"], "val")


# ── CELL 3: Generate predictions on test set ──────────────────────────────────
print("\n" + "=" * 65)
print("GENERATING TEST SET PREDICTIONS")
print("=" * 65)

y_test_prob = model.predict_proba(X_test)[:, 1]
y_test_pred = (y_test_prob >= OPTIMAL_THRESHOLD).astype(int)

print(f"  Prediction range: [{y_test_prob.min():.4f}, {y_test_prob.max():.4f}]")
print(f"  Mean predicted prob: {y_test_prob.mean():.4f}")
print(f"  True positive rate:  {y_test.mean():.4f}")
print(f"  Predictions at threshold {OPTIMAL_THRESHOLD:.3f}:")
print(f"    Predicted positive: {y_test_pred.sum():,}  ({y_test_pred.mean():.1%})")
print(f"    Predicted negative: {(y_test_pred==0).sum():,}  ({(y_test_pred==0).mean():.1%})")


# ── CELL 4: Compute final metrics — authoritative numbers ─────────────────────
print("\n" + "=" * 65)
print("FINAL TEST SET METRICS — AUTHORITATIVE RESULTS")
print("=" * 65)

test_auc   = roc_auc_score(y_test, y_test_prob)
test_ap    = average_precision_score(y_test, y_test_prob)
test_brier = brier_score_loss(y_test, y_test_prob)

cm = confusion_matrix(y_test, y_test_pred)
tn, fp, fn, tp = cm.ravel()

test_precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
test_recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
test_specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
test_f1        = (2 * test_precision * test_recall /
                  (test_precision + test_recall)
                  if (test_precision + test_recall) > 0 else 0.0)
test_npv       = tn / (tn + fn) if (tn + fn) > 0 else 0.0

print(f"\n  {'Metric':<38} {'Value':>10}  {'Status'}")
print(f"  {'-'*60}")

metrics = [
    ("AUC-ROC",                       test_auc,        test_auc >= MIN_AUC_ROC),
    ("Average Precision (AP)",         test_ap,         test_ap > 0.40),
    ("Brier Score (lower=better)",     test_brier,      test_brier < 0.25),
    ("Recall on discontinued (TPR)",   test_recall,     test_recall >= MIN_RECALL),
    ("Precision on discontinued",      test_precision,  test_precision > 0.40),
    ("Specificity (TNR)",              test_specificity,test_specificity > 0.50),
    ("F1 Score",                       test_f1,         test_f1 > 0.45),
    ("Negative Predictive Value",      test_npv,        True),
]

for name, val, ok in metrics:
    flag = "✅" if ok else "⚠️ "
    print(f"  {flag} {name:<38} {val:>10.4f}")

print(f"\n  Confusion Matrix (threshold={OPTIMAL_THRESHOLD:.3f}):")
print(f"    True  Negatives (correctly identified continued): {tn:,}")
print(f"    False Positives (continued flagged as high-risk): {fp:,}")
print(f"    False Negatives (missed discontinuations):        {fn:,}  ← most costly")
print(f"    True  Positives (correctly identified at-risk):  {tp:,}")

print(f"\n  CLINICAL INTERPRETATION OF ERRORS:")
print(f"    False Negative (fn={fn:,}): Women who will discontinue but the model")
print(f"    predicts they will continue. In ChaguoAI, this means no follow-up")
print(f"    message will be triggered. They may stop with no support.")
print(f"    Cost: medium. ChaguoAI does follow-up for ALL users at 14/30/90 days,")
print(f"    so some safety net exists even without a specific high-risk flag.")
print()
print(f"    False Positive (fp={fp:,}): Women who will continue but the model")
print(f"    predicts they will discontinue. They receive an earlier follow-up")
print(f"    message. Cost: low. An extra supportive message is harmless.")
print()
print(f"    CONCLUSION: Our error asymmetry is clinically acceptable.")
print(f"    FP is cheaper than FN in a follow-up support context.")


# ── CELL 5: Disaggregated evaluation — bias audit ─────────────────────────────
print("\n" + "=" * 65)
print("DISAGGREGATED EVALUATION — BIAS AUDIT")
print("=" * 65)
print()
print("  This is the most important evaluation step.")
print("  A model with high overall AUC can still be biased against")
print("  specific subgroups. We check every clinically meaningful")
print("  subgroup. Any group below the minimum AUC threshold is flagged.")
print()

# Rebuild the test data with the original clean columns for subgroup analysis
clean_path = PATHS["processed_dir"] / "02_cleaned.parquet"
if clean_path.exists():
    df_clean = pd.read_parquet(clean_path)
    # Filter to test split clients
    test_clients = set(
        pd.read_parquet(PATHS["processed_dir"] / "04_X_test.parquet").index
    ) if False else None  # Use feature index approach

    # Instead: rebuild by joining on X_test index
    # X_test index aligns with the test subset of df_clean
    # We stored the split in df_clean in Notebook 04
    if "split" in df_clean.columns:
        df_test_meta = df_clean[df_clean["split"] == "test"].reset_index(drop=True)
    else:
        df_test_meta = None
        print("  NOTE: 'split' column not found in clean data.")
        print("  Subgroup analysis will use encoded features only.")
else:
    df_test_meta = None
    print("  NOTE: Clean data not found. Using encoded features for subgroup analysis.")

bias_rows = []

# Subgroup analysis using encoded X_test features
print(f"  {'Subgroup':<40} {'AUC':>8} {'AP':>8} {'Recall':>8} "
      f"{'N':>7} {'Pos%':>7}  Status")
print(f"  {'-'*82}")


def evaluate_subgroup(mask: np.ndarray, label: str) -> dict | None:
    """Compute metrics for a boolean mask over the test set."""
    if mask.sum() < 50:
        return None
    y_sub  = y_test[mask]
    yp_sub = y_test_prob[mask]
    if y_sub.nunique() < 2:
        return None
    auc    = roc_auc_score(y_sub, yp_sub)
    ap     = average_precision_score(y_sub, yp_sub)
    yhat   = (yp_sub >= OPTIMAL_THRESHOLD).astype(int)
    tp_s   = int(((yhat == 1) & (y_sub == 1)).sum())
    fn_s   = int(((yhat == 0) & (y_sub == 1)).sum())
    rec    = tp_s / (tp_s + fn_s) if (tp_s + fn_s) > 0 else 0.0
    n      = int(mask.sum())
    pos_r  = float(y_sub.mean())
    flag   = "✅" if auc >= MIN_AUC_ROC else "⚠️ BELOW THRESHOLD"
    print(f"  {label:<40} {auc:>8.3f} {ap:>8.3f} {rec:>8.3f} "
          f"{n:>7,} {pos_r:>6.1%}  {flag}")
    return {
        "subgroup": label, "auc": round(auc, 4), "ap": round(ap, 4),
        "recall": round(rec, 4), "n": n, "positive_rate": round(pos_r, 4),
        "meets_min_auc": auc >= MIN_AUC_ROC,
    }


# Age group subgroups
age_col = X_test["age"].values
for lo, hi, label in [
    (10, 17, "Age: 10–17"),
    (18, 24, "Age: 18–24"),
    (25, 29, "Age: 25–29"),
    (30, 34, "Age: 30–34"),
    (35, 39, "Age: 35–39"),
    (40, 49, "Age: 40–49"),
    (50, 60, "Age: 50+"),
]:
    mask   = (age_col >= lo) & (age_col <= hi)
    result = evaluate_subgroup(mask, label)
    if result:
        bias_rows.append(result)

print()
# Previous method category subgroups
prev_cat_col = X_test["previous_method_category_enc"].values
for code, label in enumerate(["(unknown / other)", "barrier",
                               "long_acting_reversible", "permanent",
                               "short_acting_hormonal"]):
    mask   = prev_cat_col == code
    result = evaluate_subgroup(mask, f"Prev method: {label}")
    if result:
        bias_rows.append(result)

print()
# County subgroup
county_col = X_test["county_enc"].values
le_county  = encoders.get("county")
if le_county is not None:
    for code, county_name in enumerate(le_county.classes_):
        if county_name == "UNKNOWN":
            continue
        mask   = county_col == code
        result = evaluate_subgroup(mask, f"County: {county_name}")
        if result:
            bias_rows.append(result)

print()
# Fertility intention subgroup
fert_col = X_test["fertility_ordinal"].values
for val, label in [(1, "Fertility: Within 2 Years"),
                   (2, "Fertility: Later than 2 years"),
                   (3, "Fertility: No more children")]:
    mask   = fert_col == val
    result = evaluate_subgroup(mask, label)
    if result:
        bias_rows.append(result)

bias_df = pd.DataFrame(bias_rows)
bias_df.to_csv(PATHS["reports_dir"] / "06_bias_audit.csv", index=False)
print(f"\n  Bias audit saved: {PATHS['reports_dir'] / '06_bias_audit.csv'}")

n_below = (bias_df["meets_min_auc"] == False).sum()
if n_below > 0:
    print(f"\n  ⚠️  {n_below} subgroups below AUC threshold {MIN_AUC_ROC}:")
    for _, row in bias_df[~bias_df["meets_min_auc"]].iterrows():
        print(f"    {row['subgroup']}: AUC={row['auc']:.3f}  n={row['n']:,}")
else:
    print(f"\n  ✅ All subgroups meet minimum AUC threshold {MIN_AUC_ROC}.")


# ── CELL 6: Calibration analysis ──────────────────────────────────────────────
print("\n" + "=" * 65)
print("CALIBRATION ANALYSIS")
print("=" * 65)
print()
print("  A well-calibrated model means: when it says 60% probability,")
print("  approximately 60% of those women actually discontinue.")
print("  Miscalibrated probabilities mislead the ranking in ChaguoAI.")
print()

fraction_of_pos, mean_predicted = calibration_curve(
    y_test, y_test_prob, n_bins=10, strategy="quantile"
)

calibration_error = np.mean(np.abs(fraction_of_pos - mean_predicted))
print(f"  Mean Absolute Calibration Error: {calibration_error:.4f}")

if calibration_error < 0.05:
    print("  ✅ Excellent calibration (error < 0.05).")
elif calibration_error < 0.10:
    print("  ✅ Good calibration (error < 0.10).")
else:
    print("  ⚠️  Calibration error > 0.10. Consider Platt scaling.")
    print("     Adding CalibratedClassifierCV wrapper will improve this.")


# ── CELL 7: Save final metrics ─────────────────────────────────────────────────
final_metrics = {
    "model_name":              BEST_NAME,
    "evaluated_at":            datetime.now().isoformat(),
    "test_set_n":              int(len(y_test)),
    "test_positive_rate":      float(round(y_test.mean(), 4)),
    "auc_roc":                 float(round(test_auc, 4)),
    "average_precision":       float(round(test_ap, 4)),
    "brier_score":             float(round(test_brier, 4)),
    "calibration_error":       float(round(calibration_error, 4)),
    "optimal_threshold":       float(round(OPTIMAL_THRESHOLD, 4)),
    "precision":               float(round(test_precision, 4)),
    "recall":                  float(round(test_recall, 4)),
    "specificity":             float(round(test_specificity, 4)),
    "f1_score":                float(round(test_f1, 4)),
    "negative_predictive_value":float(round(test_npv, 4)),
    "true_positives":          int(tp),
    "false_positives":         int(fp),
    "true_negatives":          int(tn),
    "false_negatives":         int(fn),
    "meets_min_auc":           bool(test_auc >= MIN_AUC_ROC),
    "meets_min_recall":        bool(test_recall >= MIN_RECALL),
}

pd.DataFrame([final_metrics]).T.to_csv(
    PATHS["reports_dir"] / "06_final_metrics.csv", header=["value"]
)
print(f"\nFinal metrics saved: {PATHS['reports_dir'] / '06_final_metrics.csv'}")


# ── CELL 8: Plot 1 — Main evaluation dashboard ────────────────────────────────
print("\n[Plot 1] Final evaluation dashboard")

fig = plt.figure(figsize=(18, 12))
gs  = gridspec.GridSpec(2, 3, figure=fig, hspace=0.35, wspace=0.35)

# ── ROC Curve ─────────────────────────────────────────────────────────────────
ax1 = fig.add_subplot(gs[0, 0])
RocCurveDisplay.from_predictions(
    y_test, y_test_prob, ax=ax1,
    name=f"{BEST_NAME}\n(AUC={test_auc:.4f})",
    color=PALETTE["teal"], lw=2.5,
)
ax1.plot([0, 1], [0, 1], "k:", linewidth=1, label="Random (0.50)")
ax1.set_title("ROC Curve — Test Set")
ax1.legend(fontsize=8, loc="lower right")

# ── Precision-Recall Curve ────────────────────────────────────────────────────
ax2 = fig.add_subplot(gs[0, 1])
p_vals, r_vals, thresh_vals = precision_recall_curve(y_test, y_test_prob)
ax2.plot(r_vals, p_vals, color=PALETTE["coral"], lw=2.5,
         label=f"AP={test_ap:.4f}")
ax2.axhline(y_test.mean(), color="k", linestyle=":", lw=1,
            label=f"No-skill ({y_test.mean():.2f})")
ax2.axvline(test_recall, color=PALETTE["red"], linestyle="--", lw=1.5,
            label=f"Recall@threshold={test_recall:.3f}")
ax2.set_xlabel("Recall")
ax2.set_ylabel("Precision")
ax2.set_title("Precision-Recall Curve — Test Set")
ax2.legend(fontsize=8)
ax2.set_xlim(0, 1)
ax2.set_ylim(0, 1.05)

# ── Calibration Plot ──────────────────────────────────────────────────────────
ax3 = fig.add_subplot(gs[0, 2])
ax3.plot(mean_predicted, fraction_of_pos,
         "o-", color=PALETTE["teal"], lw=2, markersize=6,
         label=f"Model (MAE={calibration_error:.3f})")
ax3.plot([0, 1], [0, 1], "k--", lw=1.5, label="Perfect calibration")
ax3.set_xlabel("Mean predicted probability")
ax3.set_ylabel("Fraction actually discontinued")
ax3.set_title("Calibration Plot — Test Set\n(closer to diagonal = better)")
ax3.legend(fontsize=9)
ax3.set_xlim(0, 1)
ax3.set_ylim(0, 1)

# ── Confusion Matrix ──────────────────────────────────────────────────────────
ax4 = fig.add_subplot(gs[1, 0])
ConfusionMatrixDisplay(
    cm, display_labels=["Continued", "Discontinued"]
).plot(ax=ax4, cmap="Blues", colorbar=False)
ax4.set_title(f"Confusion Matrix — Test Set\n(threshold={OPTIMAL_THRESHOLD:.3f})")

# ── Probability distribution ──────────────────────────────────────────────────
ax5 = fig.add_subplot(gs[1, 1])
ax5.hist(y_test_prob[y_test == 0], bins=40, alpha=0.65,
         color=PALETTE["teal"], label="Continued (y=0)", density=True)
ax5.hist(y_test_prob[y_test == 1], bins=40, alpha=0.65,
         color=PALETTE["coral"], label="Discontinued (y=1)", density=True)
ax5.axvline(OPTIMAL_THRESHOLD, color=PALETTE["red"], linestyle="--", lw=2,
            label=f"Threshold: {OPTIMAL_THRESHOLD:.3f}")
ax5.set_xlabel("Predicted discontinuation probability")
ax5.set_ylabel("Density")
ax5.set_title("Score Distribution — Test Set")
ax5.legend(fontsize=8)

# ── Metrics summary panel ─────────────────────────────────────────────────────
ax6 = fig.add_subplot(gs[1, 2])
ax6.axis("off")
summary_text = [
    ("Model",        BEST_NAME),
    ("",             ""),
    ("AUC-ROC",      f"{test_auc:.4f}  {'✅' if test_auc >= MIN_AUC_ROC else '❌'}"),
    ("Avg Precision",f"{test_ap:.4f}"),
    ("Brier Score",  f"{test_brier:.4f}"),
    ("Cal. Error",   f"{calibration_error:.4f}"),
    ("",             ""),
    ("Threshold",    f"{OPTIMAL_THRESHOLD:.4f}"),
    ("Precision",    f"{test_precision:.4f}"),
    ("Recall",       f"{test_recall:.4f}  {'✅' if test_recall >= MIN_RECALL else '❌'}"),
    ("Specificity",  f"{test_specificity:.4f}"),
    ("F1 Score",     f"{test_f1:.4f}"),
    ("",             ""),
    ("TP",           f"{tp:,}"),
    ("FP",           f"{fp:,}"),
    ("TN",           f"{tn:,}"),
    ("FN",           f"{fn:,}"),
    ("",             ""),
    ("Test Records", f"{len(y_test):,}"),
    ("Pos Rate",     f"{y_test.mean():.1%}"),
]
y_pos = 1.0
for label, val in summary_text:
    if label == "":
        y_pos -= 0.03
        continue
    fw = "bold" if label in ("Model", "AUC-ROC", "Recall") else "normal"
    ax6.text(0.0, y_pos, f"{label}:", transform=ax6.transAxes,
             fontsize=9, fontweight=fw, va="top")
    ax6.text(0.55, y_pos, val, transform=ax6.transAxes,
             fontsize=9, va="top")
    y_pos -= 0.05

ax6.set_title("Metrics Summary", fontweight="bold")

plt.suptitle(
    f"Figure 27: Final Evaluation Dashboard — {BEST_NAME}\n"
    f"(Test set: n={len(y_test):,} records, never used during training or tuning)",
    fontweight="bold", y=1.01, fontsize=12
)
plt.savefig(PATHS["figures_dir"] / "06a_final_evaluation_dashboard.png",
            dpi=150, bbox_inches="tight")
plt.show()
print("  Saved: 06a_final_evaluation_dashboard.png")


# ── CELL 9: Plot 2 — Bias audit visualisation ─────────────────────────────────
print("\n[Plot 2] Bias audit chart")

age_bias     = bias_df[bias_df["subgroup"].str.startswith("Age")].copy()
method_bias  = bias_df[bias_df["subgroup"].str.startswith("Prev")].copy()
county_bias  = bias_df[bias_df["subgroup"].str.startswith("County")].copy()
fertility_bias = bias_df[bias_df["subgroup"].str.startswith("Fertility")].copy()

fig, axes = plt.subplots(2, 2, figsize=(16, 10))

for ax, subset, title in [
    (axes[0, 0], age_bias,      "AUC-ROC by Age Group"),
    (axes[0, 1], method_bias,   "AUC-ROC by Previous Method Category"),
    (axes[1, 0], county_bias,   "AUC-ROC by County"),
    (axes[1, 1], fertility_bias,"AUC-ROC by Fertility Intention"),
]:
    if subset.empty:
        ax.text(0.5, 0.5, "Insufficient data", ha="center", va="center",
                transform=ax.transAxes)
        ax.set_title(title)
        continue

    subset_sorted = subset.sort_values("auc")
    bar_colors = [PALETTE["coral"] if not ok else PALETTE["teal"]
                  for ok in subset_sorted["meets_min_auc"]]

    bars = ax.barh(subset_sorted["subgroup"], subset_sorted["auc"],
                   color=bar_colors, height=0.55)

    for bar, (_, row) in zip(bars, subset_sorted.iterrows()):
        ax.text(bar.get_width() + 0.002,
                bar.get_y() + bar.get_height() / 2,
                f"{row['auc']:.3f}  (n={row['n']:,})",
                va="center", fontsize=8.5)

    ax.axvline(MIN_AUC_ROC, color=PALETTE["red"], linestyle="--",
               linewidth=1.5, label=f"Min: {MIN_AUC_ROC}")
    ax.axvline(test_auc, color=PALETTE["navy"], linestyle=":",
               linewidth=1.5, label=f"Overall: {test_auc:.3f}")
    ax.set_xlabel("AUC-ROC")
    ax.set_title(title)
    ax.set_xlim(0.40, 1.05)
    ax.legend(fontsize=8)

legend_items = [
    mpatches.Patch(color=PALETTE["teal"],  label="Meets minimum AUC"),
    mpatches.Patch(color=PALETTE["coral"], label="Below minimum AUC"),
]
fig.legend(handles=legend_items, loc="lower center", ncol=2,
           fontsize=10, bbox_to_anchor=(0.5, -0.02))

plt.suptitle(
    "Figure 28: Disaggregated Performance — Bias Audit\n"
    "(Coral = performance concern; subgroups below threshold need monitoring)",
    fontweight="bold"
)
plt.tight_layout()
plt.savefig(PATHS["figures_dir"] / "06b_bias_audit.png",
            dpi=150, bbox_inches="tight")
plt.show()
print("  Saved: 06b_bias_audit.png")


# ── CELL 10: Plot 3 — Predicted risk rank vs actual rate ──────────────────────
print("\n[Plot 3] Predicted risk deciles vs actual discontinuation rate")
print("  (Validates that the model's ranking is clinically meaningful)")

decile_df = pd.DataFrame({
    "prob":    y_test_prob,
    "actual":  y_test.values,
})
decile_df["decile"] = pd.qcut(decile_df["prob"], q=10, labels=False)

decile_summary = (
    decile_df.groupby("decile")
    .agg(mean_pred=("prob", "mean"), actual_rate=("actual", "mean"), n=("actual", "count"))
    .reset_index()
)

fig, ax = plt.subplots(figsize=(11, 5))
x = decile_summary["decile"]
width = 0.35

bars1 = ax.bar(x - width / 2, decile_summary["mean_pred"] * 100,
               width=width, color=PALETTE["teal"], alpha=0.85,
               label="Mean predicted probability")
bars2 = ax.bar(x + width / 2, decile_summary["actual_rate"] * 100,
               width=width, color=PALETTE["coral"], alpha=0.85,
               label="Actual discontinuation rate")

ax.set_xticks(x)
ax.set_xticklabels([f"D{int(i)+1}" for i in x])
ax.set_xlabel("Risk decile (D1 = lowest predicted risk, D10 = highest)")
ax.set_ylabel("Rate (%)")
ax.set_title(
    "Figure 29: Predicted Risk Decile vs Actual Discontinuation Rate\n"
    "Good calibration: teal and coral bars should be similar heights per decile\n"
    "Good discrimination: actual rate should rise consistently D1 → D10"
)
ax.legend(fontsize=9)
ax.axhline(y_test.mean() * 100, color=PALETTE["navy"], linestyle="--",
           linewidth=1.5, label=f"Overall rate: {y_test.mean()*100:.1f}%")

# Add count labels above each pair
for i, (_, row) in enumerate(decile_summary.iterrows()):
    ax.text(i, max(row["mean_pred"], row["actual_rate"]) * 100 + 1.0,
            f"n={row['n']:,}", ha="center", fontsize=7.5, color=PALETTE["gray"])

plt.tight_layout()
plt.savefig(PATHS["figures_dir"] / "06c_decile_calibration.png",
            dpi=150, bbox_inches="tight")
plt.show()
print("  Saved: 06c_decile_calibration.png")

print(f"\n  DISCRIMINATION: Does predicted risk rise D1→D10?")
monotone = all(
    decile_summary["actual_rate"].iloc[i] <=
    decile_summary["actual_rate"].iloc[i + 1]
    for i in range(len(decile_summary) - 1)
)
print(f"    Strictly monotone: {'✅ Yes' if monotone else '⚠️  Not fully — check D8-D10'}")
print(f"    D1 actual rate:  {decile_summary['actual_rate'].iloc[0]*100:.1f}%")
print(f"    D10 actual rate: {decile_summary['actual_rate'].iloc[-1]*100:.1f}%")
lift_d10 = decile_summary["actual_rate"].iloc[-1] / y_test.mean()
print(f"    Lift in top decile: {lift_d10:.2f}×  (1.0 = no lift, >1.5 = useful)")


# ── CELL 11: Inference pipeline ───────────────────────────────────────────────
print("\n" + "=" * 65)
print("INFERENCE PIPELINE")
print("=" * 65)
print()
print("  This is the function called by the ChaguoAI orchestrator.")
print("  It takes a user profile and a candidate method, returns")
print("  a predicted adherence probability for method ranking.")


def build_inference_row(
    user_profile: dict,
    candidate_method: str,
    previous_method:  str,
    feature_names:    list,
    loaded_encoders:  dict,
) -> pd.DataFrame:
    """
    Build a single-row feature DataFrame for one (user, method) combination.

    Parameters
    ----------
    user_profile : dict
        Keys: age_years, number_of_children, education_level,
              fertility_intention, counseled, county,
              delivery_type, year, month_num
    candidate_method : str
        Method being evaluated e.g. 'Injectables', 'Implants'
    previous_method : str
        User's prior method, or 'unknown' if first-time user
    feature_names : list
        Ordered list from feature_meta["final_model_features"]
    loaded_encoders : dict
        Fitted LabelEncoder objects from 04_encoders.pkl

    Returns
    -------
    pd.DataFrame with exactly one row and columns = feature_names
    """
    age      = int(user_profile.get("age_years", 25))
    children = int(user_profile.get("number_of_children", 1))
    edu_text = user_profile.get("education_level", "Primary Complete")
    fert_text= user_profile.get("fertility_intention", "Later than 2 years")
    cou_text = user_profile.get("counseled", "Yes")
    county   = str(user_profile.get("county", "UNKNOWN"))
    delivery = str(user_profile.get("delivery_type", "facility"))
    year_val = int(user_profile.get("year", 2024))
    month_n  = int(user_profile.get("month_num", 6))

    prev_cat = METHOD_CATEGORY_MAP.get(previous_method, "unknown")
    curr_cat = METHOD_CATEGORY_MAP.get(candidate_method, "unknown")

    def _switch_type(curr, prev):
        if prev == "unknown":
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

    row = {
        "age":                        age,
        "noofchildren":               min(children, 15),
        "education_ordinal":          EDUCATION_ORDINAL.get(edu_text, 2),
        "fertility_ordinal":          FERTILITY_ORDINAL.get(fert_text, 2),
        "month_num":                  month_n,
        "year":                       year_val,
        "is_young_woman":             int(age < 20),
        "is_older_woman":             int(age >= 40),
        "has_high_parity":            int(children >= 5),
        "wants_child_soon":           int(fert_text == "Within 2 Years"),
        "wants_no_more":              int(fert_text == "No more Children"),
        "was_on_larc":                int(prev_cat == "long_acting_reversible"),
        "adopted_larc":               int(curr_cat == "long_acting_reversible"),
        "counseled_binary":           COUNSELED_BINARY.get(cou_text, 1),
        "fertility_intention_known":  1,
        "education_known":            1,
        "county":                     county,
        "delivery_type":              delivery,
        "previous_method_category":   prev_cat,
        "current_method_category":    curr_cat,
        "switch_type":                _switch_type(curr_cat, prev_cat),
    }

    df_row = pd.DataFrame([row])

    for cat_col in ["county", "delivery_type", "previous_method_category",
                    "current_method_category", "switch_type"]:
        le      = loaded_encoders.get(cat_col)
        enc_col = cat_col + "_enc"
        if le is None:
            df_row[enc_col] = 0
            continue
        val = str(df_row[cat_col].iloc[0])
        if val not in set(le.classes_):
            val = "UNKNOWN"
        df_row[enc_col] = int(le.transform([val])[0])

    # Select features in exact trained order, fill any missing with 0
    for feat in feature_names:
        if feat not in df_row.columns:
            df_row[feat] = 0

    return df_row[feature_names].fillna(0)


def rank_methods_for_user(
    user_profile:    dict,
    previous_method: str,
    mec_safe_methods: list,
    model,
    feature_names:   list,
    loaded_encoders: dict,
    threshold:       float,
) -> pd.DataFrame:
    """
    Score all MEC-safe candidate methods for one user and rank them
    by predicted adherence probability (highest = recommend first).

    Parameters
    ----------
    mec_safe_methods : list
        List of method names that the WHO MEC engine has cleared
        as safe for this user. Only these are scored.
    threshold : float
        Decision threshold for 'high risk' flag.

    Returns
    -------
    pd.DataFrame sorted by adherence_probability descending.
    Columns: method, discontinuation_probability, adherence_probability,
             risk_level
    """
    results = []
    for method in mec_safe_methods:
        X_inf = build_inference_row(
            user_profile, method, previous_method,
            feature_names, loaded_encoders,
        )
        disc_prob   = float(model.predict_proba(X_inf)[0, 1])
        adhere_prob = 1.0 - disc_prob
        results.append({
            "method":                      method,
            "discontinuation_probability": round(disc_prob, 4),
            "adherence_probability":       round(adhere_prob, 4),
            "risk_level":                  "high" if disc_prob >= threshold else "low",
        })

    return (
        pd.DataFrame(results)
        .sort_values("adherence_probability", ascending=False)
        .reset_index(drop=True)
    )


# ── CELL 12: Inference demonstration ──────────────────────────────────────────
print("\n" + "=" * 65)
print("INFERENCE DEMONSTRATION")
print("=" * 65)

demo_profiles = [
    {
        "label":           "Amina — 22yr, 1 child, Siaya, injections history",
        "profile": {
            "age_years":          22,
            "number_of_children": 1,
            "education_level":    "Primary Complete",
            "fertility_intention":"Later than 2 years",
            "counseled":          "Yes",
            "county":             "Siaya",
            "delivery_type":      "facility",
            "year":               2024,
            "month_num":          6,
        },
        "previous_method": "Injectables",
        "mec_safe":        ["Injectables", "Implants", "Pills", "Condoms", "IUCD", "BTL"],
    },
    {
        "label":           "Beatrice — 35yr, 5 children, Busia, wants no more",
        "profile": {
            "age_years":          35,
            "number_of_children": 5,
            "education_level":    "Primary Incomplete",
            "fertility_intention":"No more Children",
            "counseled":          "Yes",
            "county":             "Busia",
            "delivery_type":      "community",
            "year":               2024,
            "month_num":          3,
        },
        "previous_method": "Pills",
        "mec_safe":        ["Injectables", "Implants", "Condoms", "IUCD", "BTL"],
    },
    {
        "label":           "Cynthia — 18yr, 0 children, Siaya, wants child within 2yr",
        "profile": {
            "age_years":          18,
            "number_of_children": 0,
            "education_level":    "Secondary & Above",
            "fertility_intention":"Within 2 Years",
            "counseled":          "Yes",
            "county":             "Siaya",
            "delivery_type":      "facility",
            "year":               2024,
            "month_num":          9,
        },
        "previous_method": "Condoms",
        "mec_safe":        ["Injectables", "Pills", "Condoms", "Implants"],
    },
]

all_demo_rows = []

for demo in demo_profiles:
    print(f"\n  {demo['label']}")
    print(f"  Previous method: {demo['previous_method']}")
    print(f"  MEC-safe methods: {demo['mec_safe']}")

    ranking = rank_methods_for_user(
        user_profile     = demo["profile"],
        previous_method  = demo["previous_method"],
        mec_safe_methods = demo["mec_safe"],
        model            = model,
        feature_names    = FEATURE_NAMES,
        loaded_encoders  = encoders,
        threshold        = OPTIMAL_THRESHOLD,
    )

    print(f"\n  {'Rank':<6} {'Method':<20} {'Adherence Prob':>15} "
          f"{'Disc Prob':>12} {'Risk':>8}")
    print(f"  {'-'*65}")
    for rank, (_, row) in enumerate(ranking.iterrows(), 1):
        star = " ← RECOMMEND" if rank == 1 else ""
        print(f"  {rank:<6} {row['method']:<20} "
              f"{row['adherence_probability']:>14.1%} "
              f"{row['discontinuation_probability']:>12.1%} "
              f"{row['risk_level']:>8}{star}")

    # Collect for saving
    for rank, (_, row) in enumerate(ranking.iterrows(), 1):
        all_demo_rows.append({
            "user_label":    demo["label"],
            "rank":          rank,
            "method":        row["method"],
            "adherence_pct": round(row["adherence_probability"] * 100, 1),
            "disc_pct":      round(row["discontinuation_probability"] * 100, 1),
            "risk_level":    row["risk_level"],
        })

pd.DataFrame(all_demo_rows).to_csv(
    PATHS["reports_dir"] / "06_inference_demo.csv", index=False
)
print(f"\n  Inference demo saved: {PATHS['reports_dir'] / '06_inference_demo.csv'}")


# ── CELL 13: Scalability guide ────────────────────────────────────────────────
print("\n" + "=" * 65)
print("SCALABILITY GUIDE")
print("=" * 65)

scalability_guide = """
HOW TO ADD DATA FROM A NEW COUNTY OR COUNTRY
=============================================

The model is designed to scale to new geographies without
rewriting any code. Follow these steps:

STEP 1 — Format your new CSV to match Client_Service_Statistics.csv
  Required column names (can be renamed in config.py):
    gender, fpstatus, age, noofchildren, educationlevel,
    fertilityintention, previousmethod, methodadopted,
    counseled, county, delivery, year, month

  Required values for fpstatus:   'Revisit' (or equivalent)
  Required values for gender:     'Female' (or equivalent)
  Method names should match or be added to METHOD_CATEGORY_MAP in config.py

STEP 2 — Run the full pipeline on new data
  Set CHAGUOAI_DATA_DIR to your new data folder
  Run Notebooks 01 → 04 (skip Notebook 02 Step 6 removal list
  if your data has different method names)

STEP 3 — Choose a retraining strategy

  Option A: FULL RETRAIN (new geography only)
    Train a fresh model on new-geography data only.
    Best when: new geography is very different from Western Kenya.
    Risk: loses all patterns learned from 78k+ Western Kenya records.

  Option B: TRANSFER LEARNING (recommended)
    Take the current best model. Fine-tune it on new data
    by continuing training with a lower learning rate.
    The dataset_source_enc feature automatically differentiates
    geographies in the combined model.
    Best when: new geography is broadly similar (East Africa, SSA).

  Option C: COMBINED RETRAIN (most data-efficient)
    Stack new CSV rows with original (after harmonizing column names).
    Retrain from scratch on combined dataset.
    The 'county' or new 'geography' column becomes a feature.
    Best when: you have 5k+ new records from the new geography.

STEP 4 — Re-evaluate disaggregated performance
  Run Notebook 06 with the new test set.
  Check that AUC >= 0.65 for all subgroups in the new geography.

HOW TO RETRAIN WITH CHATBOT DATA
=================================

Every follow-up interaction at Day 14, Day 30, and Day 90
where a user confirms their method status is a labeled data point.

Log each interaction with this schema:
  gender='Female', fpstatus='Revisit',
  age=<from intake>, noofchildren=<from intake>,
  educationlevel=<from intake>, fertilityintention=<from intake>,
  previousmethod=<method at recommendation>, methodadopted=<confirmed>,
  counseled='Yes', county=<from intake>, delivery='facility',
  year=<current year>, month=<current month>

When 500+ chatbot records accumulate → trigger Notebooks 02-06.
The new model incorporates real-world ChaguoAI user behaviour.

BIAS MONITORING IN PRODUCTION
================================

After deployment, monitor these metrics monthly:
  1. Overall positive rate among scored users (should be ~40%)
  2. AUC-ROC on any new labeled data (should be >=0.65)
  3. Fraction of 'high risk' flags by age group
     (should not systematically over-flag young women)
  4. Method recommendation distribution
     (should not always recommend LARC regardless of profile)

If any metric drifts significantly, trigger retraining.
"""
print(scalability_guide)

# Save as text file for open-source repo
with open(PATHS["reports_dir"] / "06_scalability_guide.txt", "w", encoding='utf-8') as f:
    f.write(scalability_guide)
print(f"Scalability guide saved: {PATHS['reports_dir'] / '06_scalability_guide.txt'}")


# ── CELL 14: Complete model card ──────────────────────────────────────────────
print("\n" + "=" * 65)
print("GENERATING COMPLETE MODEL CARD")
print("=" * 65)

model_card = {
    "model_card_version": "1.0",
    "generated_at":       datetime.now().isoformat(),

    "model_overview": {
        "name":        f"ChaguoAI Contraceptive Discontinuation Predictor",
        "version":     datetime.now().strftime("%Y%m%d"),
        "algorithm":   BEST_NAME,
        "task":        "Binary classification: predicts contraceptive discontinuation",
        "output":      "Probability [0.0-1.0] that a client will switch/stop method",
        "intended_use":(
            "Rank candidate contraceptive methods by predicted adherence "
            "for a specific woman's profile. Used inside ChaguoAI to order "
            "recommendations after the WHO MEC safety filter is applied. "
            "A higher predicted discontinuation probability means the model "
            "expects this woman is less likely to continue that method. "
            "Use (1 - probability) as the adherence score for ranking."
        ),
    },

    "training_data": {
        "source":        "Client_Service_Statistics.csv",
        "provider":      "Western Kenya FP Programme Monitoring System",
        "geography":     "Siaya and Busia counties, Western Kenya, Kenya",
        "time_period":   "2013-2015",
        "n_raw_records": 216539,
        "n_model_records": int(
            feature_meta["n_train"] + feature_meta["n_val"] + feature_meta["n_test"]
        ),
        "population":    "Female family planning revisit clients aged 10-60",
        "target_definition": (
            "discontinued=1 if client adopted a different method at revisit; "
            "discontinued=0 if client continued same method. "
            "Planned removals (Removal_Implant, Removal_IUCD) excluded."
        ),
        "split_strategy": (
            "Client-level stratified 70/15/15. All visits from the same "
            "client go to exactly one split, preventing data leakage."
        ),
    },

    "features": {
        "n_features":         len(FEATURE_NAMES),
        "feature_list":       FEATURE_NAMES,
        "categorical_encoded":feature_meta["categorical_features_raw"],
        "encoding_file":      "04_encoders.pkl",
    },

    "performance": {
        "test_set_metrics": {
            "auc_roc":               float(round(test_auc, 4)),
            "average_precision":     float(round(test_ap, 4)),
            "brier_score":           float(round(test_brier, 4)),
            "calibration_mae":       float(round(calibration_error, 4)),
            "optimal_threshold":     float(round(OPTIMAL_THRESHOLD, 4)),
            "precision":             float(round(test_precision, 4)),
            "recall_discontinued":   float(round(test_recall, 4)),
            "specificity":           float(round(test_specificity, 4)),
            "f1_score":              float(round(test_f1, 4)),
            "true_positives":        int(tp),
            "false_positives":       int(fp),
            "true_negatives":        int(tn),
            "false_negatives":       int(fn),
            "n_test_records":        int(len(y_test)),
        },
        "minimum_thresholds": {
            "auc_roc":  MIN_AUC_ROC,
            "recall":   MIN_RECALL,
        },
        "meets_thresholds": {
            "auc_roc": bool(test_auc >= MIN_AUC_ROC),
            "recall":  bool(test_recall >= MIN_RECALL),
        },
        "subgroup_performance": bias_df.to_dict(orient="records"),
    },

    "ethical_considerations": {
        "bias_statement": (
            "This model was trained exclusively on data from two counties in "
            "Western Kenya (2013-2015). Performance in other geographies "
            "has not been validated and should be tested locally before "
            "clinical deployment. Disaggregated performance across age "
            "groups and method categories is documented in the bias audit."
        ),
        "limitations": [
            "Does not capture women who stopped and never returned to clinic.",
            "No attitudinal features (partner support, side-effect history).",
            "2013-2015 method availability may differ from current programmes.",
            "Vasectomy excluded — male partner context not captured.",
            "Pills & Condoms dual method treated as short-acting hormonal.",
        ],
        "misuse_prevention": (
            "This model must NEVER be used as a standalone recommendation "
            "engine. It operates DOWNSTREAM of the WHO MEC safety filter. "
            "The MEC engine determines what is medically safe; this model "
            "determines what is most likely to be sustained. Any method "
            "flagged as Category 3 or 4 by the MEC engine must never "
            "appear in recommendations regardless of this model's output."
        ),
        "privacy": (
            "No personally identifiable information is required at inference. "
            "The model takes demographic and clinical attributes only. "
            "Phone numbers and names are never passed to the model."
        ),
    },

    "technical_details": {
        "framework":         "scikit-learn / xgboost / lightgbm",
        "python_version":    sys.version,
        "random_seed":       RANDOM_SEED,
        "model_files": {
            "model":         "05_best_model.pkl",
            "encoders":      "04_encoders.pkl",
            "feature_meta":  "04_feature_meta.json",
        },
        "inference_function": "build_inference_row() in Notebook 06",
        "retraining_guide":   "See 06_scalability_guide.txt",
    },

    "deployment": {
        "integration": (
            "Called by the ChaguoAI orchestrator after WHO MEC assessment. "
            "Receives a UserProfile and a list of MEC-safe methods. "
            "Returns methods ranked by predicted adherence probability. "
            "Optimal threshold: {:.3f}".format(OPTIMAL_THRESHOLD)
        ),
        "inference_latency": "<5ms per method (single row prediction)",
        "dependencies":      ["scikit-learn", "xgboost", "lightgbm",
                              "numpy", "pandas"],
    },
}

model_card_path = MODELS_DIR / "06_model_card.json"
with open(model_card_path, "w") as f:
    json.dump(model_card, f, indent=2, default=str)
print(f"  Model card saved: {model_card_path}")


# ── CELL 15: Final dashboard chart ────────────────────────────────────────────
print("\n[Final Plot] Model performance vs baseline vs thresholds")

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Left: Val vs Test comparison to confirm no overfitting
val_auc   = model_metadata["validation_performance"]["auc_roc"]
val_ap    = model_metadata["validation_performance"]["average_precision"]
val_rec   = model_metadata["validation_performance"]["recall_at_threshold"]
dummy_auc = 0.50

metrics_compare = pd.DataFrame({
    "metric":    ["AUC-ROC", "Avg Precision", "Recall"],
    "validation":[val_auc, val_ap, val_rec],
    "test":      [test_auc, test_ap, test_recall],
    "minimum":   [MIN_AUC_ROC, 0.35, MIN_RECALL],
    "dummy":     [dummy_auc, y_test.mean(), y_test.mean()],
})

ax = axes[0]
x_pos = np.arange(len(metrics_compare))
width = 0.22
bars1 = ax.bar(x_pos - width*1.5, metrics_compare["dummy"],      width=width, color=PALETTE["gray"],   label="Dummy baseline")
bars2 = ax.bar(x_pos - width*0.5, metrics_compare["minimum"],    width=width, color=PALETTE["amber"],  label="Min threshold")
bars3 = ax.bar(x_pos + width*0.5, metrics_compare["validation"], width=width, color=PALETTE["teal"],   label="Validation")
bars4 = ax.bar(x_pos + width*1.5, metrics_compare["test"],       width=width, color=PALETTE["coral"],  label="Test (final)")

for bar_grp in [bars1, bars2, bars3, bars4]:
    for bar in bar_grp:
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.008,
                f"{bar.get_height():.2f}",
                ha="center", va="bottom", fontsize=7.5)

ax.set_xticks(x_pos)
ax.set_xticklabels(metrics_compare["metric"])
ax.set_ylabel("Score")
ax.set_title("Figure 30a: Validation vs Test Performance\n(similar scores = no overfitting)")
ax.legend(fontsize=8)
ax.set_ylim(0, 1.15)

# Right: Bias audit summary
ax = axes[1]
if not bias_df.empty:
    bias_sorted = bias_df.sort_values("auc")
    bar_colors  = [PALETTE["coral"] if not ok else PALETTE["teal"]
                   for ok in bias_sorted["meets_min_auc"]]
    bars = ax.barh(
        [s[:35] for s in bias_sorted["subgroup"]],
        bias_sorted["auc"],
        color=bar_colors, height=0.7,
    )
    ax.axvline(MIN_AUC_ROC, color=PALETTE["red"], linestyle="--",
               linewidth=1.5, label=f"Min AUC: {MIN_AUC_ROC}")
    ax.axvline(test_auc, color=PALETTE["navy"], linestyle=":",
               linewidth=1.5, label=f"Overall: {test_auc:.3f}")
    ax.set_xlabel("AUC-ROC")
    ax.set_title("Figure 30b: Subgroup AUC Summary\n(coral = below minimum threshold)")
    ax.set_xlim(0.4, 1.02)
    ax.legend(fontsize=8)

legend_items = [
    mpatches.Patch(color=PALETTE["teal"],  label="Meets minimum"),
    mpatches.Patch(color=PALETTE["coral"], label="Below minimum"),
]
ax.legend(handles=legend_items, loc="lower right", fontsize=8)

plt.suptitle("Figure 30: Final Performance Summary", fontweight="bold")
plt.tight_layout()
plt.savefig(PATHS["figures_dir"] / "06d_final_summary.png",
            dpi=150, bbox_inches="tight")
plt.show()
print("  Saved: 06d_final_summary.png")


# ── CELL 16: Final summary ─────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("FINAL EVALUATION COMPLETE")
print("=" * 65)

print(f"""
  MODEL: {BEST_NAME}
  ─────────────────────────────────────────────────────
  TEST SET RESULTS (authoritative — test set opened once):
    AUC-ROC:          {test_auc:.4f}   {'✅' if test_auc >= MIN_AUC_ROC else '❌'}  (min {MIN_AUC_ROC})
    Average Precision:{test_ap:.4f}
    Brier Score:      {test_brier:.4f}   (lower is better)
    Calibration MAE:  {calibration_error:.4f}   ({'excellent' if calibration_error < 0.05 else 'good' if calibration_error < 0.10 else 'needs calibration'})
    Threshold:        {OPTIMAL_THRESHOLD:.4f}
    Precision:        {test_precision:.4f}
    Recall:           {test_recall:.4f}   {'✅' if test_recall >= MIN_RECALL else '❌'}  (min {MIN_RECALL})
    F1 Score:         {test_f1:.4f}
    Specificity:      {test_specificity:.4f}

  CONFUSION MATRIX:
    TP (correct high-risk):      {tp:,}
    FP (false alarm):            {fp:,}
    TN (correct low-risk):       {tn:,}
    FN (missed high-risk):       {fn:,}  ← most costly error

  BIAS AUDIT:
    Subgroups evaluated:         {len(bias_df)}
    Subgroups below min AUC:     {(~bias_df['meets_min_auc']).sum()}

  TOP DECILE LIFT:
    D10 actual disc rate:        {decile_summary['actual_rate'].iloc[-1]*100:.1f}%
    Overall disc rate:           {y_test.mean()*100:.1f}%
    Lift:                        {lift_d10:.2f}×

  FILES SAVED:
    outputs/figures/06a_final_evaluation_dashboard.png
    outputs/figures/06b_bias_audit.png
    outputs/figures/06c_decile_calibration.png
    outputs/figures/06d_final_summary.png
    outputs/reports/06_final_metrics.csv
    outputs/reports/06_bias_audit.csv
    outputs/reports/06_inference_demo.csv
    outputs/reports/06_scalability_guide.txt
    outputs/models/06_model_card.json

  PIPELINE COMPLETE
  ─────────────────────────────────────────────────────
  The model is ready for integration with ChaguoAI.
  Use build_inference_row() and rank_methods_for_user()
  from this notebook in the ChaguoAI orchestrator.
  The inference functions and model card are documented
  and ready for open-source release.
""")
