"""Owned GUI supervisor. Launch arguments bind exact action bytes and a fresh gate."""
from pathlib import Path
import sys, time
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from camera_windows_static import common as c, service

def main():
    action_path, action_sha, gate_path, nonce = sys.argv[1:]
    gate = Path(gate_path)
    deadline = time.monotonic() + 20
    while not gate.exists():
        if time.monotonic() > deadline: raise TimeoutError("Supervisor launch gate absent")
        time.sleep(0.05)
    c.require(c.read_json(gate, 4096) == {"nonce": nonce}, "Supervisor launch gate differs")
    item = c.load_descriptor({"file": action_path, "sha256": action_sha})
    c.verify_package(item["manifest_sha"])
    result = service.dispatch(item["action"], item["params"])
    c.write_new(Path(action_path).parent / "result.json", result)

if __name__ == "__main__": main()
