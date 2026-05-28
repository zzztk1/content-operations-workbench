from __future__ import annotations

from fastapi.testclient import TestClient

from api_v2 import create_app


def main() -> None:
    app = create_app()
    expected_images = {"公众号": 5, "小红书": 8, "知乎": 3}
    bodies: dict[str, str] = {}

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        rules = client.get("/v2/platform-rules").json()["platforms"]
        assert {rule["platform"] for rule in rules} == set(expected_images)

        for platform, image_count in expected_images.items():
            result = client.post(
                "/v2/run",
                json={
                    "brief": "信息过载为什么让判断力变弱",
                    "platform": platform,
                    "style": "经验总结",
                    "run_mode": "auto",
                    "approval_decision": "approve",
                    "image_mock": True,
                    "vision_review_mock": True,
                },
            ).json()
            state = result["state"]
            package = state["publish_package"]
            assert state["status"] == "completed"
            assert len(state["image_assets"]) == image_count
            assert len(package["image_assets"]) == image_count
            assert package["copy_blocks"]["title"]
            assert package["copy_blocks"]["body"]
            assert state["review"].get("total_score") is not None
            bodies[platform] = state["adapted"]["content"][:40]

        assert len(set(bodies.values())) == 3

        guided = client.post(
            "/v2/run",
            json={
                "brief": "guided 验收",
                "platform": "小红书",
                "style": "经验总结",
                "run_mode": "guided",
                "approval_decision": "approve",
                "image_mock": True,
                "vision_review_mock": True,
            },
        ).json()
        assert guided["state"]["status"] == "awaiting_topic_selection"

        continued = client.post(
            "/v2/run/continue",
            json={
                "run_id": guided["run_id"],
                "selected_topic_index": 0,
                "approval_decision": "approve",
                "image_mock": True,
                "vision_review_mock": True,
            },
        ).json()
        assert continued["state"]["status"] == "completed"

        nodes = client.get(f"/v2/runs/{continued['run_id']}/nodes").json()["nodes"]
        assert len(nodes) >= 10
        assert all("input_summary" in node and "output_summary" in node for node in nodes)

        rerun = client.post(
            f"/v2/runs/{continued['run_id']}/nodes/write_draft/rerun",
            json={
                "instruction": "更具体",
                "approval_decision": "approve",
                "image_mock": True,
                "vision_review_mock": True,
            },
        ).json()
        assert rerun["state"]["status"] == "completed"

        stream = client.post(
            "/v2/run/stream",
            json={
                "brief": "stream 验收",
                "platform": "知乎",
                "style": "经验总结",
                "run_mode": "auto",
                "approval_decision": "approve",
                "image_mock": True,
                "vision_review_mock": True,
            },
        )
        assert stream.status_code == 200
        assert "event: final" in stream.text

    print("WORKBENCH_SMOKE_OK")


if __name__ == "__main__":
    main()
