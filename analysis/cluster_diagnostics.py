"""Describe partition geometry and algorithm agreement in standardized feature space."""

import numpy as np
from sklearn.cluster import DBSCAN, AgglomerativeClustering
from sklearn.metrics import (
    adjusted_rand_score,
    calinski_harabasz_score,
    davies_bouldin_score,
    silhouette_score,
)


def canonical_labels(values, labels):
    groups = sorted(
        set(labels) - {-1}, key=lambda label: tuple(values[labels == label].mean(axis=0))
    )
    mapping = {label: index for index, label in enumerate(groups)}
    return np.array([mapping.get(label, -1) for label in labels], dtype=int)


def partition_metrics(values, labels):
    included = labels >= 0
    points, fitted = values[included], labels[included]
    count = len(set(fitted))
    result = {
        "clusters": count,
        "noise_runs": int((~included).sum()),
        "noise_fraction": float((~included).mean()),
        "silhouette": None,
        "davies_bouldin": None,
        "calinski_harabasz": None,
        "score_scope": "non_noise_runs_in_standardized_feature_space",
    }
    if 1 < count < len(points):
        result.update(
            silhouette=float(silhouette_score(points, fitted)),
            davies_bouldin=float(davies_bouldin_score(points, fitted)),
            calinski_harabasz=float(calinski_harabasz_score(points, fitted)),
        )
    return result


def compare_partitions(values, kmeans):
    agglomerative = canonical_labels(
        values, AgglomerativeClustering(n_clusters=2, linkage="ward").fit_predict(values)
    )
    density = canonical_labels(
        values, DBSCAN(eps=1.5, min_samples=3, algorithm="brute", n_jobs=1).fit_predict(values)
    )
    result = {}
    for name, labels in (("kmeans", kmeans), ("agglomerative", agglomerative), ("dbscan", density)):
        result[name] = {
            **partition_metrics(values, labels),
            "adjusted_rand_agreement_with_kmeans": float(adjusted_rand_score(kmeans, labels)),
        }
    return (
        agglomerative,
        density,
        {
            "partitions": result,
            "agglomerative": {"clusters": 2, "linkage": "ward"},
            "dbscan": {"eps": 1.5, "min_samples": 3, "noise_label": -1},
            "interpretation": "internal geometry and algorithm agreement, not predictive accuracy",
        },
    )
