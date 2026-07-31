"""Re-execute every committed notebook, in place, and fail on the first error.

The notebooks are documentation that runs, so CI runs it. This does not compare outputs —
holiday data and timings legitimately differ — only that every cell executes cleanly.

    uv run python tools/run_notebooks.py            # check, leave files untouched
    uv run python tools/run_notebooks.py --write    # refresh the committed outputs
"""

from __future__ import annotations

import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

NOTEBOOK_DIR = Path(__file__).resolve().parents[1] / "notebooks"


def main(argv: list[str]) -> int:
    """Execute every notebook; return how many failed.

    Args:
        argv: Command-line arguments; ``--write`` refreshes the committed outputs.

    Returns:
        The number of notebooks that raised.
    """
    write = "--write" in argv
    failures = 0
    for path in sorted(NOTEBOOK_DIR.glob("*.ipynb")):
        notebook = nbformat.read(path, as_version=4)
        try:
            NotebookClient(
                notebook,
                timeout=300,
                kernel_name="python3",
                resources={"metadata": {"path": str(NOTEBOOK_DIR)}},
            ).execute()
        except Exception as exc:  # report every notebook, not just the first
            print(f"FAIL {path.name}: {type(exc).__name__}: {str(exc)[:1500]}")
            failures += 1
            continue
        if write:
            nbformat.write(notebook, path)
        print(f"  ok {path.name} ({len(notebook.cells)} cells)")
    if failures:
        print(f"\n{failures} notebook(s) failed to execute.", file=sys.stderr)
    return failures


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
