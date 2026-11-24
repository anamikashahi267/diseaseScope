from __future__ import annotations

import io
import os
import zipfile
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import davies_bouldin_score, silhouette_score
from sklearn.preprocessing import StandardScaler
try:
    from .upload_service import (
        evaluate_kmeans_cluster_counts,
        get_upload_record,
        register_upload_routes,
    )
except ImportError:
    from upload_service import (
        evaluate_kmeans_cluster_counts,
        get_upload_record,
        register_upload_routes,
    )


ROOT = Path(__file__).resolve().parent.parent
DATA_ARCHIVE = Path(os.environ.get(
    "DISEASESCOPE_DATA",
    ROOT / "IHME-GBD_2023_DATA-f03f1508-1.zip",
))
N_CLUSTERS = 6
ALGORITHMS = {"kmeans": "K-Means", "hierarchical": "Hierarchical"}


def load_analysis():
    if not DATA_ARCHIVE.is_file():
        raise FileNotFoundError(
            f"Dataset archive not found at {DATA_ARCHIVE}. "
            "Place the supplied IHME GBD 2023 ZIP in the project root or set DISEASESCOPE_DATA."
        )
    with zipfile.ZipFile(DATA_ARCHIVE) as archive:
        csv_files = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not csv_files:
            raise ValueError(f"No CSV file was found inside {DATA_ARCHIVE.name}.")
        with archive.open(csv_files[0]) as source:
            raw = pd.read_csv(source)

    required = {
        "location_id", "location_name", "cause_name", "measure_name",
        "metric_name", "age_name", "sex_name", "year", "val",
    }
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"The supplied CSV is missing required columns: {', '.join(sorted(missing))}.")

    data = raw[
        (raw["measure_name"] == "DALYs (Disability-Adjusted Life Years)")
        & (raw["metric_name"] == "Rate")
        & (raw["age_name"] == "Age-standardized")
        & (raw["sex_name"] == "Both")
        & (raw["year"].astype(str) == "2023")
    ].copy()
    if data.empty:
        raise ValueError("No 2023, both-sex, age-standardized DALY rate rows were found in the CSV.")

    data["val"] = pd.to_numeric(data["val"], errors="coerce")
    data = data.dropna(subset=["val"])
    profiles = data.pivot_table(
        index=["location_id", "location_name"],
        columns="cause_name",
        values="val",
        aggfunc="mean",
    ).sort_index(axis=1)
    profiles = profiles.dropna(axis=0, how="any")
    if len(profiles) <= N_CLUSTERS or profiles.shape[1] < 2:
        raise ValueError(
            f"At least {N_CLUSTERS + 1} complete country profiles and two disease categories "
            f"are required; found {len(profiles)} profiles and {profiles.shape[1]} categories."
        )

    features = profiles.to_numpy(dtype=float)
    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)
    kmeans = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init=20)
    kmeans_labels = kmeans.fit_predict(scaled)
    hierarchical_labels = AgglomerativeClustering(
        n_clusters=N_CLUSTERS, linkage="ward"
    ).fit_predict(scaled)
    pca = PCA(n_components=2, random_state=42)
    coordinates = pca.fit_transform(scaled)

    countries = pd.DataFrame({
        "location_id": profiles.index.get_level_values("location_id").astype(str),
        "country": profiles.index.get_level_values("location_name"),
        **{cause: profiles[cause].to_numpy() for cause in profiles.columns},
        "kmeans_cluster": kmeans_labels + 1,
        "hierarchical_cluster": hierarchical_labels + 1,
        "pca_1": coordinates[:, 0],
        "pca_2": coordinates[:, 1],
    }).reset_index(drop=True)

    metrics = {}
    for key, labels in (("kmeans", kmeans_labels), ("hierarchical", hierarchical_labels)):
        metrics[key] = {
            "silhouette": float(silhouette_score(scaled, labels)),
            "silhouette_manhattan": float(silhouette_score(scaled, labels, metric="manhattan")),
            "davies_bouldin": float(davies_bouldin_score(scaled, labels)),
        }

    wcss = []
    for k in range(2, min(10, len(profiles) - 1) + 1):
        model = KMeans(n_clusters=k, random_state=42, n_init=10).fit(scaled)
        wcss.append({"k": k, "wcss": float(model.inertia_)})

    return {
        "profiles": profiles,
        "countries": countries,
        "causes": list(profiles.columns),
        "scaled": scaled,
        "metrics": metrics,
        "wcss": wcss,
        "pca_variance": [float(value) for value in pca.explained_variance_ratio_],
        "archive_name": DATA_ARCHIVE.name,
    }


