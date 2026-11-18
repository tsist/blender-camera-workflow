"""Build an installable Camera Workflow ZIP from this source checkout."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


PACKAGE = Path(__file__).resolve().parent / "camera_windows_static"
MANIFEST = PACKAGE / "CODE-MANIFEST.json"
RUNTIME = {
    "blender": "8f7a131ad8bc148edc218b334f07d92a57f5a357fa66d913b290537fd8353c06",
    "python": "b51e9a425a5b703017ac6e8b827be2b3c3122a2683040a6215a1d70a3dd5af0b",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Path of the new ZIP")
    args = parser.parse_args()
    sources = {
        file.relative_to(PACKAGE).as_posix(): file.read_bytes()
        for file in sorted(PACKAGE.rglob("*.py"))
        if "__pycache__" not in file.parts
    }
    expected = {
        "schema": 2,
        "files": {name: sha256(content).hexdigest() for name, content in sources.items()},
        "runtime": RUNTIME,
    }
    manifest = MANIFEST.read_bytes()
    if json.loads(manifest) != expected:
        raise SystemExit("CODE-MANIFEST.json does not match the package sources")
    entries = {**sources, MANIFEST.name: manifest}
    for name in ("COPYING", "README.md", "SUPPORT-NOTICE.md"):
        entries[name] = (PACKAGE / name).read_bytes()
    with ZipFile(args.output, "x", compression=ZIP_DEFLATED) as archive:
        for name, data in sorted(entries.items()):
            info = ZipInfo(f"{PACKAGE.name}/{name}")
            archive.writestr(info, data, compress_type=ZIP_DEFLATED)
    with ZipFile(args.output) as archive:
        if archive.testzip() or any(archive.read(f"{PACKAGE.name}/{name}") != data for name, data in entries.items()):
            raise SystemExit("Built archive did not pass readback")
    print(args.output)


if __name__ == "__main__":
    main()
