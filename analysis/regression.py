"""Nested block validation of design-based Ridge and Lasso latency models."""

import warnings

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import Lasso, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GridSearchCV, GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from threadpoolctl import threadpool_limits

FEATURES = ["policy", "requested_mbps", "flows"]
ALPHAS = [0.01, 0.1, 1.0, 10.0]
PREDICTION_COLUMNS = [
    "run_id",
    "block",
    "policy",
    "model",
    "observed_ms",
    "predicted_ms",
    "baseline_ms",
    "outer_fold",
    "selected_alpha",
]


def _search(name, groups):
    design = ColumnTransformer(
        [
            (
                "policy",
                OneHotEncoder(
                    categories=[["fifo", "fq_codel", "cake_best_effort", "cake_bounded"]],
                    drop="first",
                    sparse_output=False,
                    handle_unknown="error",
                ),
                ["policy"],
            ),
            ("numeric", "passthrough", ["requested_mbps", "flows"]),
        ]
    )
    estimator = (
        Ridge(solver="svd")
        if name == "ridge"
        else Lasso(max_iter=10000, tol=1e-6, selection="cyclic")
    )
    pipeline = Pipeline([("design", design), ("scale", StandardScaler()), ("model", estimator)])
    return GridSearchCV(
        pipeline,
        {"model__alpha": ALPHAS},
        scoring="neg_mean_absolute_error",
        cv=GroupKFold(n_splits=min(3, groups)),
        n_jobs=1,
        error_score="raise",
    )


def regress_runs(matched: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows = matched.sort_values("run_id").copy()
    blocks = rows.block.nunique()
    base = {
        "target": "added_p99_ms",
        "features": FEATURES,
        "minimum_blocks": 6,
        "blocks": int(blocks),
        "purpose": "exploratory_design_interpolation",
        "outer_split": "GroupKFold_by_recorded_block",
        "inner_split": "GroupKFold_by_training_block",
        "alphas": ALPHAS,
        "eligible_for_primary": False,
    }
    if blocks < 6:
        return pd.DataFrame(columns=PREDICTION_COLUMNS), {
            **base,
            "status": "unavailable_fewer_than_six_blocks",
        }
    if rows.added_p99_ms.isna().any() or not np.isfinite(rows.added_p99_ms).all():
        return pd.DataFrame(columns=PREDICTION_COLUMNS), {
            **base,
            "status": "unavailable_missing_target",
        }
    predictions, models = [], {}
    with threadpool_limits(limits=1), warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        for name in ("ridge", "lasso"):
            results, metadata = _fit_model(name, rows)
            predictions.extend(results)
            models[name] = metadata
    return pd.DataFrame(predictions, columns=PREDICTION_COLUMNS), {
        **base,
        "status": "exploratory_fit",
        "models": models,
    }


def _fit_model(name, rows):
    features, target, groups = rows[FEATURES], rows.added_p99_ms.to_numpy(), rows.block.to_numpy()
    prediction, baseline = np.zeros(len(rows)), np.zeros(len(rows))
    records = []
    folds = GroupKFold(n_splits=min(5, rows.block.nunique()))
    partitions = []
    for fold, (train, test) in enumerate(folds.split(features, target, groups)):
        search = _search(name, len(set(groups[train])))
        search.fit(features.iloc[train], target[train], groups=groups[train])
        prediction[test] = search.predict(features.iloc[test])
        baseline[test] = target[train].mean()
        train_blocks, test_blocks = sorted(set(groups[train])), sorted(set(groups[test]))
        partitions.append({"train_blocks": train_blocks, "test_blocks": test_blocks})
        for index in test:
            records.append(
                {
                    "run_id": rows.iloc[index].run_id,
                    "block": groups[index],
                    "policy": rows.iloc[index].policy,
                    "model": name,
                    "observed_ms": float(target[index]),
                    "predicted_ms": float(prediction[index]),
                    "baseline_ms": float(baseline[index]),
                    "outer_fold": fold,
                    "selected_alpha": float(search.best_params_["model__alpha"]),
                }
            )
    final = _search(name, rows.block.nunique())
    final.fit(features, target, groups=groups)
    names = final.best_estimator_.named_steps["design"].get_feature_names_out()
    coefficients = final.best_estimator_.named_steps["model"].coef_
    return records, {
        "mae_ms": float(mean_absolute_error(target, prediction)),
        "rmse_ms": float(np.sqrt(mean_squared_error(target, prediction))),
        "r2": float(r2_score(target, prediction)),
        "mean_baseline_mae_ms": float(mean_absolute_error(target, baseline)),
        "outer_folds": partitions,
        "full_data_alpha": float(final.best_params_["model__alpha"]),
        "full_data_coefficients_per_feature_sd": dict(
            zip(names.tolist(), coefficients.tolist(), strict=True)
        ),
        "coefficient_scope": "full-data descriptive fit; coefficients are not causal effects",
    }