ANALYSIS = load_analysis()
app = Flask(__name__)
CORS(app, origins=r"https?://(localhost|127\.0\.0\.1)(:\d+)?")
register_upload_routes(app)


def algorithm_key():
    key = request.args.get("algorithm", "kmeans").lower()
    if key not in ALGORITHMS:
        raise ValueError("algorithm must be 'kmeans' or 'hierarchical'.")
    return key


def json_records(frame):
    return frame.replace({np.nan: None}).to_dict(orient="records")


def active_upload():
    dataset_id = request.args.get("dataset_id")
    if not dataset_id:
        return None, None
    record, error = get_upload_record(dataset_id)
    if error:
        _, status = error
        if status == 404:
            return None, (jsonify({"error": "The active upload is no longer available. Return to the default dataset or upload and analyze the file again."}), 410)
        return None, error
    if record["analysis"] is None:
        return None, (jsonify({"error": "Finish preprocessing and run the uploaded dataset analysis before using it across the dashboard."}), 409)
    return record, None


def active_cluster_count(record=None):
    analysis = record["analysis"] if record else None
    default_count = (
        int(analysis["report"]["n_clusters"]) if analysis else N_CLUSTERS
    )
    requested = request.args.get("active_k")
    if requested is None:
        return default_count
    try:
        count = int(requested)
    except (TypeError, ValueError) as error:
        raise ValueError("active_k must be an integer.") from error
    sample_count = (
        len(analysis["model_values"]) if analysis else len(ANALYSIS["scaled"])
    )
    if not 2 <= count < sample_count:
        raise ValueError(
            f"active_k must be from 2 to {sample_count - 1} for this dataset."
        )
    return count


def _cluster_profile_records(profile_values, country_names, labels):
    assignments = pd.DataFrame({
        "country": country_names,
        "cluster": labels,
    })
    values = profile_values.copy()
    values["cluster"] = labels
    grouped = values.groupby("cluster", sort=True)
    profile_sizes = grouped.size()
    profile_means = grouped.mean(numeric_only=True)
    profiles = [
        {
            "cluster": int(cluster),
            "countries": int(profile_sizes.loc[cluster]),
            **{str(column): float(value) for column, value in means.items()},
        }
        for cluster, means in profile_means.iterrows()
    ]
    return assignments, profiles


@lru_cache(maxsize=32)
def _default_cluster_result(key, cluster_count):
    if key == "kmeans":
        labels = KMeans(
            n_clusters=cluster_count, random_state=42, n_init=10
        ).fit_predict(ANALYSIS["scaled"]) + 1
    else:
        labels = AgglomerativeClustering(
            n_clusters=cluster_count, linkage="ward"
        ).fit_predict(ANALYSIS["scaled"]) + 1
    assignments, profiles = _cluster_profile_records(
        ANALYSIS["profiles"].reset_index(drop=True),
        ANALYSIS["countries"]["country"].tolist(),
        labels,
    )
    return assignments, profiles


def cluster_result(record, key, cluster_count):
    if record is None:
        assignments, profiles = _default_cluster_result(key, cluster_count)
        return {
            "assignments": assignments,
            "profiles": profiles,
            "cluster_count": cluster_count,
        }

    analysis = record["analysis"]
    if cluster_count == int(analysis["report"]["n_clusters"]):
        assignments = analysis["assignments_by_algorithm"][key]
        profiles = analysis["profiles_by_algorithm"][key]
    else:
        cache = analysis.setdefault("cluster_results_by_k", {})
        cache_key = (key, cluster_count)
        if cache_key not in cache:
            if key == "kmeans":
                labels = KMeans(
                    n_clusters=cluster_count, random_state=42, n_init=10
                ).fit_predict(analysis["model_values"])
            else:
                labels = AgglomerativeClustering(
                    n_clusters=cluster_count, linkage="ward"
                ).fit_predict(analysis["model_values"])
            country_profiles = analysis["country_profiles"]
            assignments, profiles = _cluster_profile_records(
                country_profiles[analysis["numeric_selected"]],
                country_profiles["country"].tolist(),
                labels + 1,
            )
            cache[cache_key] = assignments, profiles
        assignments, profiles = cache[cache_key]
    return {
        "assignments": assignments,
        "profiles": profiles,
        "cluster_count": cluster_count,
    }


