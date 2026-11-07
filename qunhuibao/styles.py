"""One complete stylesheet entry point for every report surface."""
from pathlib import Path

ASSET_DIR = Path(__file__).resolve().parent / "assets"


def report_styles(*, editor=False):
    names = ["tongcheng-proposal.css", "report.css"]
    if editor:
        names.extend(["editor.css", "digest.css"])
    return "\n".join((ASSET_DIR / name).read_text(encoding="utf-8-sig") for name in names)
