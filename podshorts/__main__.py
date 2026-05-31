from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="podshorts",
    help="AI Podcast-to-Shorts Automation Pipeline",
    add_completion=False,
)
cache_app = typer.Typer(help="Cache management commands")
app.add_typer(cache_app, name="cache")

console = Console()
err_console = Console(stderr=True)


def _load_settings(config_path: Optional[Path] = None) -> "Settings":
    from podshorts.config import Settings
    if config_path:
        return Settings(_env_file=str(config_path))
    return Settings()


@app.command()
def run(
    youtube_url: Annotated[str, typer.Argument(help="YouTube podcast URL")],
    top_n: Annotated[int, typer.Option("--top-n", help="Number of shorts to produce")] = 5,
    force: Annotated[bool, typer.Option("--force", help="Force re-run all stages")] = False,
    config: Annotated[Optional[Path], typer.Option("--config", help="Path to .env file")] = None,
) -> None:
    """Download a podcast and produce vertical short videos."""
    from podshorts.pipeline import run_pipeline
    from podshorts.utils.logging import configure_root_logger

    settings = _load_settings(config)
    settings.top_n_shorts = top_n
    settings.force_rerun = force
    configure_root_logger(settings.log_level)

    try:
        output_dir = run_pipeline(youtube_url, settings)
        console.print(f"[green]Done.[/green] Shorts written to {output_dir}")
    except NotImplementedError as exc:
        err_console.print(f"[yellow]Not yet implemented:[/yellow] {exc}")
        raise typer.Exit(code=2) from None
    except Exception as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from None


@cache_app.command("list")
def cache_list(
    config: Annotated[Optional[Path], typer.Option("--config")] = None,
) -> None:
    """List cached videos."""
    settings = _load_settings(config)
    cache_dir = settings.cache_dir

    if not cache_dir.exists():
        console.print("Cache directory empty.")
        return

    entries = [d for d in cache_dir.iterdir() if d.is_dir()]
    if not entries:
        console.print("No cached videos.")
        return

    table = Table(title="Cached Videos")
    table.add_column("Video ID", style="cyan")
    table.add_column("Files")

    for entry in sorted(entries):
        files = list(entry.iterdir())
        table.add_row(entry.name, str(len(files)))

    console.print(table)


@cache_app.command("clear")
def cache_clear(
    video_id: Annotated[str, typer.Argument(help="Video ID to clear from cache")],
    config: Annotated[Optional[Path], typer.Option("--config")] = None,
) -> None:
    """Remove a video from cache."""
    import shutil
    settings = _load_settings(config)
    target = settings.cache_dir / video_id

    if not target.exists():
        err_console.print(f"[yellow]Not found in cache:[/yellow] {video_id}")
        raise typer.Exit(code=1)

    shutil.rmtree(target)
    console.print(f"[green]Cleared:[/green] {video_id}")


@app.command()
def inspect(
    video_id: Annotated[str, typer.Argument(help="Video ID (must already be in cache)")],
    config: Annotated[Optional[Path], typer.Option("--config")] = None,
) -> None:
    """Show heatmap and scored segments without rendering video."""
    from podshorts.pipeline import inspect_pipeline
    from podshorts.utils.logging import configure_root_logger

    settings = _load_settings(config)
    configure_root_logger(settings.log_level)

    try:
        inspect_pipeline(video_id, settings)
    except NotImplementedError as exc:
        err_console.print(f"[yellow]Not yet implemented:[/yellow] {exc}")
        raise typer.Exit(code=2) from None
    except Exception as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from None


@app.command()
def doctor(
    config: Annotated[Optional[Path], typer.Option("--config")] = None,
) -> None:
    """Verify all required dependencies and hardware acceleration."""
    settings = _load_settings(config)
    all_ok = True

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal all_ok
        status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
        line = f"  {status}  {label}"
        if detail:
            line += f"  — {detail}"
        console.print(line)
        if not ok:
            all_ok = False

    console.print("\n[bold]PodShorts Doctor[/bold]\n")

    # 1. FFmpeg + h264_videotoolbox
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True, check=False
        )
        ffmpeg_ok = result.returncode == 0
    except FileNotFoundError:
        ffmpeg_ok = False

    check("ffmpeg", ffmpeg_ok, "not found — brew install ffmpeg" if not ffmpeg_ok else "")

    if ffmpeg_ok:
        vt_result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, check=False,
        )
        vt_ok = "h264_videotoolbox" in vt_result.stdout
        check("h264_videotoolbox", vt_ok, "Apple Silicon HW encoder")
    else:
        check("h264_videotoolbox", False, "ffmpeg missing")

    # 2. Ollama
    try:
        import httpx
        resp = httpx.get(f"{settings.ollama_host}/api/tags", timeout=3.0)
        ollama_ok = resp.status_code == 200
        models = [m["name"] for m in resp.json().get("models", [])]
        target_pulled = any(settings.ollama_model in m for m in models)
        check("ollama", ollama_ok, f"reachable at {settings.ollama_host}")
        check(
            f"ollama model ({settings.ollama_model})",
            target_pulled,
            "not pulled — run: ollama pull " + settings.ollama_model if not target_pulled else "",
        )
    except Exception as exc:
        check("ollama", False, str(exc)[:80])
        check(f"ollama model ({settings.ollama_model})", False, "ollama unreachable")

    # 3. Apple Silicon MPS
    try:
        import torch
        mps_ok = torch.backends.mps.is_available()
        check("torch MPS (Apple Silicon)", mps_ok, "Metal acceleration")
    except ImportError:
        check("torch MPS (Apple Silicon)", False, "torch not installed")

    # 4. faster-whisper
    try:
        import faster_whisper  # noqa: F401
        check("faster-whisper", True)
    except ImportError:
        check("faster-whisper", False, "pip install faster-whisper")

    # 5. MediaPipe
    try:
        import mediapipe  # noqa: F401
        check("mediapipe", True)
    except ImportError:
        check("mediapipe", False, "pip install mediapipe")

    # 6. filterpy
    try:
        import filterpy  # noqa: F401
        check("filterpy", True)
    except ImportError:
        check("filterpy", False, "pip install filterpy")

    # 7. yt-dlp
    try:
        import yt_dlp  # noqa: F401
        check("yt-dlp", True)
    except ImportError:
        check("yt-dlp", False, "pip install yt-dlp")

    console.print()
    if all_ok:
        console.print("[bold green]All checks passed.[/bold green]")
    else:
        console.print("[bold yellow]Some checks failed. See above.[/bold yellow]")
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
