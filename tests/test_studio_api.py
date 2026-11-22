"""End-to-end tests for the all-in-one Local Studio API (trial -> advise -> retrial)."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from wonderland_court.courtroom.server import create_app


def test_local_studio_end_to_end_mock_flow(tmp_path: Path) -> None:
    db_path = tmp_path / "studio.db"
    app = create_app(db_path=db_path)

    with TestClient(app) as client:
        # 1. Health advertises studio_enabled=True
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["studio_enabled"] is True

        # 2. Studio options return scenarios & defenses
        opts = client.get("/api/studio/options")
        assert opts.status_code == 200
        opts_data = opts.json()
        assert "refund_tool" in opts_data["scenarios"]
        assert "plain" in opts_data["defenses"]

        # 3. Launch an instant offline mock trial directly from the API
        start_resp = client.post(
            "/api/studio/trials",
            json={
                "target": "mock",
                "scenarios": ["refund_tool"],
                "defenses": ["plain", "spotlighting+output_filter"],
                "mode": "adaptive",
                "rounds": 1,
                "max_turns": 2,
            },
        )
        assert start_resp.status_code == 200, start_resp.text
        job = start_resp.json()
        assert job["kind"] == "trial"
        job_id = job["job_id"]

        # Poll job until complete
        for _ in range(40):
            poll = client.get(f"/api/studio/jobs/{job_id}")
            assert poll.status_code == 200
            job = poll.json()
            if job["status"] != "running":
                break
            time.sleep(0.05)

        assert job["status"] == "completed", job
        run_id = job["run_id"]
        assert isinstance(run_id, str) and run_id

        # 4. Run Caterpillar advice directly from the API
        adv_resp = client.post(f"/api/studio/runs/{run_id}/advise")
        assert adv_resp.status_code == 200, adv_resp.text
        advice = adv_resp.json()
        assert advice["run_id"] == run_id
        assert advice["recommended_defense"]

        # 5. Run seed-locked retrial directly from the API
        retrial_resp = client.post(
            f"/api/studio/runs/{run_id}/retrial",
            json={"defense": "spotlighting+output_filter"},
        )
        assert retrial_resp.status_code == 200, retrial_resp.text
        retrial_job = retrial_resp.json()
        assert retrial_job["kind"] == "retrial"

        for _ in range(40):
            poll = client.get(f"/api/studio/jobs/{retrial_job['job_id']}")
            assert poll.status_code == 200
            retrial_job = poll.json()
            if retrial_job["status"] != "running":
                break
            time.sleep(0.05)

        assert retrial_job["status"] == "completed", retrial_job
        assert retrial_job["retrial_run_id"]

        # 6. Bundle now contains both advice and retrial comparison
        bundle_resp = client.get(f"/api/runs/{run_id}/bundle")
        assert bundle_resp.status_code == 200
        bundle = bundle_resp.json()
        assert bundle["advice"] is not None
        assert bundle["retrial"] is not None
