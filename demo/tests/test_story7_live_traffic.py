"""Story 7: Live Traffic Monitoring

As an operator, I can see real-time inference traffic flowing across clusters.
"""
import time


class TestSpreadsTraffic:
    def test_returns_traffic_for_all_spreads(self, demo_client, seed_spreads):
        resp = demo_client.get("/api/spreads/traffic")
        assert resp.status_code == 200
        data = resp.json()
        assert "spreads" in data
        for spread in seed_spreads:
            assert spread["id"] in data["spreads"], (
                f"Spread '{spread['id']}' missing from traffic data"
            )

    def test_traffic_includes_all_spokes(self, demo_client, seed_spreads):
        resp = demo_client.get("/api/spreads/traffic")
        data = resp.json()
        for spread in seed_spreads:
            spread_traffic = data["spreads"][spread["id"]]
            for spoke in spread["spokes"]:
                assert spoke in spread_traffic, (
                    f"Spoke '{spoke}' missing from spread '{spread['id']}' traffic"
                )

    def test_each_spoke_has_req_rate(self, demo_client, seed_spreads):
        resp = demo_client.get("/api/spreads/traffic")
        data = resp.json()
        for spread in seed_spreads:
            for spoke, metrics in data["spreads"][spread["id"]].items():
                assert "req_rate" in metrics
                assert isinstance(metrics["req_rate"], (int, float))

    def test_at_least_one_spoke_has_nonzero_traffic(self, demo_client, seed_spreads):
        resp = demo_client.get("/api/spreads/traffic")
        data = resp.json()
        all_rates = []
        for spread_traffic in data["spreads"].values():
            for spoke_data in spread_traffic.values():
                all_rates.append(spoke_data["req_rate"])
        assert any(r > 0 for r in all_rates), "All spokes have zero traffic — no animation"

    def test_traffic_values_are_stable_not_random(self, demo_client):
        """Two rapid calls should return values within 20% of each other."""
        resp1 = demo_client.get("/api/spreads/traffic").json()
        resp2 = demo_client.get("/api/spreads/traffic").json()
        for spread_id, spokes in resp1["spreads"].items():
            for spoke, data1 in spokes.items():
                data2 = resp2["spreads"][spread_id][spoke]
                r1 = data1["req_rate"]
                r2 = data2["req_rate"]
                if r1 == 0 and r2 == 0:
                    continue
                max_val = max(r1, r2)
                diff = abs(r1 - r2)
                assert diff <= max_val * 0.2, (
                    f"Traffic for {spread_id}/{spoke} jumped from {r1} to {r2}"
                )


class TestSpreadMetrics:
    def test_returns_spread_and_spokes(self, demo_client, seed_spreads):
        spread = seed_spreads[0]
        resp = demo_client.get(f"/api/spreads/{spread['id']}/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "spread" in data
        assert "spokes" in data
        assert len(data["spokes"]) == len(spread["spokes"])

    def test_each_spoke_has_required_metrics(self, demo_client, seed_spreads):
        spread = seed_spreads[0]
        resp = demo_client.get(f"/api/spreads/{spread['id']}/metrics")
        required = {
            "name", "display_name", "ready_pods", "avg_latency_ms",
            "req_rate", "tokens_per_sec", "total_requests", "region", "reachable",
        }
        for spoke in resp.json()["spokes"]:
            missing = required - set(spoke.keys())
            assert not missing, f"Spoke '{spoke.get('name', '?')}' missing: {missing}"

    def test_spokes_are_reachable(self, demo_client, seed_spreads):
        spread = seed_spreads[0]
        resp = demo_client.get(f"/api/spreads/{spread['id']}/metrics")
        for spoke in resp.json()["spokes"]:
            assert spoke["reachable"] is True

    def test_spokes_have_ready_pods(self, demo_client, seed_spreads):
        spread = seed_spreads[0]
        resp = demo_client.get(f"/api/spreads/{spread['id']}/metrics")
        for spoke in resp.json()["spokes"]:
            assert spoke["ready_pods"] >= 1

    def test_latency_is_realistic(self, demo_client, seed_spreads):
        spread = seed_spreads[0]
        resp = demo_client.get(f"/api/spreads/{spread['id']}/metrics")
        for spoke in resp.json()["spokes"]:
            assert 10 <= spoke["avg_latency_ms"] <= 2000, (
                f"Spoke '{spoke['name']}' latency {spoke['avg_latency_ms']}ms outside realistic range"
            )

    def test_returns_hub_url(self, demo_client, seed_spreads):
        spread = seed_spreads[0]
        resp = demo_client.get(f"/api/spreads/{spread['id']}/metrics")
        data = resp.json()
        assert "hub_url" in data
        assert isinstance(data["hub_url"], str)
        assert len(data["hub_url"]) > 0

    def test_returns_route_to(self, demo_client, seed_spreads):
        spread = seed_spreads[0]
        resp = demo_client.get(f"/api/spreads/{spread['id']}/metrics")
        data = resp.json()
        assert "route_to" in data
        spoke_names = [s["name"] for s in data["spokes"]]
        assert data["route_to"] in spoke_names

    def test_returns_scores(self, demo_client, seed_spreads):
        spread = seed_spreads[0]
        resp = demo_client.get(f"/api/spreads/{spread['id']}/metrics")
        data = resp.json()
        assert "scores" in data
        assert len(data["scores"]) == len(data["spokes"])
        for score in data["scores"]:
            assert 1 <= score <= 4

    def test_route_to_matches_best_score(self, demo_client, seed_spreads):
        spread = seed_spreads[0]
        resp = demo_client.get(f"/api/spreads/{spread['id']}/metrics")
        data = resp.json()
        best_idx = data["scores"].index(max(data["scores"]))
        assert data["route_to"] == data["spokes"][best_idx]["name"]

    def test_nonexistent_spread_returns_404(self, demo_client):
        resp = demo_client.get("/api/spreads/nonexistent/metrics")
        assert resp.status_code == 404
