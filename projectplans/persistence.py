import json
from pathlib import Path
from PyQt6.QtCore import QSaveFile, QIODevice

from .constants import SCHEMA_VERSION
from .model import ProjectModel


def save_project(path: str | Path, model: ProjectModel, view_state: dict) -> None:
    payload = model.to_dict()
    payload["schema_version"] = SCHEMA_VERSION
    payload["view"] = view_state
    path = Path(path)
    encoded = json.dumps(payload, indent=2).encode("utf-8")
    output = QSaveFile(str(path))
    output.setDirectWriteFallback(False)
    if not output.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(output.errorString())
    if output.write(encoded) != len(encoded):
        error = output.errorString()
        output.cancelWriting()
        raise OSError(error)
    if not output.commit():
        raise OSError(output.errorString())


def load_project(path: str | Path) -> tuple[ProjectModel, dict]:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    model = ProjectModel.from_dict(data)
    view_state = data.get("view", {})
    return model, view_state