def active_metrics(record, cluster_count):
    metrics = []
    for key in ALGORITHMS:
        assignments = cluster_result(record, key, cluster_count)["assignments"]
        labels = assignments["cluster"].to_numpy() - 1
        values = (
            record["analysis"]["model_values"]
            if record
            else ANALYSIS["scaled"]
        )
        distinct_clusters = len(np.unique(labels))
        if distinct_clusters < 2 or distinct_clusters >= len(labels):
            metrics.append({
                "algorithm": ALGORITHMS[key],
                "silhouette": None,
                "silhouette_manhattan": None,
                "davies_bouldin": None,
            })
            continue
        metrics.append({
            "algorithm": ALGORITHMS[key],
            "silhouette": float(silhouette_score(
                values, labels, metric="euclidean",
                sample_size=min(2000, len(labels)), random_state=42,
            )),
            "silhouette_manhattan": float(silhouette_score(
                values, labels, metric="manhattan",
                sample_size=min(2000, len(labels)), random_state=42,
            )),
            "davies_bouldin": float(davies_bouldin_score(values, labels)),
        })
    return metrics


@app.errorhandler(ValueError)
def handle_value_error(error):
    return jsonify({"error": str(error)}), 400


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "dataset": ANALYSIS["archive_name"]})


@app.get("/api/summary")
def summary():
    record, error = active_upload()
    if error:
        return error
    if record:
        analysis = record["analysis"]
        countries = analysis["country_profiles"]
        features = analysis["numeric_selected"]
        top = countries[features].mean().sort_values(ascending=False).head(5)
        cluster_count = active_cluster_count(record)
        return jsonify({
            "country_count": int(len(countries)),
            "cause_count": int(len(features)),
            "cluster_count": cluster_count,
            "active_cluster_count": cluster_count,
            "algorithm": ALGORITHMS[analysis["report"]["algorithm"]],
            "algorithm_key": analysis["report"]["algorithm"],
            "causes": features,
            "top_causes": [{"cause": name, "mean_rate": float(value)} for name, value in top.items()],
            "dataset": record["filename"],
            "source": "User-uploaded dataset",
            "data_scope": "Uploaded dataset · analyzed selected features",
            "analysis_note": f"Using the reviewed and analyzed upload '{record['filename']}'. Results reflect the selected preprocessing options and features.",
        })
    countries = ANALYSIS["countries"]
    profiles = ANALYSIS["profiles"]
    top = profiles.mean().sort_values(ascending=False).head(5)
    cluster_count = active_cluster_count()
    return jsonify({
        "country_count": int(len(countries)),
        "cause_count": int(len(ANALYSIS["causes"])),
        "cluster_count": cluster_count,
        "active_cluster_count": cluster_count,
        "algorithm": "K-Means",
        "algorithm_key": "kmeans",
        "causes": ANALYSIS["causes"],
        "top_causes": [{"cause": name, "mean_rate": float(value)} for name, value in top.items()],
        "dataset": ANALYSIS["archive_name"],
        "source": "IHME Global Burden of Disease 2023 dataset supplied with this project",
        "data_scope": "2023, both sexes, age-standardized DALY rate",
        "analysis_note": "Clustering, PCA and metrics are computed at backend startup from the supplied data; saved Colab outputs were not included.",
    })


@app.get("/api/countries")
def country_list():
    record, error = active_upload()
    if error:
        return error
    if record:
        names = record["analysis"]["country_profiles"]["country"].drop_duplicates().tolist()
        return jsonify({"countries": sorted(names)})
    return jsonify({"countries": sorted(ANALYSIS["countries"]["country"].tolist())})


