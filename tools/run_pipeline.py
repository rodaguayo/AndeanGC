"""Execute pipeline notebooks in order, streaming their output as they run.

`jupyter nbconvert --execute` buffers everything into the output notebook, so a
stage that runs for an hour prints two lines and nothing in between. This runs
the same notebooks through the same machinery (nbclient, which is what
nbconvert's ExecutePreprocessor wraps) but echoes each cell and its stdout /
stderr to the terminal while it happens, and reports per-stage timings.

    python tools/run_pipeline.py processing/01_....ipynb processing/02_....ipynb

The stage order stays in pixi.toml, where it is enforced.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

DEFAULT_OUT = Path("temp/pipeline")


def _hms(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def _first_line(source: str, width: int = 68) -> str:
    for line in source.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:width] + ("…" if len(line) > width else "")
    return "(comments only)"


class StreamingClient(NotebookClient):
    """NotebookClient that mirrors cell output to the terminal as it arrives."""

    def output(self, outs, msg, display_id, cell_index):
        content = msg.get("content", {})
        if msg["msg_type"] == "stream":
            stream = sys.stderr if content.get("name") == "stderr" else sys.stdout
            stream.write(content.get("text", ""))
            stream.flush()
        return super().output(outs, msg, display_id, cell_index)


def run_notebook(path: Path, out_dir: Path) -> float:
    nb = nbformat.read(path, as_version=4)
    code_cells = [i for i, c in enumerate(nb.cells) if c.cell_type == "code"]
    total = len(code_cells)
    started = time.monotonic()
    cell_started = {}

    print(f"\n{'=' * 78}\n▶ {path.name}  ({total} code cells)\n{'=' * 78}", flush=True)

    def on_cell_start(cell, cell_index):
        if cell.cell_type != "code":
            return
        cell_started[cell_index] = time.monotonic()
        n = code_cells.index(cell_index) + 1
        print(f"\n[{path.stem[:2]} {n:>2}/{total}] {_first_line(cell.source)}", flush=True)

    def on_cell_executed(cell, cell_index, execute_reply):
        if cell.cell_type != "code":
            return
        elapsed = time.monotonic() - cell_started.pop(cell_index, time.monotonic())
        if elapsed >= 1:
            print(f"    ↳ {_hms(elapsed)}", flush=True)

    client = StreamingClient(
        nb,
        timeout=None,
        allow_errors=False,
        kernel_name="python3",
        resources={"metadata": {"path": str(path.parent)}},
        on_cell_start=on_cell_start,
        on_cell_executed=on_cell_executed,
    )

    try:
        client.execute()
    finally:
        out_dir.mkdir(parents=True, exist_ok=True)
        nbformat.write(nb, out_dir / path.name)

    return time.monotonic() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("notebooks", nargs="+", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    timings: list[tuple[str, float]] = []
    for path in args.notebooks:
        try:
            timings.append((path.name, run_notebook(path, args.out_dir)))
        except CellExecutionError as exc:
            print(f"\n✗ {path.name} failed — executed copy in {args.out_dir}\n{exc}", file=sys.stderr)
            _summary(timings, failed=path.name)
            return 1

    _summary(timings)
    return 0


def _summary(timings: list[tuple[str, float]], failed: str | None = None) -> None:
    print(f"\n{'=' * 78}")
    for name, elapsed in timings:
        print(f"  {_hms(elapsed):>8}  {name}")
    if failed:
        print(f"  {'FAILED':>8}  {failed}")
    print(f"  {'-' * 8}")
    print(f"  {_hms(sum(t for _, t in timings)):>8}  total")


if __name__ == "__main__":
    raise SystemExit(main())
