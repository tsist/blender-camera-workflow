# Camera Workflow 0.8.2

Camera Workflow organizes shots and saves verified copies of Blender scenes. The Camera Live sidebar provides shot preview, candidate comparison, framing diagnosis and checks for camera edits.

## Install on Windows

The saved-copy tools are qualified with the official **Blender 5.2.1 LTS** Windows x64 build `9e2066aef7ef`. The add-on uses that installation's bundled Python and local support modules.

1. Build the add-on archive from this repository with `python addons/build_camera_zip.py camera-workflow-0.8.2.zip`.
2. In Blender, open **Edit > Preferences > Add-ons > Install from Disk**, select the ZIP and enable **Camera Workflow Windows**.
3. Open the **Camera Live** tab in the 3D View sidebar. Work from a saved Blender file.

## Edit and verify

Use **Diagnose Saved Framing** with a JSON specification that names the scene, camera, subjects, sample frames and constraints. A viable camera offset can feed **Check Framing Suggestion Copy**. Use **Check**, **Create Verified Copy**, then **Open Verified Copy** for supported edits.

The panel supports static position and lens changes, adjacent cuts, a named bone focus, simple camera motion easing, focus timing and explicit camera-group retiming. The Graph Editor and camera properties remain available for native fine editing. Framing and collision observations cover the specified subject points, frames and sampled camera paths.

## Command line

Run `cli.py` from this add-on directory with Blender's bundled Python and an explicit Blender executable:

```text
<Blender Python> cli.py --blender <Blender executable> <request.json>
```

The input has keys `action` and `params`. Supported actions are `diagnose`, `check`, `apply`, `cancel` and `result`. Choose a new job directory and provide the exact saved source path and SHA-256. To use the existing blenderctl extension executor, point its script descriptor at this directory's `cli_bridge.py` and use the same action and params as bridge parameters.

Camera Workflow is available under GPL-3.0-or-later. See [COPYING](COPYING) and [support notice](SUPPORT-NOTICE.md).
