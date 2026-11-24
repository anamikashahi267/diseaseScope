import unittest

import numpy as np
from sklearn.cluster import KMeans
from sklearn.datasets import make_blobs
from sklearn.metrics import davies_bouldin_score, silhouette_score

from upload_service import evaluate_kmeans_cluster_counts


class KMeansEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.values, _ = make_blobs(
            n_samples=36,
            centers=3,
            n_features=4,
            cluster_std=0.6,
            random_state=42,
        )

    def test_evaluates_k_two_through_ten_with_all_metrics(self):
        result = evaluate_kmeans_cluster_counts(self.values)

        self.assertEqual([row["k"] for row in result["scores"]], list(range(2, 11)))
        self.assertTrue(all(row["valid"] for row in result["scores"]))
        self.assertTrue(all(
            np.isfinite(row[name])
            for row in result["scores"]
            for name in ("wcss", "silhouette", "davies_bouldin")
        ))
        self.assertIn(result["recommended_k"], range(2, 11))
        self.assertIn(result["elbow_k"], range(2, 11))

    def test_metrics_use_the_same_euclidean_kmeans_result(self):
        row = evaluate_kmeans_cluster_counts(self.values)["scores"][0]
        model = KMeans(n_clusters=2, random_state=42, n_init=10).fit(self.values)

        self.assertAlmostEqual(row["wcss"], model.inertia_)
        self.assertAlmostEqual(
            row["silhouette"],
            silhouette_score(self.values, model.labels_, metric="euclidean"),
        )
        self.assertAlmostEqual(
            row["davies_bouldin"],
            davies_bouldin_score(self.values, model.labels_),
        )

    def test_limits_k_to_less_than_sample_count(self):
        result = evaluate_kmeans_cluster_counts(self.values[:4])

        self.assertEqual([row["k"] for row in result["scores"]], [2, 3])
        self.assertEqual(result["max_k_evaluated"], 3)

    def test_rejects_insufficient_or_invalid_inputs(self):
        with self.assertRaisesRegex(ValueError, "At least three samples"):
            evaluate_kmeans_cluster_counts(self.values[:2])
        with self.assertRaisesRegex(ValueError, "Maximum K"):
            evaluate_kmeans_cluster_counts(self.values, max_k=1)
        with self.assertRaisesRegex(ValueError, "Maximum K"):
            evaluate_kmeans_cluster_counts(self.values, max_k=11)
        with self.assertRaisesRegex(ValueError, "finite"):
            evaluate_kmeans_cluster_counts(np.array([[0.0], [1.0], [np.nan]]))


if __name__ == "__main__":
    unittest.main()
