# Included support code

Camera Workflow ships the local file guards, process ownership and read-only scene witnesses it uses to save and verify camera edits. The implementations come from the project-maintained Blender tooling.

- `_support/blenderctl/` contains process and filesystem utilities and the camera transaction's read-only Blender scene witnesses. The upstream project is [blenderctl](https://github.com/tsist/blenderctl).
- `_support/animation_curves_workflow_addon/` contains the Action witness functions used to retain existing animation during timing changes.
- `_vendor/` contains the Camera Live and Camera Placement code used by the add-on.

Camera Workflow and its bundled code are distributed under GPL-3.0-or-later. The GPL version 3 text is in [COPYING](COPYING).
