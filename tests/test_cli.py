"""Tests for the hermify-mcp Typer CLI."""

import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner

from hermify_mcp.cli import app

# CliRunner simulates terminal execution
runner = CliRunner()


def test_init_creates_config_and_dirs(tmp_path: Path):
    """The init command should create the home dir, logs, and config.yaml."""
    home_dir = tmp_path / "custom_hermify"

    result = runner.invoke(
        app, ["init", "--home", str(home_dir), "--mode", "local_only"]
    )

    assert result.exit_code == 0, f"CLI failed with output: {result.output}"
    assert (home_dir / "config.yaml").exists()
    assert (home_dir / "logs").is_dir()

    # Verify config content was saved correctly
    with open(home_dir / "config.yaml") as f:
        cfg_data = yaml.safe_load(f)

    assert cfg_data["sync_mode"] == "local_only"
    assert cfg_data["hermify_home"] == str(home_dir)


def test_init_with_hf_repo_and_yolo(tmp_path: Path):
    """Init should correctly parse and save HF repo config and YOLO mode."""
    home_dir = tmp_path / "hf_hermify"
    result = runner.invoke(
        app,
        [
            "init",
            "--home",
            str(home_dir),
            "--hf-repo",
            "test-user/my-brain",
            "--mode",
            "hf_push",
            "--yolo",
        ],
    )

    assert result.exit_code == 0
    with open(home_dir / "config.yaml") as f:
        cfg_data = yaml.safe_load(f)

    assert cfg_data["hf_repo_id"] == "test-user/my-brain"
    assert cfg_data["sync_mode"] == "hf_push"
    assert cfg_data["yolo_mode"] is True


def test_sync_status_runs_successfully(tmp_path: Path):
    """sync status should run without crashing and read the local config."""
    home_dir = tmp_path / "status_hermify"
    # 1. Init first to create a valid config
    runner.invoke(app, ["init", "--home", str(home_dir)])

    # 2. Run status (pointing to the newly created config)
    result = runner.invoke(
        app, ["sync", "status", "--config", str(home_dir / "config.yaml")]
    )

    # We just verify it exits cleanly (Rich tables can be tricky to assert exact strings on)
    assert result.exit_code == 0


@patch("hermify_mcp.cli.HFSyncEngine")
def test_sync_push_calls_engine(mock_engine_class, tmp_path: Path):
    """sync push should instantiate the engine and call push()."""
    home_dir = tmp_path / "push_hermify"
    runner.invoke(app, ["init", "--home", str(home_dir)])

    # Setup mock to prevent actual HF Hub network calls
    mock_engine_instance = MagicMock()
    mock_engine_instance.push.return_value = MagicMock(
        success=True, message="Pushed 5 rows to HF Hub"
    )
    mock_engine_class.return_value = mock_engine_instance

    result = runner.invoke(
        app, ["sync", "push", "--config", str(home_dir / "config.yaml")]
    )

    assert result.exit_code == 0
    mock_engine_instance.push.assert_called_once()


@patch("hermify_mcp.cli.create_server")
def test_serve_stdio_transport(mock_create_server, tmp_path: Path):
    """serve command should default to stdio transport and call server.run()."""
    home_dir = tmp_path / "serve_hermify"
    runner.invoke(app, ["init", "--home", str(home_dir)])

    # Setup mock server to prevent the CLI from actually blocking on stdin
    mock_server = MagicMock()
    mock_create_server.return_value = mock_server

    result = runner.invoke(app, ["serve", "--config", str(home_dir / "config.yaml")])

    assert result.exit_code == 0
    mock_create_server.assert_called_once()

    # Verify it ran with the default stdio transport
    mock_server.run.assert_called_once_with(transport="stdio")


@patch("hermify_mcp.cli.create_server")
def test_serve_http_transport(mock_create_server, tmp_path: Path):
    """serve command should correctly pass http transport and port arguments."""
    home_dir = tmp_path / "serve_http_hermify"
    runner.invoke(app, ["init", "--home", str(home_dir)])

    mock_server = MagicMock()
    mock_create_server.return_value = mock_server

    result = runner.invoke(
        app,
        [
            "serve",
            "--config",
            str(home_dir / "config.yaml"),
            "--transport",
            "http",
            "--port",
            "9999",
        ],
    )

    assert result.exit_code == 0
    # Verify it ran with http transport and the custom port
    mock_server.run.assert_called_once_with(transport="http", host="0.0.0.0", port=9999)
