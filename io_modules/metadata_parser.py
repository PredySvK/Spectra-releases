# io_modules/metadata_parser.py
"""
Streamlined metadata engine that processes a single primary flat metadata sheet.
Maps Excel rows to UNV files based on case-insensitive partial filename substrings.
Maintains pristine original Excel column names and strict index insertion order.
All internal documentation strings and variable labels are standardly written in English.
"""

import os
from typing import Any, Dict, Optional

import pandas as pd

from io_modules.measurement_files import has_measurement_suffix


def normalize_file_key(name: str) -> str:
    """Case-insensitive, extension-independent identity for a filename."""
    cleaned = str(name).strip()
    if has_measurement_suffix(cleaned):
        return os.path.splitext(cleaned)[0].lower()
    return cleaned.lower()


def build_normalized_lookup(metadata_db: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Re-keys a filename->row database (as parsed straight from Excel) by
    `normalize_file_key`, so a run can be linked by an exact, case- and
    extension-independent match instead of an unanchored substring search.
    """
    lookup: Dict[str, Dict[str, Any]] = {}
    for key, row in metadata_db.items():
        norm_key = normalize_file_key(key)
        if norm_key not in lookup:
            lookup[norm_key] = row
    return lookup


def find_matching_row(file_key: str, lookup: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Finds the Excel row for a scanned file's normalized key.

    An exact match wins outright. Failing that, the excel key must be a
    *prefix* of the file key, followed by a separator -- this is what lets
    "Setup1-Sweep1-1" in the sheet still describe a file the pipeline saved as
    "Setup1-Sweep1-1_Processed.unv", without letting "data_4" match
    "data_41" (no separator follows "data_4" there). When several excel
    keys qualify, the longest -- the most specific -- one wins.
    """
    exact = lookup.get(file_key)
    if exact is not None:
        return exact

    best_key = None
    for excel_key in lookup:
        if best_key is not None and len(excel_key) <= len(best_key):
            continue
        if not file_key.startswith(excel_key):
            continue
        if file_key[len(excel_key)] in ("_", "-", " "):
            best_key = excel_key

    return lookup[best_key] if best_key is not None else None


class AccMetadataParser:
    """
    Streamlined metadata engine that processes a single primary flat metadata sheet.
    Maps Excel rows to UNV files based on case-insensitive partial filename substrings.
    """

    def __init__(self, excel_path: str):
        self.excel_path = excel_path

    def parse_and_link_metadata(self) -> Dict[str, Dict[str, Any]]:
        """
        Scans sheets to find the primary flat database layout containing 'File Name',
        converts its records into standard primitives, and keys them by filename.
        """
        if not os.path.exists(self.excel_path):
            return {}

        try:
            # Read all cells across all sheets as raw strings to prevent decimal conversions.
            # Closed immediately after -- everything needed is now in sheets_dict, and an
            # open file handle left dangling until garbage collection is what produced the
            # "unclosed file" ResourceWarning on exit.
            with pd.ExcelFile(self.excel_path) as xls:
                sheets_dict = {sheet: xls.parse(sheet, dtype=str) for sheet in xls.sheet_names}

            target_df = None
            filename_original_column_key = None

            # 1. Look for the single flat sheet that contains the filename anchor column
            for sheet_name, df in sheets_dict.items():
                # --- THE CRITICAL FIX: Do NOT overwrite df.columns directly! ---
                # We scan column definitions non-destructively to identify the anchor
                has_filename_anchor = False

                for col in df.columns:
                    c_clean = str(col).strip().lower().replace(" ", "").replace("_", "").replace("-", "")
                    if c_clean == "filename":
                        has_filename_anchor = True
                        filename_original_column_key = col  # Lock the exact original column casing pointer
                        break

                # If this sheet contains the filename anchor, we select it as our single database sheet
                if has_filename_anchor:
                    target_df = df

                    # Normalize cell values utilizing pristine original column header handles
                    for col in target_df.columns:
                        target_df[col] = target_df[col].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
                        target_df[col] = target_df[col].replace(['nan', 'None', '', '<na>'], pd.NA)
                    break

            if target_df is None or filename_original_column_key is None:
                print("METADATA_WARN: Excel loaded but no flat sheet contains a 'File Name' column layout.")
                return {}

            # 2. Convert the chosen flat dataframe into our filename-keyed dictionary database
            # orient="records" perfectly respects the natural left-to-right spreadsheet columns insertion order
            compiled_rows = target_df.to_dict(orient="records")
            metadata_database = {}

            for row in compiled_rows:
                # Retrieve cell contents via the verified original exact filename key dictionary slot
                filename_cell_value = row.get(filename_original_column_key)

                if filename_cell_value and not pd.isna(filename_cell_value):
                    file_key = str(filename_cell_value).strip()

                    # Clean out pandas/numpy nan objects into standard safe python primitives
                    # Preserves original capitalization and symbols (e.g., 'Rotor Temp [°C]')
                    clean_row = {}
                    for k, v in row.items():
                        if pd.isna(v) or str(v).lower() in ["nan", "none", "<na>"]:
                            clean_row[k] = None
                        else:
                            clean_row[k] = v

                    metadata_database[file_key] = clean_row

            return metadata_database

        except Exception as e:
            print(f"METADATA_ERROR: Critical failure parsing primary flat Excel sheet. Trace: {str(e)}")
            return {}












