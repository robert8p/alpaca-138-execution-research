from app import orchestrator


def test_massive_stage_count_binds_like_wildcard(monkeypatch):
    captured = {}

    def fake_fetch_one(sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return {"total": 1, "completed": 0, "failed": 0, "running": 0, "queued": 1}

    monkeypatch.setattr(orchestrator, "fetch_one", fake_fetch_one)
    result = orchestrator._stage_counts("run-id", "primary", "massive_reference")

    assert result["total"] == 1
    assert "partition_key like %s" in captured["sql"]
    assert "symbol-batch-%" not in captured["sql"]
    assert captured["params"] == (
        "run-id",
        "primary",
        "massive_reference",
        "symbol-batch-%",
    )
