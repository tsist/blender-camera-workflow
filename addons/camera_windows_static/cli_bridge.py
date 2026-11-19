"""Reviewed bridge for the existing blenderctl extension.run executor."""
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root.parent))
from camera_windows_static import common

if common.ROOT != root:
    raise ValueError("Camera bridge loaded a different adapter")
_, _, (_, blender, python) = common.verify_package()
folder = Path(job_directory)
request = folder / "camera-bridge-input.json"
with request.open("x", encoding="utf8") as handle:
    json.dump(parameters, handle, allow_nan=False)

process = subprocess.run(
    [str(python), "-I", "-B", str(root / "cli.py"), "--blender", str(blender), str(request)],
    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    stdin=subprocess.DEVNULL, capture_output=True, timeout=900,
)
result = json.loads(process.stdout.decode("utf8"))
if process.returncode:
    raise ValueError(result["error"]["message"])
with (folder / "output-camera-static.json").open("x", encoding="utf8") as handle:
    json.dump(result, handle, ensure_ascii=False, allow_nan=False)