@app.get("/api/countries/<path:country_name>")
def country_detail(country_name):
    record, error = active_upload()
    if error:
        return error
    if record:
        analysis = record["analysis"]
        key = request.args.get("algorithm", "kmeans").lower()
        if key not in ALGORITHMS:
            raise ValueError("algorithm must be 'kmeans' or 'hierarchical'.")
        cluster_count = active_cluster_count(record)
        result = cluster_result(record, key, cluster_count)
        profiles = analysis["country_profiles"]
        found = profiles[profiles["country"].str.casefold() == country_name.casefold()]
        if found.empty:
            return jsonify({"error": f"No analyzed profile was found for '{country_name}'."}), 404
        row = found.iloc[0]
        cluster = int(result["assignments"].iloc[int(row["row"]) - 1]["cluster"])
        cluster_assignments = result["assignments"]
        profile_averages = result["profiles"]
        average = next(item for item in profile_averages if item["cluster"] == cluster)
        causes = analysis["numeric_selected"]
        return jsonify({
            "country": row["country"],
            "location_id": int(row["row"]),
            "profile": [
                {"cause": cause, "rate": float(row[cause]), "cluster_average": float(average[cause])}
                for cause in causes
            ],
            "clusters": {
                algorithm: int(cluster_result(record, algorithm, cluster_count)["assignments"].iloc[int(row["row"]) - 1]["cluster"])
                for algorithm in ALGORITHMS
            },
            "cluster_size": int((cluster_assignments["cluster"] == cluster).sum()),
            "cluster_countries": cluster_assignments.loc[
                cluster_assignments["cluster"] == cluster, "country"
            ].tolist(),
        })
    found = ANALYSIS["countries"][ANALYSIS["countries"]["country"].str.casefold() == country_name.casefold()]
    if found.empty:
        return jsonify({"error": f"No complete profile was found for '{country_name}'."}), 404
    row = found.iloc[0]
    cluster_count = active_cluster_count()
    assignments, cluster_profiles = _default_cluster_result("kmeans", cluster_count)
    profile_row = int(found.index[0])
    cluster = int(assignments.iloc[profile_row]["cluster"])
    cluster_mask = assignments["cluster"] == cluster
    cluster_countries = assignments.loc[cluster_mask, "country"].tolist()
    profile = ANALYSIS["profiles"].loc[
        (ANALYSIS["profiles"].index.get_level_values("location_name") == row["country"])
    ].iloc[0]
    average = next(item for item in cluster_profiles if item["cluster"] == cluster)
    return jsonify({
        "country": row["country"],
        "location_id": row["location_id"],
        "profile": [{"cause": cause, "rate": float(profile[cause]), "cluster_average": float(average[cause])} for cause in ANALYSIS["causes"]],
        "clusters": {
            "kmeans": cluster,
            "hierarchical": int(_default_cluster_result("hierarchical", cluster_count)[0].iloc[profile_row]["cluster"]),
        },
        "cluster_size": len(cluster_countries),
        "cluster_countries": cluster_countries,
    })


@app.get("/api/clusters")
def clusters():
    key = algorithm_key()
    record, error = active_upload()
    if error:
        return error
    cluster_count = active_cluster_count(record)
    result = cluster_result(record, key, cluster_count)
    if record:
        assignments = result["assignments"]
        distribution = assignments["cluster"].value_counts().sort_index()
        return jsonify({
            "algorithm": ALGORITHMS[key],
            "cluster_count": result["cluster_count"],
            "assignments": json_records(assignments.sort_values("country")),
            "distribution": [
                {"cluster": int(cluster), "count": int(count)}
                for cluster, count in distribution.items()
            ],
            "profiles": result["profiles"],
        })
    assignments = result["assignments"]
    distribution = assignments["cluster"].value_counts().sort_index()
    return jsonify({
        "algorithm": ALGORITHMS[key],
        "cluster_count": result["cluster_count"],
        "assignments": json_records(assignments.sort_values("country")),
        "distribution": [
            {"cluster": int(cluster), "count": int(count)}
            for cluster, count in distribution.items()
        ],
        "profiles": result["profiles"],
    })


@app.get("/api/pca")
def pca_data():
    key = algorithm_key()
    record, error = active_upload()
    if error:
        return error
    cluster_count = active_cluster_count(record)
    if record:
        analysis = record["analysis"]
        points = analysis["pca"][["country", "component_1", "component_2"]].copy()
        points["cluster"] = cluster_result(record, key, cluster_count)["assignments"]["cluster"].to_numpy()
        selected = request.args.get("cluster")
        if selected and selected != "all":
            try:
                points = points[points["cluster"] == int(selected)]
            except ValueError as error:
                raise ValueError("cluster must be an integer or 'all'.") from error
        return jsonify({
            "algorithm": ALGORITHMS[key],
            "explained_variance": analysis["pca_variance"],
            "points": json_records(points),
        })
    frame = ANALYSIS["countries"]
    points = frame[["country", "pca_1", "pca_2"]].rename(
        columns={"pca_1": "component_1", "pca_2": "component_2"}
    )
    points["cluster"] = cluster_result(record, key, cluster_count)["assignments"]["cluster"].to_numpy()
    selected = request.args.get("cluster")
    if selected and selected != "all":
        try:
            points = points[points["cluster"] == int(selected)]
        except ValueError as error:
            raise ValueError("cluster must be an integer or 'all'.") from error
    return jsonify({
        "algorithm": ALGORITHMS[key],
        "explained_variance": ANALYSIS["pca_variance"],
        "points": json_records(points),
    })


