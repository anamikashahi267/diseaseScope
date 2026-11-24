from __future__ import annotations

import io
import json
import math
import re
import secrets
import threading
import time
import unicodedata
import zipfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from flask import jsonify, request, send_file
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import davies_bouldin_score, silhouette_score
from sklearn.preprocessing import StandardScaler
from werkzeug.utils import secure_filename


MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ROWS = 50_000
MAX_COLUMNS = 100
MAX_ANALYSIS_ROWS = 5_000
SILHOUETTE_SAMPLE_SIZE = 2_000
MAX_ACTIVE_UPLOADS = 8
UPLOAD_TTL_SECONDS = 60 * 60
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
COUNTRY_COLUMN_NAMES = {
    "country", "countryname", "location", "locationname",
    "country_name", "location_name",
}
_UPLOADS = {}
_UPLOADS_LOCK = threading.RLock()


def _json_value(value):
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        value = value.item()
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _records(frame):
    return [
        {str(key): _json_value(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def evaluate_kmeans_cluster_counts(model_values, max_k=10):
    values = np.asarray(model_values, dtype=float)
    if values.ndim != 2 or values.shape[1] == 0:
        raise ValueError("K-Means evaluation requires a two-dimensional feature matrix.")
    if not np.isfinite(values).all():
        raise ValueError("K-Means evaluation requires finite feature values.")
    if (
        isinstance(max_k, bool)
        or not isinstance(max_k, (int, np.integer))
        or not 2 <= max_k <= 10
    ):
        raise ValueError("Maximum K must be an integer from 2 through 10.")
    if len(values) < 3:
        raise ValueError("At least three samples are required to evaluate K-Means.")

    silhouette_sample_size = min(SILHOUETTE_SAMPLE_SIZE, len(values))
    scores = []
    for candidate_k in range(2, min(int(max_k), len(values) - 1) + 1):
        model = KMeans(
            n_clusters=candidate_k, random_state=42, n_init=10
        ).fit(values)
        labels = model.labels_
        distinct_clusters = len(np.unique(labels))
        if distinct_clusters < 2 or distinct_clusters >= len(values):
            scores.append({
                "k": candidate_k,
                "wcss": float(model.inertia_),
                "silhouette": None,
                "davies_bouldin": None,
                "valid": False,
                "reason": "K-Means produced an invalid number of distinct clusters.",
            })
            continue

        silhouette = float(silhouette_score(
            values,
            labels,
            metric="euclidean",
            sample_size=silhouette_sample_size,
            random_state=42,
        ))
        davies_bouldin = float(davies_bouldin_score(values, labels))
        if not math.isfinite(silhouette) or not math.isfinite(davies_bouldin):
            scores.append({
                "k": candidate_k,
                "wcss": float(model.inertia_),
                "silhouette": silhouette if math.isfinite(silhouette) else None,
                "davies_bouldin": (
                    davies_bouldin if math.isfinite(davies_bouldin) else None
                ),
                "valid": False,
                "reason": "A clustering metric was not finite for this K.",
            })
            continue

        scores.append({
            "k": candidate_k,
            "wcss": float(model.inertia_),
            "silhouette": silhouette,
            "davies_bouldin": davies_bouldin,
            "valid": True,
            "reason": None,
        })

    valid_scores = [score for score in scores if score["valid"]]
    if not valid_scores:
        raise ValueError(
            "No valid K-Means evaluations are available for this dataset."
        )

    silhouette_ranks = {
        score["k"]: rank
        for rank, score in enumerate(
            sorted(valid_scores, key=lambda score: (-score["silhouette"], score["k"])),
            start=1,
        )
    }
    davies_bouldin_ranks = {
        score["k"]: rank
        for rank, score in enumerate(
            sorted(valid_scores, key=lambda score: (score["davies_bouldin"], score["k"])),
            start=1,
        )
    }

    elbow_k = None
    if len(valid_scores) >= 3:
        first_wcss = valid_scores[0]["wcss"]
        last_wcss = valid_scores[-1]["wcss"]
        wcss_range = first_wcss - last_wcss
        if wcss_range > 0:
            count = len(valid_scores)
            elbow_k = max(
                valid_scores,
                key=lambda score: (
                    1 - (score["wcss"] - last_wcss) / wcss_range
                    - (score["k"] - valid_scores[0]["k"]) / (count - 1),
                    -score["k"],
                ),
            )["k"]

    recommended = min(
        valid_scores,
        key=lambda score: (
            silhouette_ranks[score["k"]]
            + davies_bouldin_ranks[score["k"]]
            + (0 if score["k"] == elbow_k else 1),
            score["k"],
        ),
    )["k"]
    return {
        "scores": scores,
        "recommended_k": recommended,
        "elbow_k": elbow_k,
        "sample_count": int(len(values)),
        "silhouette_sample_size": silhouette_sample_size,
        "max_k_evaluated": max(score["k"] for score in scores),
        "selection_method": (
            "The recommendation combines equal-weight ranks for higher Silhouette "
            "and lower Davies–Bouldin, with a one-rank preference for the Elbow "
            "Method K when a knee is detectable. Ties favor smaller K."
        ),
    }


def _missing_mask(series):
    mask = series.isna()
    if series.dtype == object or pd.api.types.is_string_dtype(series):
        mask = mask | series.astype("string").str.strip().eq("").fillna(False)
    return mask


def _column_key(value):
    return "".join(char for char in unicodedata.normalize("NFKC", str(value)).casefold() if char.isalnum())


def _country_column(frame):
    lookup = {_column_key(column): column for column in frame.columns}
    for candidate in COUNTRY_COLUMN_NAMES:
        found = lookup.get(_column_key(candidate))
        if found is not None:
            return found
    return None


def _inspect(frame):
    country = _country_column(frame)
    numeric = frame.select_dtypes(include=[np.number]).columns.tolist()
    categorical = [column for column in frame.columns if column not in numeric]
    missing = []
    for column in frame.columns:
        missing_mask = _missing_mask(frame[column])
        missing.append({
            "column": str(column),
            "missing": int(missing_mask.sum()),
            "percent": float(missing_mask.mean() * 100),
        })
    empty_columns = [
        str(column) for column in frame.columns
        if _missing_mask(frame[column]).all()
    ]
    duplicate_count = int(frame.duplicated().sum())
    inconsistent_types = []
    invalid_numeric = []
    infinite_values = []
    outliers = []
    numeric_candidates = list(numeric)

    for column in frame.columns:
        series = frame[column]
        if pd.api.types.is_numeric_dtype(series):
            values = pd.to_numeric(series, errors="coerce")
            infinite_count = int(np.isinf(values.to_numpy(dtype=float, na_value=np.nan)).sum())
            if infinite_count:
                infinite_values.append({"column": str(column), "count": infinite_count})
            candidate_values = values.replace([np.inf, -np.inf], np.nan).dropna()
            if len(candidate_values) >= 4:
                q1, q3 = candidate_values.quantile([0.25, 0.75])
                spread = q3 - q1
                if spread > 0:
                    count = int(((candidate_values < q1 - 1.5 * spread) | (candidate_values > q3 + 1.5 * spread)).sum())
                    if count:
                        outliers.append({"column": str(column), "count": count})
        elif series.dtype == object or pd.api.types.is_string_dtype(series):
            nonempty = series.dropna().astype(str).str.strip()
            nonempty = nonempty[nonempty.ne("")]
            numeric_values = pd.to_numeric(nonempty, errors="coerce")
            convertible = int(numeric_values.notna().sum())
            numeric_name = column != country and bool(re.search(
                r"\b(rate|value|score|count|daly|burden|mortality|prevalence|incidence)\b",
                str(column),
                flags=re.IGNORECASE,
            ))
            if convertible or numeric_name:
                numeric_candidates.append(column)
                invalid_count = int(numeric_values.isna().sum())
                if invalid_count:
                    inconsistent_types.append({
                        "column": str(column),
                        "numeric_values": convertible,
                        "non_numeric_values": invalid_count,
                    })
                    invalid_numeric.append({"column": str(column), "count": invalid_count})
                finite_values = numeric_values.dropna()
                infinite_count = int(np.isinf(finite_values.to_numpy(dtype=float)).sum())
                if infinite_count:
                    infinite_values.append({"column": str(column), "count": infinite_count})
                finite_values = finite_values.replace([np.inf, -np.inf], np.nan).dropna()
                if len(finite_values) >= 4:
                    q1, q3 = finite_values.quantile([0.25, 0.75])
                    spread = q3 - q1
                    if spread > 0:
                        count = int(((finite_values < q1 - 1.5 * spread) | (finite_values > q3 + 1.5 * spread)).sum())
                        if count:
                            outliers.append({"column": str(column), "count": count})

    country_count = None
    country_variants = []
    if country is not None:
        names = frame[country].dropna().astype(str).str.strip()
        country_count = int(names[names.ne("")].nunique())
        normalized = defaultdict(set)
        for name in names[names.ne("")].unique():
            key = " ".join(unicodedata.normalize("NFKC", name).casefold().split())
            normalized[key].add(name)
        country_variants = [
            {"normalized_name": key, "variants": sorted(values)}
            for key, values in normalized.items() if len(values) > 1
        ]
    numeric_candidates = [column for column in numeric_candidates if column != country]

    safe_frame = frame.replace([np.inf, -np.inf], np.nan)
    for column in safe_frame.columns:
        if safe_frame[column].dtype == object or pd.api.types.is_string_dtype(safe_frame[column]):
            safe_frame[column] = safe_frame[column].mask(_missing_mask(safe_frame[column]), np.nan)
    summary = safe_frame.describe(include="all").T
    summary_records = [
        {
            "feature": str(feature),
            "statistics": {str(name): _json_value(value) for name, value in row.items()},
        }
        for feature, row in summary.iterrows()
    ]
    report_rows = []
    for column in frame.columns:
        report_rows.append({
            "column": str(column),
            "dtype": str(frame[column].dtype),
            "missing": int(frame[column].isna().sum()),
            "unique": int(frame[column].nunique(dropna=True)),
            "empty": str(column) in empty_columns,
        })

    return {
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "worksheet_names": frame.attrs.get("worksheet_names", []),
        "selected_worksheet": frame.attrs.get("selected_worksheet"),
        "column_names": [str(column) for column in frame.columns],
        "column_details": report_rows,
        "numeric_columns": [str(column) for column in numeric],
        "categorical_columns": [str(column) for column in categorical],
        "numeric_count": len(numeric),
        "categorical_count": len(categorical),
        "numeric_candidates": list(dict.fromkeys(str(column) for column in numeric_candidates)),
        "country_column": str(country) if country is not None else None,
        "country_count": country_count,
        "missing_values": missing,
        "duplicate_rows": duplicate_count,
        "empty_columns": empty_columns,
        "inconsistent_types": inconsistent_types,
        "invalid_numeric_values": invalid_numeric,
        "infinite_values": infinite_values,
        "outliers": outliers,
        "country_name_variants": country_variants,
        "summary_statistics": summary_records,
        "first_five": _records(frame.head(5)),
        "last_five": _records(frame.tail(5)),
        "data_quality": {
            "missing_cells": int(sum(_missing_mask(frame[column]).sum() for column in frame.columns)),
            "duplicate_rows": duplicate_count,
            "empty_columns": len(empty_columns),
            "inconsistent_type_columns": len(inconsistent_types),
            "invalid_numeric_cells": int(sum(item["count"] for item in invalid_numeric)),
            "infinite_cells": int(sum(item["count"] for item in infinite_values)),
            "outlier_values": int(sum(item["count"] for item in outliers)),
            "country_name_variant_groups": len(country_variants),
        },
    }


def _decode_upload(filename, content):
    suffix = Path(filename).suffix.lower()
    if suffix == ".zip":
        if not zipfile.is_zipfile(io.BytesIO(content)):
            raise ValueError("The .zip file is not a valid archive.")
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = [info for info in archive.infolist() if not info.is_dir()]
                expanded_size = sum(info.file_size for info in entries)
                if expanded_size > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("Archive expands beyond the 100 MB safety limit.")
                candidates = [
                    info for info in entries
                    if Path(info.filename).suffix.lower() in ALLOWED_EXTENSIONS
                ]
                if not candidates:
                    raise ValueError("The ZIP archive must contain one .csv, .xlsx, or .xls dataset.")
                if len(candidates) > 1:
                    raise ValueError("The ZIP archive contains multiple CSV/Excel files. Keep only the dataset you want to analyze.")
                member = candidates[0]
                if member.file_size > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("The dataset inside the archive exceeds the 100 MB safety limit.")
                inner_content = archive.read(member)
        except ValueError:
            raise
        except (OSError, RuntimeError, zipfile.BadZipFile) as error:
            raise ValueError(f"Could not read the ZIP archive: {error}") from error
        return _decode_upload(member.filename, inner_content)
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported file type. Upload a .csv, .xlsx, .xls, or .zip file.")
    if not content:
        raise ValueError("The uploaded file is empty.")
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("File exceeds the 20 MB upload limit.")
    if suffix == ".csv":
        try:
            frame = pd.read_csv(io.BytesIO(content), nrows=MAX_ROWS + 1, encoding="utf-8-sig")
        except UnicodeDecodeError:
            try:
                frame = pd.read_csv(io.BytesIO(content), nrows=MAX_ROWS + 1, encoding="cp1252")
            except Exception as error:
                raise ValueError(f"Could not read the CSV: {error}") from error
        except Exception as error:
            raise ValueError(f"Could not read the CSV: {error}") from error
    elif suffix == ".xlsx":
        if not zipfile.is_zipfile(io.BytesIO(content)):
            raise ValueError("The .xlsx file is not a valid Excel workbook.")
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                expanded_size = sum(info.file_size for info in archive.infolist())
                if expanded_size > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("Workbook expands beyond the 100 MB safety limit.")
                if any(Path(info.filename).suffix.lower() in {".vba", ".bin"} and "vba" in info.filename.lower() for info in archive.infolist()):
                    raise ValueError("Macro-enabled workbooks are not accepted.")
            workbook = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
            frame = workbook.parse(sheet_name=0, nrows=MAX_ROWS + 1)
            frame.attrs["worksheet_names"] = workbook.sheet_names
            frame.attrs["selected_worksheet"] = workbook.sheet_names[0]
        except ValueError:
            raise
        except Exception as error:
            raise ValueError(f"Could not read the Excel workbook: {error}") from error
    else:
        if not content.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
            raise ValueError("The .xls file does not have a valid Excel workbook signature.")
        try:
            workbook = pd.ExcelFile(io.BytesIO(content), engine="xlrd")
            frame = workbook.parse(sheet_name=0, nrows=MAX_ROWS + 1)
            frame.attrs["worksheet_names"] = workbook.sheet_names
            frame.attrs["selected_worksheet"] = workbook.sheet_names[0]
        except Exception as error:
            raise ValueError(f"Could not read the Excel workbook: {error}") from error

    if len(frame) > MAX_ROWS:
        raise ValueError(f"Dataset exceeds the {MAX_ROWS:,}-row processing limit.")
    if len(frame.columns) > MAX_COLUMNS:
        raise ValueError(f"Dataset exceeds the {MAX_COLUMNS}-column processing limit.")
    if len(frame.columns) == 0:
        raise ValueError("The file does not contain any columns.")
    frame.columns = [str(column).strip() or f"Unnamed column {index + 1}" for index, column in enumerate(frame.columns)]
    if len(set(frame.columns)) != len(frame.columns):
        duplicates = frame.columns[frame.columns.duplicated()].unique().tolist()
        raise ValueError(f"Column names must be unique. Duplicate names: {', '.join(duplicates)}.")
    if frame.empty:
        raise ValueError("The file contains column headers but no data rows.")
    return frame


def _cleanup_expired():
    now = time.time()
    expired = [key for key, value in _UPLOADS.items() if now - value["created_at"] > UPLOAD_TTL_SECONDS]
    for key in expired:
        _UPLOADS.pop(key, None)


def _get_upload(dataset_id):
    with _UPLOADS_LOCK:
        _cleanup_expired()
        record = _UPLOADS.get(dataset_id)
        if record is None:
            return None
        return record


def _require_upload(dataset_id):
    record = _get_upload(dataset_id)
    if record is None:
        return None, (jsonify({"error": "Upload not found or expired. Upload the dataset again."}), 404)
    return record, None


def get_upload_record(dataset_id):
    return _require_upload(dataset_id)


def _preprocess(record, options):
    frame = record["original"].copy()
    if options.get("remove_duplicates", False):
        frame = frame.drop_duplicates().copy()

    feature_columns = options.get("features") or []
    categorical_columns = options.get("categorical_features") or []
    if not isinstance(feature_columns, list) or not isinstance(categorical_columns, list):
        raise ValueError("Selected feature lists must be arrays of column names.")
    if any(not isinstance(name, str) for name in feature_columns + categorical_columns):
        raise ValueError("Selected feature names must be strings.")
    if len(set(feature_columns)) != len(feature_columns) or len(set(categorical_columns)) != len(categorical_columns):
        raise ValueError("Selected feature lists cannot contain duplicate columns.")
    available = set(frame.columns)
    invalid = [str(name) for name in feature_columns + categorical_columns if name not in available]
    if invalid:
        raise ValueError(f"Selected columns are not in the dataset: {', '.join(invalid)}.")
    if set(feature_columns).intersection(categorical_columns):
        raise ValueError("A column cannot be selected as both a numeric and categorical feature.")
    if not feature_columns and not categorical_columns:
        raise ValueError("Select at least two numerical disease features before analysis.")

    selected = feature_columns + categorical_columns
    country = _country_column(frame)
    if country in selected:
        raise ValueError("The country/location label cannot be used as a model feature.")
    for column in feature_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in categorical_columns:
        if frame[column].dtype == object or pd.api.types.is_string_dtype(frame[column]):
            frame[column] = frame[column].mask(_missing_mask(frame[column]), np.nan)
    strategy = options.get("missing_strategy", "none")
    if strategy not in {"none", "drop_rows", "mean", "median", "mode"}:
        raise ValueError("Missing-value strategy must be none, drop_rows, mean, median, or mode.")
    missing_before = int(frame[selected].isna().sum().sum())
    if strategy == "drop_rows":
        frame = frame.dropna(subset=selected).copy()
    elif strategy in {"mean", "median", "mode"}:
        for column in selected:
            if not frame[column].isna().any():
                continue
            if strategy == "mean" and column in feature_columns:
                fill = frame[column].mean()
            elif strategy == "median" and column in feature_columns:
                fill = frame[column].median()
            else:
                values = frame[column].dropna()
                fill = values.mode(dropna=True).iloc[0] if not values.empty else np.nan
            if pd.isna(fill):
                raise ValueError(f"Column '{column}' contains only missing values and cannot be imputed.")
            frame[column] = frame[column].fillna(fill)
    remaining = int(frame[selected].isna().sum().sum())
    if remaining:
        raise ValueError(
            f"{remaining} missing or invalid values remain in selected features. "
            "Choose a missing-value strategy or review the selected columns."
        )
    if feature_columns and not frame[feature_columns].apply(
        lambda column: np.isfinite(pd.to_numeric(column, errors="coerce")).all()
    ).all():
        raise ValueError("Selected features contain infinite or invalid numerical values. Resolve them before analysis.")

    encoded = pd.DataFrame(index=frame.index)
    if feature_columns:
        encoded = frame[feature_columns].astype(float)
    encoding_details = []
    for column in categorical_columns:
        distinct = int(frame[column].nunique(dropna=False))
        if distinct > 50:
            raise ValueError(
                f"Categorical feature '{column}' has {distinct} categories. "
                "Choose a lower-cardinality feature (50 or fewer) before one-hot encoding."
            )
        dummy = pd.get_dummies(frame[column].astype(str), prefix=str(column), dtype=float)
        encoded = pd.concat([encoded, dummy], axis=1)
        encoding_details.append({"column": str(column), "categories": distinct, "encoded_features": int(dummy.shape[1])})
    encoded = encoded.replace([np.inf, -np.inf], np.nan)
    if encoded.shape[1] < 2:
        raise ValueError("At least two model features are required after encoding.")
    if len(encoded) < 3:
        raise ValueError("At least three complete rows are required for clustering.")

    return frame, encoded, {
        "rows_before": int(len(record["original"])),
        "rows_after": int(len(frame)),
        "duplicates_removed": int(len(record["original"]) - len(record["original"].drop_duplicates())) if options.get("remove_duplicates", False) else 0,
        "missing_before": missing_before,
        "missing_strategy": strategy,
        "numeric_features": [str(column) for column in feature_columns],
        "categorical_features": [str(column) for column in categorical_columns],
        "categorical_encoding": encoding_details,
        "model_feature_names": [str(column) for column in encoded.columns],
        "standardized": bool(options.get("standardize", True)),
    }


def _run_analysis(record, options):
    frame, raw_features, preprocessing = _preprocess(record, options)
    if len(frame) > MAX_ANALYSIS_ROWS:
        raise ValueError(
            f"Clustering is limited to {MAX_ANALYSIS_ROWS:,} rows per analysis to keep "
            "hierarchical clustering responsive. The full uploaded dataset remains available for inspection."
        )
    n_clusters = options.get("n_clusters", 4)
    try:
        converted_clusters = int(n_clusters)
    except (TypeError, ValueError) as error:
        raise ValueError("Number of clusters must be an integer.") from error
    if isinstance(n_clusters, float) and not n_clusters.is_integer():
        raise ValueError("Number of clusters must be an integer.")
    n_clusters = converted_clusters
    if not 2 <= n_clusters < len(frame):
        raise ValueError(f"Number of clusters must be from 2 to {len(frame) - 1} for this dataset.")
    algorithm = options.get("algorithm", "kmeans")
    if algorithm not in {"kmeans", "hierarchical"}:
        raise ValueError("Algorithm must be kmeans or hierarchical.")

    values = raw_features.to_numpy(dtype=float)
    scaler = StandardScaler()
    model_values = scaler.fit_transform(values) if options.get("standardize", True) else values.copy()
    kmeans_model = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    kmeans_labels = kmeans_model.fit_predict(model_values)
    hierarchical_euclidean = AgglomerativeClustering(n_clusters=n_clusters, linkage="ward").fit_predict(model_values)
    hierarchical_manhattan = AgglomerativeClustering(
        n_clusters=n_clusters, linkage="average", metric="manhattan"
    ).fit_predict(model_values)
    labels = kmeans_labels if algorithm == "kmeans" else hierarchical_euclidean
    actual_clusters = len(np.unique(labels))
    if actual_clusters < 2 or actual_clusters >= len(frame):
        raise ValueError("The selected settings produced invalid cluster labels; choose different features or K.")

    def metric_values(candidate_labels):
        if len(np.unique(candidate_labels)) < 2 or len(np.unique(candidate_labels)) >= len(candidate_labels):
            return {
                "silhouette_euclidean": None,
                "silhouette_manhattan": None,
                "davies_bouldin": None,
            }
        silhouette_euclidean = float(silhouette_score(
                model_values, candidate_labels, metric="euclidean",
                sample_size=min(SILHOUETTE_SAMPLE_SIZE, len(candidate_labels)), random_state=42,
            ))
        silhouette_manhattan = float(silhouette_score(
                model_values, candidate_labels, metric="manhattan",
                sample_size=min(SILHOUETTE_SAMPLE_SIZE, len(candidate_labels)), random_state=42,
            ))
        davies_bouldin = float(davies_bouldin_score(model_values, candidate_labels))
        return {
            "silhouette_euclidean": silhouette_euclidean if math.isfinite(silhouette_euclidean) else None,
            "silhouette_manhattan": silhouette_manhattan if math.isfinite(silhouette_manhattan) else None,
            "davies_bouldin": davies_bouldin if math.isfinite(davies_bouldin) else None,
        }

    metrics = [
        {"algorithm": "K-Means", "distance": "Euclidean", **(metric_values(kmeans_labels) or {})},
        {"algorithm": "Hierarchical", "distance": "Euclidean / Ward", **(metric_values(hierarchical_euclidean) or {})},
        {"algorithm": "Hierarchical", "distance": "Manhattan / Average", **(metric_values(hierarchical_manhattan) or {})},
    ]
    wcss = []
    for candidate_k in range(2, min(10, len(frame) - 1) + 1):
        candidate = KMeans(n_clusters=candidate_k, random_state=42, n_init=5).fit(model_values)
        wcss.append({"k": candidate_k, "wcss": float(candidate.inertia_)})

    pca = PCA(n_components=2, random_state=42)
    coordinates = pca.fit_transform(model_values)
    country_column = _country_column(frame)
    if country_column:
        country_names = frame[country_column].fillna("").astype(str).tolist()
    else:
        country_names = [f"Row {index + 1}" for index in range(len(frame))]
    cluster_labels = {
        "kmeans": kmeans_labels + 1,
        "hierarchical": hierarchical_euclidean + 1,
    }
    assignments = pd.DataFrame({
        "country": country_names,
        "cluster": labels + 1,
    })
    pca_results = pd.DataFrame({
        "row": np.arange(len(frame)) + 1,
        "country": country_names,
        "cluster": labels + 1,
        "kmeans_cluster": cluster_labels["kmeans"],
        "hierarchical_cluster": cluster_labels["hierarchical"],
        "component_1": coordinates[:, 0],
        "component_2": coordinates[:, 1],
    })

    profile_values = raw_features.copy()
    profile_values["cluster"] = labels + 1
    profiles = profile_values.groupby("cluster", sort=True).mean(numeric_only=True).reset_index()
    profile_records = []
    for _, row in profiles.iterrows():
        cluster_id = int(row["cluster"])
        profile_records.append({
            "cluster": cluster_id,
            "countries": int(np.sum(labels + 1 == cluster_id)),
            **{str(column): _json_value(value) for column, value in row.items() if column != "cluster"},
        })
    profiles_by_algorithm = {}
    assignments_by_algorithm = {}
    for key, candidate_labels in cluster_labels.items():
        candidate_profiles = raw_features.copy()
        candidate_profiles["cluster"] = candidate_labels
        grouped = candidate_profiles.groupby("cluster", sort=True).mean(numeric_only=True).reset_index()
        profiles_by_algorithm[key] = [
            {
                "cluster": int(row["cluster"]),
                "countries": int(np.sum(candidate_labels == int(row["cluster"]))),
                **{str(column): _json_value(value) for column, value in row.items() if column != "cluster"},
            }
            for _, row in grouped.iterrows()
        ]
        assignments_by_algorithm[key] = pd.DataFrame({
            "country": country_names,
            "cluster": candidate_labels,
        })

    numeric_selected = [column for column in options.get("features", []) if column in frame.columns]
    distribution_data = {
        str(column): {
            "mean": float(frame[column].mean()),
            "median": float(frame[column].median()),
            "std": float(frame[column].std()) if len(frame) > 1 else 0.0,
            "min": float(frame[column].min()),
            "max": float(frame[column].max()),
        }
        for column in numeric_selected
    }
    histograms = {}
    for column in numeric_selected:
        counts, edges = np.histogram(
            frame[column].to_numpy(dtype=float),
            bins=min(15, max(5, int(np.sqrt(len(frame))))),
        )
        histograms[str(column)] = [
            {"range": f"{edges[index]:.3g}–{edges[index + 1]:.3g}", "count": int(counts[index])}
            for index in range(len(counts))
        ]
    correlations = frame[numeric_selected].corr().replace([np.inf, -np.inf], np.nan) if len(numeric_selected) >= 2 else pd.DataFrame()
    report = {
        "dataset": record["filename"],
        "rows_analyzed": int(len(frame)),
        "features_used": preprocessing["model_feature_names"],
        "algorithm": algorithm,
        "n_clusters": n_clusters,
        "preprocessing": preprocessing,
        "metrics": metrics,
        "wcss": wcss,
        "pca_variance": [float(value) for value in pca.explained_variance_ratio_],
        "quality": _inspect(frame)["data_quality"],
        "silhouette_sample_size": min(SILHOUETTE_SAMPLE_SIZE, len(frame)),
    }
    country_profiles = raw_features.copy()
    country_profiles.insert(0, "country", country_names)
    country_profiles.insert(0, "row", np.arange(len(frame)) + 1)
    country_profiles["cluster"] = labels + 1

    return {
        "cleaned": frame,
        "model_values": model_values,
        "assignments": assignments,
        "profiles": profiles,
        "profile_records": profile_records,
        "profiles_by_algorithm": profiles_by_algorithm,
        "assignments_by_algorithm": assignments_by_algorithm,
        "pca": pca_results,
        "metrics": metrics,
        "wcss": wcss,
        "pca_variance": [float(value) for value in pca.explained_variance_ratio_],
        "correlations": correlations,
        "numeric_selected": numeric_selected,
        "distributions": distribution_data,
        "histograms": histograms,
        "country_profiles": country_profiles,
        "report": report,
        "preprocessing": preprocessing,
    }


def _csv_safe(frame):
    exported = frame.copy()
    dangerous = ("=", "+", "-", "@", "\t", "\r")
    for column in exported.select_dtypes(include=["object", "string"]).columns:
        exported[column] = exported[column].map(
            lambda value: "'" + value if isinstance(value, str) and value.startswith(dangerous) else value
        )
    return exported


def register_upload_routes(app):
    app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_BYTES

    @app.errorhandler(413)
    def upload_too_large(_error):
        return jsonify({"error": "File exceeds the 20 MB upload limit."}), 413

    @app.post("/api/uploads")
    def upload_dataset():
        if "file" not in request.files:
            return jsonify({"error": "Choose a CSV, Excel, or ZIP file to upload."}), 400
        upload = request.files["file"]
        safe_name = secure_filename(upload.filename or "")
        if not safe_name:
            return jsonify({"error": "The uploaded file must have a valid filename."}), 400
        content = upload.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            return jsonify({"error": "File exceeds the 20 MB upload limit."}), 413
        try:
            frame = _decode_upload(safe_name, content)
            inspection = _inspect(frame)
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        except Exception as error:
            app.logger.exception("Dataset upload inspection failed")
            return jsonify({"error": f"Could not inspect this dataset: {error}"}), 400

        dataset_id = secrets.token_urlsafe(32)
        with _UPLOADS_LOCK:
            _cleanup_expired()
            if len(_UPLOADS) >= MAX_ACTIVE_UPLOADS:
                return jsonify({"error": "Upload capacity is currently full. Remove an existing upload or try again later."}), 429
            _UPLOADS[dataset_id] = {
                "created_at": time.time(),
                "filename": safe_name,
                "content": content,
                "original": frame,
                "inspection": inspection,
                "analysis": None,
            }
        response = jsonify({
            "dataset_id": dataset_id,
            "filename": safe_name,
            "file_size": len(content),
            "uploaded_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "inspection": inspection,
        })
        response.headers["Cache-Control"] = "no-store"
        return response, 201

    @app.get("/api/uploads/<dataset_id>/inspection")
    def inspect_upload(dataset_id):
        record, error = _require_upload(dataset_id)
        if error:
            return error
        response = jsonify({
            "dataset_id": dataset_id,
            "filename": record["filename"],
            "file_size": len(record["content"]),
            "inspection": record["inspection"],
            "analysis_ready": record["analysis"] is not None,
        })
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/uploads/<dataset_id>/results")
    def get_upload_results(dataset_id):
        record, error = _require_upload(dataset_id)
        if error:
            return error
        analysis = record["analysis"]
        if analysis is None:
            return jsonify({"error": "Run analysis to generate results."}), 409
        response = jsonify({
            "report": analysis["report"],
            "assignments": _records(analysis["assignments"].head(100)),
            "profiles": analysis["profile_records"],
            "pca": _records(analysis["pca"][["row", "country", "cluster", "component_1", "component_2"]]),
            "correlations": {
                "features": [str(column) for column in analysis["correlations"].columns],
                "matrix": [
                    [_json_value(value) for value in row]
                    for row in analysis["correlations"].to_numpy()
                ],
            },
            "distributions": analysis["distributions"],
            "histograms": analysis["histograms"],
            "country_names": _records(analysis["country_profiles"][["row", "country"]]),
        })
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/uploads/<dataset_id>/countries")
    def search_upload_countries(dataset_id):
        record, error = _require_upload(dataset_id)
        if error:
            return error
        if record["analysis"] is None:
            return jsonify({"error": "Run analysis before searching country profiles."}), 409
        query = request.args.get("q", "").strip().casefold()
        names = record["analysis"]["country_profiles"][["row", "country"]]
        if query:
            names = names[names["country"].str.casefold().str.contains(query, regex=False)]
        response = jsonify({"countries": _records(names.head(100))})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/uploads/<dataset_id>/country-profile")
    def upload_country_profile(dataset_id):
        record, error = _require_upload(dataset_id)
        if error:
            return error
        if record["analysis"] is None:
            return jsonify({"error": "Run analysis before inspecting country profiles."}), 409
        try:
            row_number = int(request.args.get("row", ""))
        except ValueError as exception:
            raise ValueError("row must be a one-based row number returned by the country search API.") from exception
        profile = record["analysis"]["country_profiles"]
        match = profile[profile["row"] == row_number]
        if match.empty:
            return jsonify({"error": "No analyzed country profile exists for that row."}), 404
        response = jsonify({"profile": _records(match)})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/uploads/<dataset_id>/preview")
    def preview_preprocessing(dataset_id):
        record, error = _require_upload(dataset_id)
        if error:
            return error
        options = request.get_json(silent=True)
        if options is None:
            options = {}
        if not isinstance(options, dict):
            return jsonify({"error": "Preprocessing options must be a JSON object."}), 400
        try:
            cleaned, _features, summary = _preprocess(record, options)
        except ValueError as exception:
            return jsonify({"error": str(exception)}), 400
        response = jsonify({
            "preview": _records(cleaned.head(10)),
            "rows_after": int(len(cleaned)),
            "columns": [str(column) for column in cleaned.columns],
            "preprocessing": summary,
        })
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/uploads/<dataset_id>/analyze")
    def analyze_upload(dataset_id):
        record, error = _require_upload(dataset_id)
        if error:
            return error
        options = request.get_json(silent=True)
        if options is None:
            options = {}
        if not isinstance(options, dict):
            return jsonify({"error": "Analysis options must be a JSON object."}), 400
        try:
            result = _run_analysis(record, options)
        except ValueError as exception:
            return jsonify({"error": str(exception)}), 400
        except Exception as exception:
            app.logger.exception("Uploaded dataset analysis failed")
            return jsonify({"error": f"Analysis failed: {exception}"}), 400
        with _UPLOADS_LOCK:
            record["analysis"] = result
        response = jsonify({
            "report": result["report"],
            "assignments": _records(result["assignments"].head(100)),
            "profiles": result["profile_records"],
            "pca": _records(result["pca"]),
            "correlations": {
                "features": [str(column) for column in result["correlations"].columns],
                "matrix": [
                    [_json_value(value) for value in row]
                    for row in result["correlations"].to_numpy()
                ],
            },
            "distributions": result["distributions"],
            "histograms": result["histograms"],
            "country_names": _records(result["country_profiles"][["row", "country"]]),
        })
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/uploads/<dataset_id>/export/<kind>")
    def export_upload(dataset_id, kind):
        record, error = _require_upload(dataset_id)
        if error:
            return error
        analysis = record["analysis"]
        if kind == "original":
            payload = io.BytesIO(record["content"])
            suffix = Path(record["filename"]).suffix.lower()
            mimetype = {
                ".csv": "text/csv",
                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ".xls": "application/vnd.ms-excel",
                ".zip": "application/zip",
            }[suffix]
            download_name = record["filename"]
        else:
            if analysis is None:
                return jsonify({"error": "Run analysis before downloading processed results."}), 409
            tables = {
                "cleaned": analysis["cleaned"],
                "quality-report": pd.DataFrame(record["inspection"]["column_details"]),
                "assignments": analysis["assignments"],
                "profiles": analysis["profiles"],
                "pca": analysis["pca"],
                "metrics": pd.DataFrame(
                    [
                        {
                            "record_type": "model_metric",
                            "k": analysis["report"]["n_clusters"],
                            "wcss": None,
                            **metric,
                        }
                        for metric in analysis["metrics"]
                    ] + [
                        {
                            "record_type": "kmeans_wcss",
                            "k": value["k"],
                            "wcss": value["wcss"],
                            "algorithm": "K-Means",
                            "distance": "Euclidean",
                            "silhouette_euclidean": None,
                            "silhouette_manhattan": None,
                            "davies_bouldin": None,
                        }
                        for value in analysis["wcss"]
                    ]
                ),
            }
            if kind == "report":
                export = analysis["report"]
                download_name = "diseasescope-analysis-report.json"
                mimetype = "application/json"
                payload = io.BytesIO(json.dumps(export, indent=2, ensure_ascii=False).encode("utf-8"))
            elif kind == "quality-report":
                export = {
                    "filename": record["filename"],
                    "inspection": record["inspection"],
                    "post_preprocessing_quality": analysis["report"]["quality"],
                    "preprocessing": analysis["preprocessing"],
                }
                download_name = "diseasescope-data-quality-report.json"
                mimetype = "application/json"
                payload = io.BytesIO(json.dumps(export, indent=2, ensure_ascii=False).encode("utf-8"))
            elif kind in tables:
                csv_data = _csv_safe(tables[kind]).to_csv(index=False).encode("utf-8-sig")
                payload = io.BytesIO(csv_data)
                mimetype = "text/csv"
                download_name = f"diseasescope-{kind}.csv"
            else:
                return jsonify({"error": "Unknown export type."}), 404
        payload.seek(0)
        response = send_file(payload, mimetype=mimetype, as_attachment=True, download_name=download_name)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.delete("/api/uploads/<dataset_id>")
    def remove_upload(dataset_id):
        with _UPLOADS_LOCK:
            _cleanup_expired()
            if _UPLOADS.pop(dataset_id, None) is None:
                return jsonify({"error": "Upload not found or already removed."}), 404
        return jsonify({"removed": True})
