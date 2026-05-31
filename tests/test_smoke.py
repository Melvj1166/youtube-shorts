"""Smoke tests: verify all modules import and CLI commands are registered."""
from __future__ import annotations


def test_all_stages_importable():
    from podshorts.stages import (
        s01_download,
        s02_heatmap,
        s03_transcribe,
        s04_segment,
        s05_score,
        s06_rank,
        s07_face_track,
        s08_crop,
        s09_subtitle,
        s10_export,
    )
    for stage in (
        s01_download, s02_heatmap, s03_transcribe, s04_segment,
        s05_score, s06_rank, s07_face_track, s08_crop, s09_subtitle, s10_export,
    ):
        assert callable(stage.run)


def test_pipeline_importable():
    from podshorts.pipeline import run_pipeline, run_pipeline_dry, inspect_pipeline
    assert callable(run_pipeline)
    assert callable(run_pipeline_dry)
    assert callable(inspect_pipeline)


def test_settings_loads_with_defaults():
    from podshorts.config import Settings
    s = Settings()
    assert s.ollama_model == "qwen2.5:7b"
    assert s.top_n_shorts == 5
    assert s.min_short_duration == 20
    assert s.max_short_duration == 60


def test_cli_commands_registered():
    from typer.testing import CliRunner
    from podshorts.__main__ import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.output
    assert "inspect" in result.output
    assert "doctor" in result.output


def test_cli_run_help():
    from typer.testing import CliRunner
    from podshorts.__main__ import app

    runner = CliRunner()
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--dry-run" in result.output
    assert "--top-n" in result.output
    assert "--force" in result.output


def test_types_all_dataclasses():
    import dataclasses
    import podshorts.types as types_module
    # Only check classes defined in this module, not imported ones
    for name, obj in vars(types_module).items():
        if (
            isinstance(obj, type)
            and name[0].isupper()
            and getattr(obj, "__module__", "") == types_module.__name__
        ):
            assert dataclasses.is_dataclass(obj), f"{name} is not a dataclass"


def test_ffmpeg_bin_resolves():
    from podshorts.utils.ffmpeg import ffmpeg_bin
    path = ffmpeg_bin()
    assert "ffmpeg" in path
    import os
    assert os.path.isfile(path)