@app.get("/api/evaluation")
def evaluation():
    record, error = active_upload()
    if error:
        return error
    cluster_count = active_cluster_count(record)
    if record:
        analysis = record["analysis"]
        kmeans_evaluation = evaluate_kmeans_cluster_counts(analysis["model_values"])
        return jsonify({
            "metrics": active_metrics(record, cluster_count),
            "wcss": analysis["wcss"],
            "kmeans_evaluation": kmeans_evaluation,
            "cluster_count": cluster_count,
            "active_cluster_count": cluster_count,
            "distance_note": "Metrics are computed from the analyzed upload and selected features. Manhattan comparison uses hierarchical average linkage; K-Means and WCSS use Euclidean distance.",
            "pca_variance": analysis["pca_variance"],
        })
    kmeans_evaluation = evaluate_kmeans_cluster_counts(ANALYSIS["scaled"])
    return jsonify({
        "metrics": active_metrics(record, cluster_count),
        "wcss": ANALYSIS["wcss"],
        "kmeans_evaluation": kmeans_evaluation,
        "cluster_count": cluster_count,
        "active_cluster_count": cluster_count,
        "distance_note": "Manhattan values are silhouette scores computed on the same labels; K-Means fitting and WCSS use Euclidean distance.",
        "pca_variance": ANALYSIS["pca_variance"],
    })


@app.get("/api/compare")
def compare():
    record, error = active_upload()
    if error:
        return error
    names = request.args.getlist("country")
    if not names:
        names = [name.strip() for name in request.args.get("countries", "").split(",") if name.strip()]
    if len(names) < 2:
        raise ValueError("Select at least two countries to compare.")
    if len(names) > 8:
        raise ValueError("Compare no more than eight countries at a time.")
    if record:
        analysis = record["analysis"]
        cluster_count = active_cluster_count(record)
        frame = analysis["country_profiles"]
        kmeans_assignments = cluster_result(record, "kmeans", cluster_count)["assignments"]
        hierarchical_assignments = cluster_result(record, "hierarchical", cluster_count)["assignments"]
        rows = []
        missing = []
        for name in names:
            matches = frame[frame["country"].str.casefold() == name.casefold()]
            if matches.empty:
                missing.append(name)
                continue
            row = matches.iloc[0]
            row_number = int(row["row"]) - 1
            rows.append({
                "country": row["country"],
                "clusters": {
                    "kmeans": int(kmeans_assignments.iloc[row_number]["cluster"]),
                    "hierarchical": int(hierarchical_assignments.iloc[row_number]["cluster"]),
                },
                "profile": [
                    {"cause": cause, "rate": float(row[cause])}
                    for cause in analysis["numeric_selected"]
                ],
            })
        if missing:
            raise ValueError(f"No analyzed profiles were found for: {', '.join(missing)}.")
        return jsonify({"countries": rows})
    frame = ANALYSIS["countries"]
    cluster_count = active_cluster_count()
    kmeans_assignments = cluster_result(None, "kmeans", cluster_count)["assignments"]
    hierarchical_assignments = cluster_result(None, "hierarchical", cluster_count)["assignments"]
    country_indexes = {
        name.casefold(): index
        for index, name in enumerate(frame["country"].tolist())
    }
    rows = []
    missing = []
    for name in names:
        match = frame[frame["country"].str.casefold() == name.casefold()]
        if match.empty:
            missing.append(name)
            continue
        row = match.iloc[0]
        profile = ANALYSIS["profiles"].loc[
            ANALYSIS["profiles"].index.get_level_values("location_name") == row["country"]
        ].iloc[0]
        rows.append({
            "country": row["country"],
            "clusters": {
                "kmeans": int(kmeans_assignments.iloc[country_indexes[name.casefold()]]["cluster"]),
                "hierarchical": int(hierarchical_assignments.iloc[country_indexes[name.casefold()]]["cluster"]),
            },
            "profile": [{"cause": cause, "rate": float(profile[cause])} for cause in ANALYSIS["causes"]],
        })
    if missing:
        raise ValueError(f"No complete profiles were found for: {', '.join(missing)}.")
    return jsonify({"countries": rows})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
