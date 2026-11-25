"""Exact per-prediction explanations for the Random Forest by tree-path decomposition.

For every tree, the probability at the leaf equals the root probability plus the change made by
each split on the decision path; attributing each change to the split's feature gives an exact
additive decomposition (Saabas, "Interpreting random forests", 2014). Averaging over trees gives

    predicted probability == base value + sum(feature contributions)

for the actual model output. This was chosen over the SHAP package to avoid its numba/llvmlite/
pandas dependency chain in the Windows bundle; contributions are model-faithful but, unlike
TreeSHAP, are not order-symmetric, which is documented as a limitation.
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline


def decompose(
    pipeline: Pipeline, raw_features: np.ndarray, output_index: int
) -> tuple[float, np.ndarray, float]:
    """Return ``(base_value, contributions, probability)`` for one row and one label."""
    forest = pipeline[-1]
    if not isinstance(forest, RandomForestClassifier):
        raise TypeError("Explanations are only supported for RandomForestClassifier pipelines.")
    x = pipeline[:-1].transform(raw_features.reshape(1, -1))
    classes = forest.classes_[output_index] if forest.n_outputs_ > 1 else forest.classes_
    positive = np.flatnonzero(np.asarray(classes) == 1)
    contributions = np.zeros(x.shape[1])
    if positive.size == 0:
        return 0.0, contributions, 0.0
    column = int(positive[0])
    base = 0.0
    for estimator in forest.estimators_:
        tree = estimator.tree_
        values = tree.value[:, output_index, :]
        totals = values.sum(axis=1, keepdims=True)
        probabilities = np.divide(values, totals, out=np.zeros_like(values), where=totals > 0)
        path = estimator.decision_path(x).indices
        node_probability = probabilities[path, column]
        base += node_probability[0]
        np.add.at(contributions, tree.feature[path[:-1]], np.diff(node_probability))
    count = len(forest.estimators_)
    base /= count
    contributions /= count
    return float(base), contributions, float(base + contributions.sum())
