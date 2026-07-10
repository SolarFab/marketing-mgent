"""Tests for the eval framework itself."""
import pytest


def test_golden_set_loads_and_shape_ok():
    from backend.eval.evaluate_scorer import load_golden_set

    gs = load_golden_set()
    assert gs["version"] == "v1"
    assert "wine_estate" in gs["profiles"]
    assert "logistics_startup" in gs["profiles"]
    items = gs["items"]
    assert len(items) >= 20
    for it in items:
        assert it["profile"] in gs["profiles"]
        assert it["expected_route"] in {"feature", "uncertain", "discard"}
        assert it["kind"] in {"owned", "external"}


def test_run_golden_set_eval_produces_reasonable_precision():
    """The Evaluate node should get at least half the feature calls right.

    This isn't a claim about the ideal — it's a floor. If precision drops
    below 0.5, something regressed badly in scoring.
    """
    from backend.eval.evaluate_scorer import run_golden_set_eval

    r = run_golden_set_eval()
    assert r.total >= 20
    assert r.precision + r.recall > 0, "eval yielded no signal at all"


@pytest.mark.db
def test_run_eval_writes_files_when_no_company(tmp_path, monkeypatch):
    """The orchestrator should write both .md and .json artifacts."""
    from backend.eval import run_eval

    monkeypatch.setattr(run_eval, "_EVAL_RUNS", tmp_path)
    result = run_eval.run_all(slug="test-run")

    md = tmp_path / "test-run-run.md"
    js = tmp_path / "test-run-run.json"
    assert md.exists()
    assert js.exists()
    body = md.read_text()
    assert "Golden-set routing" in body
    assert "Skipped" in body  # no company_id
