"""
Dataset discovery module.

walks all CSV under data/raw/ and produces a full inventory of every column across every file. Tun this first before any other step. It tells what you have before you try to use it.

usage:
    from src.discovery import run_full_discovery
    inventory_df, candidates_df = run_full_discovery()
"""

import json
import warnings
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import missingno as msno

warnings.filterwarnings('ignore')

from paths import (
    get_raw_csv_paths, get_report_path, get_figure_path, ensure_output_dirs
)

def profile_single_csv(csv_path) -> dict:
    """
    Load one CSV and extract a complete profile of its contents.
    Returns a dict with file metadata and a column-by-column breakdown of data types, missing rates, and sample values.
    """
    dataframe = None
    last_error = None
    for enc in ['utf-8', 'latin1', 'cp1252', 'utf-8-sig']:
        try:
            dataframe = pd.read_csv(csv_path, encoding=enc, low_memory=False)
            last_error = None
            break
        except Exception as error: 
            last_error = error
            continue
    if dataframe is None:           
            return {
                "study_folder": csv_path.parent.name,
                "file_name": csv_path.name,
                "file_path": str(csv_path),
                "load_error": str(last_error),
                "num_rows": 0,
                "num_columns": 0,
                "column_detail": "[]",
            }
    num_rows, num_columns =dataframe.shape
    column_profiles = []

    for column_name in dataframe.columns:
        column_series = dataframe[column_name]
        num_missing = int(column_series.isna().sum())
        pct_missing = round(num_missing / num_rows *100, 1) if num_rows > 0 else 100.0
        num_unique = int(column_series.nunique())
        data_type = str(column_series.dtype)

        #collect up to 5 non-null unique sample values
        sample_values = column_series.dropna().unique()[:5].tolist()

        column_detail = {
            "column_name": column_name,
            "data_type": data_type,
            "num_missing": num_missing,
            "pct_missing": pct_missing,
            "num_unique_vals": num_unique,
            "sample_values": str(sample_values),
        }

        #Add numerical statistics when applicable
        if pd.api.types.is_numeric_dtype(column_series) and num_missing < num_rows:
            column_detail["value_min"]= round(float(column_series.min()),2)
            column_detail["value_max"] = round(float(column_series.max()), 2)
            column_detail["value_mean"] = round(float(column_series.mean()), 2)

        else:
            column_detail["value_min"] = None
            column_detail["value_max"] = None
            column_detail["value_mean"] = None

        column_profiles.append(column_detail)

    return {
        "study_folder": csv_path.parent.name,
        "file_name": csv_path.name,
        "file_path": str(csv_path),
        "load_error": None,
        "num_rows": num_rows,
        "num_columns": num_columns,
        "columns_detail": json.dumps(column_profiles),
    }

def run_full_discovery() -> tuple:
    """
    Discover all CSV files under data/raw/ and produce two reports:

    1. full_inventory.csv: one row per CSV file with metadata
    2. contraception_column_candidates.csv: columns that likely relate to contraception, family planning, or reproductive health
    """

    ensure_output_dirs()

    all_csv_paths = get_raw_csv_paths()
    print(f"Found {len(all_csv_paths)} CSV files in data/raw/\n")

    if not all_csv_paths:
        print("!!! Error: No CSV files found. Check your 'data/raw' folder. !!!")
        return pd.DataFrame(), pd.DataFrame()
    print(f"found {len(all_csv_paths)} CSV files in data/raw/\n")

    file_profiles = []
    for csv_path in all_csv_paths:
        print(f"Profiling: {csv_path.parent.name}/{csv_path.name}")
        file_profiles.append(profile_single_csv(csv_path))

    inventory_df = pd.DataFrame(file_profiles)

    #save inventory report

    inventory_path = get_report_path("full_inventory")
    inventory_df.to_csv(inventory_path, index=False)
    print(f"\nInventory saved: {inventory_path}")

    # Print summary table

    summary = inventory_df[["study_folder", "file_name", "num_rows", "num_columns", "load_error"]]

    print("DISCOVERY SUMMARY")
    print(summary.to_string(index=False))

    # Find contraception-related column candidates

    candidates_df = find_contraception_column_candidates(inventory_df)
    candidates_path = get_report_path("contraception_column_candidates")
    candidates_df.to_csv(candidates_path, index=False)
    print(f"\nContraception column candidates saved: {candidates_path}")
    print(f"Found {len(candidates_df)} candidate columns across all files")

    return inventory_df, candidates_df

def find_contraception_column_candidates(inventory_df: pd.DataFrame) -> pd.DataFrame:
    """
    Scan column names and sample values across all files for columns likely related to contraception or reproductive health.

    uses keyword matching because survey columns like q4_5_ cannot be decoded by name alone. Flags candidates for manual review.
    """

    search_keywords = ["method", "contracep", "family", "plan", "fp", "inject", "implant", "iud", "pill", "condom", "discontinu", "stop", "switch", "side", "effect", "reason", "parity", "preg", "birth", "menses", "abortion", "miscarriage", "antenatal", "postnatal",
    ]

    candidate_rows = []

    for _, file_row in inventory_df.iterrows():
        if file_row["load_error"]:
            continue
        column_profiles = json.loads(file_row["columns_detail"])

        for col_profile in column_profiles:
            column_name_lower = col_profile["column_name"].lower()
            sample_values_lower = str(col_profile["sample_values"]).lower()

            matched_keyword = None
            for keyword in search_keywords:
                if keyword in column_name_lower or keyword in sample_values_lower:
                    matched_keyword = keyword
                    break

            if matched_keyword:
                candidate_rows.append({
                    "file_name":  file_row["file_name"],
                    "study_folder": file_row["study_folder"],
                    "column_name": col_profile["column_name"],
                    "data_type": col_profile["data_type"],
                    "num_unique_vals": col_profile["num_unique_vals"],
                    "pct_missing": col_profile["pct_missing"],
                    "value_min": col_profile.get("value_min"),
                    "value_max": col_profile.get("value_max"),
                    "sample_values": col_profile["sample_values"],
                    "matched_keyword": matched_keyword,
                    })
                


    return pd.DataFrame(candidate_rows)

def visualize_missing_data(csv_relative_path:str):
    """
    plot missing data heatmap for a specific CSV file. 
    Helps to decide which columns to keep vs drop.
    """

    from paths import DATA_RAW_DIR
    full_path = DATA_RAW_DIR / csv_relative_path

    dataframe = pd.read_csv(full_path, low_memory=False)
    print(f"Loaded {full_path.name}: {dataframe.shape}")

    fig, ax = plt.subplots(figsize=(14,6))
    msno.matrix(dataframe, ax=ax, sparkline=False, color=(0.16,0.66,0.56))

    ax.set_title(f"Missing Data Pattern: {full_path.name}", fontsize=13)

    figure_name = f"missing_data{full_path.stem}"
    plt.savefig(get_figure_path(figure_name), dpi=150, bbox_inches='tight')
    plt.show()
    print(f"Figure saved: {get_figure_path(figure_name)}")

if __name__ == "__main__":
    # This calls the actual logic when you run the file directly
    inventory, candidates = run_full_discovery()
    print("\n Discovery Complete")












        