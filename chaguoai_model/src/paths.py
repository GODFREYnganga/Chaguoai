""" 
Central Path management for ChaguoAI model.

All paths are resolved relative to the project root.This means the code runs identically on any machine, any Operating system, and any hostig environment
"""

from pathlib import Path

def get_project_root() -> Path:
    """
    Return the absolute path to the project root directory.
    """
    return Path(__file__).resolve().parent.parent

# Core directory paths
PROJECT_ROOT = get_project_root()
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_PROC_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
MODELS_DIR = OUTPUTS_DIR /"models"
FIGURES_DIR = OUTPUTS_DIR / "figures"
REPORTS_DIR = OUTPUTS_DIR / "reports"
DOCS_DIR = PROJECT_ROOT / "docs"


def ensure_output_dirs():
    """
    Create all output directories if they don't exist.
    Safe to call multiple times(exist_ok=True).
    Call this at the start of any script that writes files.
    """
    for directory in [DATA_PROC_DIR, MODELS_DIR, REPORTS_DIR, DOCS_DIR]:
        directory.mkdir(parents=True, exist_ok=True)

def get_raw_csv_paths() -> list:
    """
    Walk the entire data/raw directory and return paths to all csv files.    
    """
    return sorted(DATA_RAW_DIR.rglob("*.csv"))

def get_processed_path(filename:str) -> Path:
    """
    Return the full path for a processed data fiile.
    """
    return DATA_PROC_DIR / filename

def get_model_path(model_name: str, timestamp: str) -> Path:
    """
    Return the full path for a saved model file.
    """
    return MODELS_DIR / f"{model_name}_{timestamp}.pkl"

def get_figure_path(figure_name:str) -> Path:
    """Return the full path for a saved figure"""
    return FIGURES_DIR / f"{figure_name}.png"

def get_report_path(report_name: str) -> Path:
    """Return the full path for a saved report. """
    return REPORTS_DIR / f"{report_name}.csv"

