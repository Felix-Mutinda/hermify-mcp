"""
cli.py — Typer CLI for hermify-mcp.
Provides commands to bootstrap, configure, and run the MCP server.
"""

from __future__ import annotations

import logging
import typer
from pathlib import Path
from typing import Optional, Literal

from rich.console import Console
from rich.table import Table

from .config import HermifyConfig, SyncMode
from .server import create_server
from .dataset_store import DatasetStore
from .hf_sync import HFSyncEngine

# CRITICAL: Use stderr=True so CLI output doesn't corrupt the stdio MCP transport
console = Console(stderr=True)

app = typer.Typer(
    name="hermify",
    help="Cross-agent skill & memory sync via MCP. Hermify your agent interactions.",
    add_completion=False,
    rich_markup_mode="rich",
)


def _load_config(config_path: Optional[Path]) -> HermifyConfig:
    if config_path:
        return HermifyConfig.load(config_path)
    return HermifyConfig.load()


# ---------------------------------------------------------------------------
# Bootstrap & Config
# ---------------------------------------------------------------------------


@app.command()
def init(
    home: Path = typer.Option(
        Path.home() / ".hermify", help="Base directory for hermify state."
    ),
    hf_repo: Optional[str] = typer.Option(
        None, help="Hugging Face dataset repo ID (e.g., 'user/hermify-memory')."
    ),
    mode: Literal["local_only", "hf_manual", "hf_push"] = typer.Option(
        "local_only", help="Sync mode."
    ),
    yolo: bool = typer.Option(False, help="Enable YOLO auto-approval mode for skills."),
):
    """Bootstrap the local hermify environment and config.yaml."""
    console.print(f"[bold green]Initializing hermify-mcp at {home}...[/bold green]")

    cfg = HermifyConfig(
        hermify_home=home,
        hf_repo_id=hf_repo,
        sync_mode=SyncMode(mode),
        yolo_mode=yolo,
    )
    cfg.ensure_dirs()
    cfg.save()

    console.print(
        f"[green]✓[/green] Created directory structure at [bold]{home}[/bold]"
    )
    console.print(
        f"[green]✓[/green] Saved configuration to [bold]{home / 'config.yaml'}[/bold]"
    )

    if hf_repo:
        console.print(
            f"[cyan]ℹ[/cyan] Configured to sync with HF Hub: [bold]{hf_repo}[/bold]"
        )
    else:
        console.print(
            "[yellow]ℹ[/yellow] Running in [bold]local_only[/bold] mode. Set --hf-repo to enable cloud sync."
        )


# ---------------------------------------------------------------------------
# Server Entrypoint
# ---------------------------------------------------------------------------


@app.command()
def serve(
    transport: Literal["stdio", "http", "sse", "streamable-http"] = typer.Option(
        "stdio",
        help="Transport protocol. Use 'stdio' for local agents, 'http' for HF Spaces/web.",
    ),
    host: str = typer.Option("0.0.0.0", help="Host to bind to (HTTP only)."),
    port: int = typer.Option(8742, help="Port to bind to (HTTP only)."),
    config_path: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config.yaml."
    ),
):
    """Start the hermify-mcp server."""
    cfg = _load_config(config_path)
    cfg.ensure_dirs()

    console.print(
        f"[bold blue]Starting hermify-mcp server ({transport})...[/bold blue]"
    )
    if transport == "stdio":
        console.print(
            "[dim]Listening on stdio. Connect via agent runtime (e.g., Claude Desktop).[/dim]"
        )
    else:
        console.print(f"[dim]Listening on http://{host}:{port}[/dim]")

    server = create_server(cfg)

    # FastMCP's run method handles the transport lifecycle
    if transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport=transport, host=host, port=port)


# ---------------------------------------------------------------------------
# Manual Sync Operations (For CLI users / Cron jobs)
# ---------------------------------------------------------------------------

sync_app = typer.Typer(help="Manual sync operations.")
app.add_typer(sync_app, name="sync")


@sync_app.command("push")
def sync_push(config_path: Optional[Path] = typer.Option(None, "--config", "-c")):
    """Push local DuckDB buffer to Hugging Face Hub."""
    cfg = _load_config(config_path)
    store = DatasetStore(cfg)
    engine = HFSyncEngine(store, cfg)

    console.print("[bold blue]Pushing to HF Hub...[/bold blue]")
    result = engine.push()
    if result.success:
        console.print(f"[green]✓[/green] {result.message}")
    else:
        console.print(f"[red]✗[/red] {result.error}")


@sync_app.command("pull")
def sync_pull(config_path: Optional[Path] = typer.Option(None, "--config", "-c")):
    """Pull latest state from Hugging Face Hub into local DuckDB."""
    cfg = _load_config(config_path)
    store = DatasetStore(cfg)
    engine = HFSyncEngine(store, cfg)

    console.print("[bold blue]Pulling from HF Hub...[/bold blue]")
    result = engine.pull()
    if result.success:
        console.print(f"[green]✓[/green] {result.message}")
    else:
        console.print(f"[red]✗[/red] {result.error}")


@sync_app.command("status")
def sync_status(config_path: Optional[Path] = typer.Option(None, "--config", "-c")):
    """Show local buffer and sync status."""
    cfg = _load_config(config_path)
    store = DatasetStore(cfg)
    engine = HFSyncEngine(store, cfg)

    status = engine.status()

    table = Table(title="Hermify Sync Status")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="magenta")

    table.add_row("Mode", status["mode"])
    table.add_row("HF Repo", status["hf_repo_id"] or "[dim]Not configured[/dim]")
    table.add_row("Local Skills", str(status["local_buffer"]["skills"]))
    table.add_row("Local Memory", str(status["local_buffer"]["memory"]))

    console.print(table)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
    )
    app()


if __name__ == "__main__":
    main()
