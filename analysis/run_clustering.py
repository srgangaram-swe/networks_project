"""Exploratory run profiles within a fixed offered-load and flow-count condition."""

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from analysis.cluster_diagnostics import compare_partitions

FEATURES = (
    "p99_ms",
    "goodput_mbps",
    "jitter_ms",
    "send_lag_p99_ms",
    "timeout_rate",
    "not_sent_rate",
)
COLUMNS = (
    "run_id",
    "policy",
    "block",
    "requested_mbps",
    "flows",
    "cluster",
    "centroid_distance",
    "pc1",
    "pc2",
    "tsne1",
    "tsne2",
    "agglomerative_cluster",
    "dbscan_cluster",
)


def _fit(group: pd.DataFrame, seed: int) -> tuple[list[dict], dict]:
    values = group[list(FEATURES)].to_numpy(float)
    if not np.isfinite(values).all():
        return [], {"status": "unavailable_missing_features"}
    if len(np.unique(values, axis=0)) < 2:
        return [], {"status": "unavailable_insufficient_variation"}
    scaler = StandardScaler()
    normalized = scaler.fit_transform(values)
    with threadpool_limits(limits=1):
        model = KMeans(n_clusters=2, random_state=seed, n_init=10, max_iter=100, algorithm="lloyd")
        labels = model.fit_predict(normalized)
        projection = PCA(n_components=2, svd_solver="full")
        points = projection.fit_transform(normalized)
        silhouette = float(silhouette_score(normalized, labels))
        perplexity = min(30.0, (len(group) - 1) / 3)
        embedding = TSNE(
            n_components=2,
            perplexity=perplexity,
            init="pca",
            learning_rate="auto",
            max_iter=1000,
            random_state=seed,
            n_jobs=1,
        ).fit_transform(normalized)
    order = sorted(range(2), key=lambda i: tuple(model.cluster_centers_[i]))
    canonical = {label: index for index, label in enumerate(order)}
    with threadpool_limits(limits=1):
        canonical_kmeans = np.array([canonical[int(label)] for label in labels])
        agglomerative, density, diagnostics = compare_partitions(normalized, canonical_kmeans)
    distances = np.linalg.norm(normalized - model.cluster_centers_[labels], axis=1)
    rows = []
    for index, row in enumerate(group.to_dict("records")):
        rows.append(
            {
                **{key: row[key] for key in COLUMNS[:5]},
                "cluster": canonical[int(labels[index])],
                "centroid_distance": float(distances[index]),
                "pc1": float(points[index, 0]),
                "pc2": float(points[index, 1]),
                "tsne1": float(embedding[index, 0]),
                "tsne2": float(embedding[index, 1]),
                "agglomerative_cluster": int(agglomerative[index]),
                "dbscan_cluster": int(density[index]),
            }
        )
    return rows, {
        "status": "exploratory_fit",
        "diagnostics": diagnostics,
        "silhouette": silhouette,
        "standardization_mean": scaler.mean_.tolist(),
        "standardization_scale": scaler.scale_.tolist(),
        "centroids_original_units": scaler.inverse_transform(
            model.cluster_centers_[order]
        ).tolist(),
        "pca_explained_variance_ratio": projection.explained_variance_ratio_.tolist(),
        "iterations": int(model.n_iter_),
        "tsne": {
            "perplexity": perplexity,
            "seed": seed,
            "init": "pca",
            "learning_rate": "auto",
            "max_iter": 1000,
            "purpose": "visualization_only",
        },
    }


def cluster_runs(summaries: pd.DataFrame, seed: int = 561) -> tuple[pd.DataFrame, dict]:
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("clustering requires an unsigned 32-bit seed")
    rows, groups = [], []
    for (load, flows), group in summaries[summaries["flows"] > 0].groupby(
        ["requested_mbps", "flows"], sort=True
    ):
        group = group.sort_values("run_id")
        result, details = ([], {"status": "unavailable_fewer_than_eight_runs"})
        if len(group) >= 8:
            result, details = _fit(group, seed)
        rows.extend(result)
        groups.append(
            {"requested_mbps": float(load), "flows": int(flows), "runs": len(group), **details}
        )
    return pd.DataFrame(rows, columns=COLUMNS), {
        "method": "standardized_kmeans",
        "clusters": 2,
        "seed": seed,
        "n_init": 10,
        "max_iter": 100,
        "features": list(FEATURES),
        "groups": groups,
        "purpose": "exploratory_description_only",
        "automatic_exclusions": False,
        "predictive_validation": "not_performed",
        "eligible_for_primary": False,
    }
