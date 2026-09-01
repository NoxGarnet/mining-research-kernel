from pathlib import Path
import shutil


def make_synthetic_workspace(destination: str | Path) -> Path:
    destination = Path(destination)
    source = Path(__file__).parents[1] / "examples" / "synthetic_workspace"
    shutil.copytree(source, destination, dirs_exist_ok=True)
    return destination
