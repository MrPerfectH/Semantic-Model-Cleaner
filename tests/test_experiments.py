from semantic_model_cleaner import experiments


def test_runtime_config_defaults_to_packaged_beta_channel(monkeypatch):
    monkeypatch.delenv("SMC_RELEASE_CHANNEL", raising=False)
    runtime = experiments.runtime_config(raw_experiments="")

    assert runtime["releaseChannel"] == "beta"
    assert runtime["betaEnabled"] is True
    assert runtime["activeExperiments"] == []


def test_runtime_config_allows_explicit_stable_override():
    runtime = experiments.runtime_config(raw_channel="stable", raw_experiments="")

    assert runtime["releaseChannel"] == "stable"
    assert runtime["betaEnabled"] is False


def test_runtime_config_enables_beta_channel():
    runtime = experiments.runtime_config(raw_channel="beta", raw_experiments="")

    assert runtime["releaseChannel"] == "beta"
    assert runtime["betaEnabled"] is True


def test_removed_compare_experiment_cannot_enable_beta():
    runtime = experiments.runtime_config(
        raw_channel="stable",
        raw_experiments="compare-models",
        extra_experiments=["compare-models", "unknown-feature"],
    )
    assert runtime["betaEnabled"] is False
    assert runtime["activeExperiments"] == []
