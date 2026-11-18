"""Run a Camera Workflow transaction with the Blender-bundled Python."""
import argparse
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from camera_windows_static import common as c, service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", type=Path, help=f"Blender executable (or set {c.BLENDER_ENV})")
    parser.add_argument("request", type=Path, help="JSON file with action and params")
    args = parser.parse_args()
    try:
        if args.blender is not None:
            os.environ[c.BLENDER_ENV] = str(args.blender.resolve(strict=True))
        request = c.read_json(args.request.resolve(strict=True))
        c.require(type(request) is dict and set(request) in (
            {"action", "params"}, {"action", "params", "adapter_manifest_sha"}
        ), "Expected action, params and optional adapter_manifest_sha")
        c.verify_package(request.get("adapter_manifest_sha"))
        result = service.dispatch(request["action"], request["params"])
    except Exception as exc:
        result = {"error": {"type": type(exc).__name__, "message": str(exc)}}
        sys.stdout.buffer.write(c.canonical(result) + b"\n")
        return 1
    sys.stdout.buffer.write(c.canonical(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
