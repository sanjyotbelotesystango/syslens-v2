"""
utils.py — Shared utilities.

Extends the original utils.py (extract_metadata, save_file).
Added: build_file_fingerprint for sending lightweight dataset
summaries to agents without exposing raw rows.
"""

from __future__ import annotations
import io
import os
from pathlib import Path
from typing import Any, Dict


# ── Original functions (preserved from original utils.py) ─────────────────────

def extract_metadata(file_path: str) -> Dict[str, Any]:
    """
    Read a CSV or Excel file and return columns, types, and 5 sample rows.
    Inherited from original utils.py — signature unchanged.
    """
    import pandas as pd

    path = str(file_path)
    if path.endswith(".csv"):
        df = pd.read_csv(path)
    elif path.endswith((".xlsx", ".xlsm")):
        df = pd.read_excel(path, engine="openpyxl")
    elif path.endswith(".xls"):
        df = pd.read_excel(path, engine="xlrd")
    else:
        raise ValueError(f"Unsupported format. Use .csv, .xls, or .xlsx. Got: {path}")

    df = df.where(df.notna(), None)

    return {
        "file_path":    path,
        "columns":      df.columns.tolist(),
        "column_types": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "sample_data":  df.head(5).to_dict(orient="records"),
    }


def save_file(file_content: bytes, file_name: str, destination_folder: str = "data") -> str:
    """
    Save raw bytes to disk. Returns the saved file path.
    Inherited from original utils.py — signature unchanged.
    """
    os.makedirs(destination_folder, exist_ok=True)
    file_path = os.path.join(destination_folder, file_name)
    with open(file_path, "wb") as f:
        f.write(file_content)
    return file_path


# ── New: file fingerprint for agents ──────────────────────────────────────────

def build_file_fingerprint(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """
    Build a lightweight metadata summary of a CSV/Excel file.
    This is what agents receive instead of raw row data — keeps token usage low.

    Returns a dict with: filename, total_rows, columns (name, type, nulls, unique, sample).
    """
    import pandas as pd

    ext = Path(filename).suffix.lower()

    try:
        if ext == ".csv":
            df_sample = pd.read_csv(io.BytesIO(file_bytes), nrows=200)
            df_full   = pd.read_csv(io.BytesIO(file_bytes))
        elif ext in (".xlsx", ".xlsm"):
            df_sample = pd.read_excel(io.BytesIO(file_bytes), nrows=200, engine="openpyxl")
            df_full   = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
        elif ext == ".xls":
            df_sample = pd.read_excel(io.BytesIO(file_bytes), nrows=200, engine="xlrd")
            df_full   = pd.read_excel(io.BytesIO(file_bytes), engine="xlrd")
        else:
            return {"filename": filename, "error": f"Unsupported extension: {ext}"}
    except Exception as e:
        return {"filename": filename, "error": str(e)}

    columns: Dict[str, Any] = {}
    for col in df_sample.columns[:40]:          # cap at 40 columns
        col_data = df_sample[col].dropna()
        numeric_ratio = pd.to_numeric(col_data, errors="coerce").notna().mean()
        columns[str(col)] = {
            "dtype":      str(df_sample[col].dtype),
            "is_numeric": numeric_ratio >= 0.5,
            "null_count": int(df_sample[col].isna().sum()),
            "unique":     int(df_sample[col].nunique()),
            "sample":     [str(v) for v in col_data.head(6).tolist()],
        }

    return {
        "filename":   filename,
        "total_rows": int(df_full.shape[0]),
        "columns":    columns,
        "first_row":  {str(k): str(v) for k, v in df_sample.iloc[0].items()} if len(df_sample) > 0 else {},
    }