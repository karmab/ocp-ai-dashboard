"""Story 8: Fleet Metrics & Trends

As an operator, I can monitor aggregate fleet health and spot trends.
"""


class TestMetricsSummary:
    def test_returns_all_summary_fields(self, demo_client):
        resp = demo_client.get("/api/metrics/summary")
        assert resp.status_code == 200
        data = resp.json()
        required = {"total_gpus", "gpu_utilization_pct", "active_models", "active_clusters", "tokens_per_sec"}
        missing = required - set(data.keys())
        assert not missing, f"Summary missing: {missing}"

    def test_total_gpus_positive(self, demo_client):
        resp = demo_client.get("/api/metrics/summary")
        assert resp.json()["total_gpus"] > 0

    def test_gpu_utilization_in_range(self, demo_client):
        resp = demo_client.get("/api/metrics/summary")
        pct = resp.json()["gpu_utilization_pct"]
        assert pct is not None
        assert 0 < pct <= 100

    def test_tokens_per_sec_positive(self, demo_client):
        resp = demo_client.get("/api/metrics/summary")
        tps = resp.json()["tokens_per_sec"]
        assert tps is not None
        assert tps > 0

    def test_active_models_matches_seed(self, demo_client, seed_models):
        resp = demo_client.get("/api/metrics/summary")
        total_seeded = sum(len(models) for models in seed_models.values())
        assert resp.json()["active_models"] == total_seeded

    def test_active_clusters_matches_seed(self, demo_client, seed_clusters):
        resp = demo_client.get("/api/metrics/summary")
        assert resp.json()["active_clusters"] == len(seed_clusters)


class TestMetricsTimeseries:
    def test_returns_all_series(self, demo_client):
        resp = demo_client.get("/api/metrics/timeseries?window=1h")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("gpu_utilization", "tokens_per_sec", "queue_depth"):
            assert key in data, f"Missing series: {key}"
            assert "timestamps" in data[key]
            assert "values" in data[key]

    def test_1h_has_approximately_60_points(self, demo_client):
        resp = demo_client.get("/api/metrics/timeseries?window=1h")
        data = resp.json()
        count = len(data["gpu_utilization"]["timestamps"])
        assert 55 <= count <= 65, f"Expected ~60 points for 1h, got {count}"

    def test_6h_has_approximately_72_points(self, demo_client):
        resp = demo_client.get("/api/metrics/timeseries?window=6h")
        data = resp.json()
        count = len(data["gpu_utilization"]["timestamps"])
        assert 68 <= count <= 76, f"Expected ~72 points for 6h, got {count}"

    def test_24h_has_approximately_96_points(self, demo_client):
        resp = demo_client.get("/api/metrics/timeseries?window=24h")
        data = resp.json()
        count = len(data["gpu_utilization"]["timestamps"])
        assert 92 <= count <= 100, f"Expected ~96 points for 24h, got {count}"

    def test_timestamps_are_ascending(self, demo_client):
        resp = demo_client.get("/api/metrics/timeseries?window=1h")
        data = resp.json()
        timestamps = data["gpu_utilization"]["timestamps"]
        assert timestamps == sorted(timestamps)

    def test_timestamps_and_values_same_length(self, demo_client):
        resp = demo_client.get("/api/metrics/timeseries?window=1h")
        data = resp.json()
        for key in ("gpu_utilization", "tokens_per_sec", "queue_depth"):
            ts_len = len(data[key]["timestamps"])
            val_len = len(data[key]["values"])
            assert ts_len == val_len, f"{key}: {ts_len} timestamps vs {val_len} values"

    def test_gpu_utilization_values_in_range(self, demo_client):
        resp = demo_client.get("/api/metrics/timeseries?window=1h")
        for val in resp.json()["gpu_utilization"]["values"]:
            assert 0 <= val <= 100, f"GPU utilization {val} out of [0, 100]"

    def test_queue_depth_values_non_negative(self, demo_client):
        resp = demo_client.get("/api/metrics/timeseries?window=1h")
        for val in resp.json()["queue_depth"]["values"]:
            assert val >= 0, f"Queue depth {val} is negative"

    def test_tokens_per_sec_values_non_negative(self, demo_client):
        resp = demo_client.get("/api/metrics/timeseries?window=1h")
        for val in resp.json()["tokens_per_sec"]["values"]:
            assert val >= 0, f"Tokens/sec {val} is negative"

    def test_series_have_variation(self, demo_client):
        """Values should not all be identical — that looks frozen, not live."""
        resp = demo_client.get("/api/metrics/timeseries?window=1h")
        for key in ("gpu_utilization", "tokens_per_sec"):
            values = resp.json()[key]["values"]
            unique = set(values)
            assert len(unique) >= 5, (
                f"{key} has only {len(unique)} unique values — looks frozen"
            )

    def test_invalid_window_returns_422(self, demo_client):
        resp = demo_client.get("/api/metrics/timeseries?window=2h")
        assert resp.status_code == 422
