"""
ChaguoAI — Shared Configuration Module
=======================================
Single source of truth for paths, constants, and value mappings.
Every notebook imports from here. Nothing is hardcoded anywhere else.

To run on a new machine or cloud environment:
  Set CHAGUOAI_DATA_DIR and CHAGUOAI_OUTPUTS_DIR env variables,
  OR leave unset to use defaults relative to this file.
"""

import os
from pathlib import Path


# ── PATH RESOLUTION ────────────────────────────────────────────────────────────

def get_project_root() -> Path:
    """Resolve project root regardless of which notebook calls this."""
    return Path(__file__).resolve().parent.parent


def get_paths() -> dict:
    """
    Return all project paths as a dict of Path objects.
    Override via environment variables:
        CHAGUOAI_DATA_DIR     — folder containing raw CSV files
        CHAGUOAI_OUTPUTS_DIR  — folder for all generated outputs
    """
    root = get_project_root()
    data_dir    = Path(os.getenv("CHAGUOAI_DATA_DIR",    str(root / "data" / "raw")))
    outputs_dir = Path(os.getenv("CHAGUOAI_OUTPUTS_DIR", str(root / "outputs")))

    paths = {
        "data_dir":      data_dir,
        "css_path":      data_dir / "Client_Service_Statistics.csv",
        "outputs_dir":   outputs_dir,
        "figures_dir":   outputs_dir / "figures",
        "reports_dir":   outputs_dir / "reports",
        "processed_dir": outputs_dir / "processed",
    }
    for key in ["figures_dir", "reports_dir", "processed_dir"]:
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


# ── COLUMN SELECTION ───────────────────────────────────────────────────────────

COLUMNS_TO_LOAD = [
    "visitid", "uniqueid", "organization", "county", "delivery",
    "year", "month", "gender", "age", "educationlevel",
    "noofchildren", "fertilityintention", "fpstatus",
    "previousmethod", "methodadopted", "counseled",
]

EXCLUDED_COLUMNS = {
    "serialnumber":      "Facility admin ID — no predictive signal",
    "facilityname":      "84.3% missing — unusable",
    "division":          "23 divisions — too granular; county is sufficient",
    "client_age":        "Bucketed age — redundant with numeric age column",
    "client_age2":       "Second bucketed age — redundant",
    "no_children":       "Bucketed parity — redundant with noofchildren",
    "new_counselled":    "Binary collapse of counseled — redundant",
    "projectstatus":     "Same as fpstatus — redundant",
    "projectfpstatus":   "Mixes FP status with project status — not needed",
    "prev_fp":           "3-bucket collapse of previousmethod — we derive own categories",
    "fp_adopted":        "3-bucket collapse of methodadopted — we derive own categories",
    "lapm":              "Derivable from methodadopted — redundant",
    "delivery_channel":  "2-bucket collapse of delivery — redundant",
    "referred":          "71.6% missing — unusable",
    "fp_referred":       "73.2% missing — unusable",
    "pillquantity":      "76.3% missing — unusable",
    "condomquantity":    "58.2% missing — unusable",
}

MISSING_SENTINEL_COLUMNS = [
    "educationlevel", "fertilityintention", "counseled",
    "previousmethod", "fpstatus",
]

PLANNED_REMOVAL_METHODS = {"Removal_Implant", "Removal_Implants", "Removal_IUCD"}
OFFSCOPE_METHODS         = {"Other RH services", "Vasectomy", "Missing"}

METHOD_CATEGORY_MAP = {
    "Injectables":    "short_acting_hormonal",
    "Pills":          "short_acting_hormonal",
    "Pills & Condoms":"short_acting_hormonal",
    "Implants":       "long_acting_reversible",
    "IUCD":           "long_acting_reversible",
    "BTL":            "permanent",
    "Condoms":        "barrier",
}

EDUCATION_ORDINAL = {
    "Primary Incomplete": 1,
    "Primary Complete":   2,
    "Secondary & Above":  3,
}

FERTILITY_ORDINAL = {
    "Within 2 Years":     1,
    "Later than 2 years": 2,
    "No more Children":   3,
}

COUNSELED_BINARY = {
    "Yes":        1,
    "Refreshers": 1,
    "No":         0,
}

MONTH_ORDER = {
    "January":1,"February":2,"March":3,"April":4,
    "May":5,"June":6,"July":7,"August":8,
    "September":9,"October":10,"November":11,"December":12
}

DELIVERY_BINARY = {
    "Household": "community",
    "Outreach":  "community",
    "Facility":  "facility",
}

RANDOM_SEED = 42
TRAIN_RATIO = 0.70
VAL_RATIO   = 0.15
TEST_RATIO  = 0.15
MIN_AUC_ROC = 0.65
MIN_RECALL  = 0.50
AGE_MIN     = 10
AGE_MAX     = 60
PARITY_CAP  = 15

PALETTE = {
    "teal":"#2A9D8F","coral":"#E76F51","amber":"#E9C46A",
    "navy":"#264653","sage":"#52796F","red":"#C62828",
    "gray":"#9E9E9E","purple":"#7B5EA7",
}

METHOD_COLORS = {
    "short_acting_hormonal":  "#E76F51",
    "long_acting_reversible": "#2A9D8F",
    "barrier":                "#E9C46A",
    "permanent":              "#264653",
    "other":                  "#9E9E9E",
    "unknown":                "#9E9E9E",
}

PLOT_STYLE = {
    "figure.facecolor":"white","axes.facecolor":"white",
    "axes.spines.top":False,"axes.spines.right":False,
    "font.family":"sans-serif","font.size":11,
    "axes.titlesize":13,"axes.titleweight":"bold",
    "axes.labelsize":11,"xtick.labelsize":10,
    "ytick.labelsize":10,"figure.dpi":120,
}