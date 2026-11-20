# Camera Workflow 0.8.3

Camera Workflow organizes shots and saves verified copies of Blender scenes. The Camera Live sidebar provides shot preview, candidate comparison, framing diagnosis and checks for camera edits.

## Install on Windows

The add-on accepts the official Windows x64 distributions **Blender 5.3.0** build `02f0899d78e3` and **Blender 5.2.1 LTS** build `9e2066aef7ef`. It verifies SHA-256 for Blender and its bundled Python. Run each saved-copy transaction from check through final readback with one Blender version.

1. Download the `camera-workflow-0.8.3.zip` release asset or build it with `python addons/build_camera_zip.py camera-workflow-0.8.3.zip`.
2. In Blender, open **Edit > Preferences > Add-ons > Install from Disk**, select the ZIP and enable **Camera Workflow Windows**.
3. Open the **Camera Live** tab in the 3D View sidebar. Work from a saved Blender file.

## Edit and verify

Use **Diagnose Saved Framing** with a JSON specification that names the scene, camera, subjects, sample frames and constraints. A viable camera offset can feed **Check Framing Suggestion Copy**. Use **Check**, **Create Verified Copy**, then **Open Verified Copy** for supported edits.

The panel supports static position and lens changes, adjacent cuts, a named bone focus, simple camera motion easing, focus timing and explicit camera-group retiming. The Graph Editor and camera properties remain available for native fine editing. Framing and collision observations cover the specified subject points, frames and sampled camera paths.

The Blender 5.3 saved-copy qualification covers the bounded camera operations on saved scenes. Choose SOLID for Blender 5.3 camera previews. Existing compositor effects stacks require a stack-aware state witness before camera retiming or strict technical-scene edits can proceed.

## Command line

Run `cli.py` from this add-on directory with Blender's bundled Python and an explicit Blender executable:

```text
<Blender Python> cli.py --blender <Blender executable> <request.json>
```

The input has keys `action` and `params`. Supported actions are `diagnose`, `check`, `apply`, `cancel` and `result`. Choose a new job directory and provide the exact saved source path and SHA-256. To use the existing blenderctl extension executor, point its script descriptor at this directory's `cli_bridge.py` and use the same action and params as bridge parameters.

After upgrading the add-on, start a fresh CHECK in a new job directory. Finish transactions created by 0.8.2 with the previous package and Blender 5.2.1.

Camera Workflow is available under GPL-3.0-or-later. See [COPYING](COPYING) and [support notice](SUPPORT-NOTICE.md).

### Linux 5.3.0 development port: native static-camera panel

On the exact official Linux x64 build 02f0899d78e3, open a trusted, enrolled, clean
saved scene. Sidebar > Camera Live > Camera Workflow · Linux static optics.
CHECK validates the saved source twice without publishing any scene, and binds the
window, scene, file identity, SHA, output path and proposed optics/location.
Choose an absolute NEW output path inside an existing private (0700) directory.
APPLY saves a new copy only. Read its receipt.json and candidate.blend together;
the original active scene stays open unchanged. Synchronous bounded transactions
block the interface until finished. Linux requires bubblewrap, libseccomp and
sealed memfds. Worker Blender instances get read-only enrolled snapshots, isolated
temp storage and denied networking. No Windows deny-write/Job Object equivalence;
requires a trusted host, user, runtime, filesystem and no concurrent writers.
No Linux production animation, DOF, adjacent cuts, retiming, GUI cancellation or
full Windows parity is represented. Two exact SHA identities remain permanently qualified. For a different file,
the CHECK dialog offers a **one-operation, default-off** “Enroll my own trusted
static work-copy” option. Do not use it with downloaded or third-party scenes.
Save an uncompressed .blend (16 MiB maximum) inside a private owner-only
directory, with no external assets. Disable compression in Blender Save As.
Workers twice probe sealed bytes with autoexec disabled: only bounded local
meshes, cameras, lights, empties, selected world/material nodes and generated or
packed static images qualify. Rigged/animated data, text, libraries, caches,
physics, constraints/modifiers, VSE strips, nontrivial external paths and
non-allowlisted IDs/nodes fail. The one recognized installed stock UI brush
reference is not a project resource and is not copied. Only a new private
candidate and receipt are published, never written into the open file.
Enrollment does not persist. This is not a loader for hostile content; the
caller must already trust the project it opens in its own Blender session.

#### Linux static pose and focus development slice

Sidebar > Camera Live > Camera Workflow · Linux static camera > CHECK pose,
optics and focus. Turn **Change lens / ortho scale** off for a pose- or
focus-only change. XYZ rotation is absolute (UI display in scene angle units;
Python operator values are radians). Accepted cameras are unparented, single,
unanimated XYZ cameras without delta rotation. For **Depth of field** choose
Keep unchanged, Disable (preserve setup), Enable: manual distance, or Enable:
focus on object. The latter targets a named local unparented static mesh or
empty; the field uses Blender's object search. DOF changes require a perspective
camera with no bone subtarget. Focus distance is in scene units, f-stop is
dimensionless. Manual focus explicitly clears any object target. Disabling DOF
does not clear the saved target or aperture. CHECK binds all selected fields;
APPLY verifies the new copy, preserves the source and never renders. These
controls are not the Windows rig-bone/shot-table DOF operator or an appearance test.

### Native Linux advanced CHECK / APPLY

Open a trusted owned, clean, uncompressed project work-copy (≤16 MiB), held in
a private directory. Open Camera Live > Camera Workflow > CHECK advanced
camera operation. Paste the one operation below, enter a **new** directory in
an owner-private parent, and explicitly authorize this work-copy. CHECK reads
two independently isolated snapshots and predicts the changed native data;
the separate APPLY button creates candidate.blend and receipt.json, never
replaces the existing project. Each operation consumes one CHECK. The optional
CLI's query wraps the same operation as {"scene":"Scene","camera":"Camera",
"sequence":{...}}; the named camera must be active on the saved frame. Keep
the saved frame on a stable shot/pose for cut or retime operations.

* Add native timeline camera marks:
  `{"kind":"cut","operation":"cuts","cuts":[{"frame":1,"camera":"Camera","name":"Shot A"},{"frame":11,"camera":"CameraB","name":"Shot B"}]}`
* Retime a complete bounded group with camera cuts and existing eligible
  camera transform curves:
  `{"kind":"cut","operation":"retime","source":[1,21],"destination":[1,41],"cameras":["Camera","CameraB"]}`
* New motion on an unanimated XYZ camera:
  `{"kind":"motion","interpolation":"EASE_IN_OUT","keys":[{"frame":1,"location":[0,0,2],"rotation_euler":[0,0,0]},{"frame":21,"location":[4,2,2],"rotation_euler":[0.2,0.1,0]}]}`.
  Rotation values are radians. LINEAR, CONSTANT, EASE_IN, EASE_OUT and
  EASE_IN_OUT create native F-curves; interpolation is checked at sample frames.
* Aim the camera's depth of field at an existing exact pose bone:
  `{"kind":"bone","focus_object":"Subject_Bank","focus_subtarget":"Eye.L","fstop":2.8}`.
  This links the native camera DOF object and subtarget; it does not rotate the
  camera or author rig animation. A bounded existing target-bone Action may
  animate the target. A typo fails; no fallback to the rig origin.

Security and scope: original binary/worker pins, sealed work-copy isolation,
no networking and separate cold readback required. No rig constraints, drivers,
NLA, shared actions, arbitrary curves, foreign files, VSE or external caches.
Preservation covers declared scoped native channels, geometry/selected material,
scene and object witnesses, not every possible Blender RNA property. These
native timeline markers are **not** the original frozen Windows shot-row data;
there is no shot-list/animation migration claim. No render, playback quality or
graphical click-through tests are implied.

Two related advanced requests:

* Change one established native cut without moving the other markers:
  `{"kind":"cut","operation":"move_cut","left":"Cut A","right":"Cut B","left_last":15}`.
  These two named camera marks must be adjacent. “Cut B” will start on frame 16.
* Change the easing of an existing eligible, unshared two-key XYZ location
  action on the active camera:
  `{"kind":"motion_ease","interpolation":"EASE_IN"}`.
  EASE_IN, EASE_OUT and EASE_IN_OUT preserve endpoints and outer handles;
  inner shape and sampled camera position are verified.

Candidate chaining: both the static and advanced writers normalize the verified
Blender-supplied material library-weak-reference to the official runtime brush
to its absolute path **inside the saved copy only**. Exact known path, type,
no strong project reference, pinned stock asset bytes and no unrelated path
changes are checked. This permits chaining saved candidates at new folder
depths with the same runtime. It neither authorizes arbitrary asset paths nor
repairs copies from an older build whose paths already resolve incorrectly.

Local native ShaderNodeUVMap is supported in material shader trees in this build.
Camera-only edits now witness each static material's named UV map, From Instancer
setting, texture-image identity, node identity/type and linked socket endpoints.
This does not admit other unlisted shader types or relax external data checks.

#### Existing focus-helper timing and legacy table protection

Advanced CHECK accepts
`{"kind":"focus_timing","helper":"FocusTarget","new_start":6,"locked_frames":[1,10,16]}`.
The perspective camera must already use the named exclusive unparented EMPTY for
DOF. Its single local, non-shared action must already contain three location
channels, with four LINEAR / FREE keys (hold, onset, arrival, hold end) on each.
The saved frame must be outside the moving interval. This moves the second key
and its two handle times only; no target, helper, action, distance, lens or
other clip is created/changed. Samples and a separate reopened copy establish
that the onset changed while the locked world-space positions remain intact.
This is not a migration of the original Windows shot-table workflow.

Every static and advanced worker loads an isolated, pinned minimal read-only
legacy camera_live_shots schema before opening any project. Nonempty typed
tables (including a row with a missing camera) and ambiguous raw storage
are refused before editing or saving. The main Blender profile is not
modified by this probe. A legitimate project with a dedicated Windows shot
table needs a compatible editor/migration; native timeline markers are not a
substitute for that data.

#### Deliberate exception: exact legacy Camera Live adjacent boundary

The static and other advanced operations still reject nonempty typed Camera Live
shot tables. Only the dedicated operation below may edit a bounded table in an
authorized clean work-copy. It changes one existing adjacent-row boundary, not
the scene camera, frame, native markers or any camera/action data:

`{"kind":"legacy_cut","left":"Opening","right":"Answer","left_camera":"Camera","right_camera":"B","old_left_last":8,"new_left_last":12}`

Use the registered original Camera Live **SEQUENCE** mode, two or more unique
contiguous shot rows covering the scene range, valid local camera pointers and
no conflicting native camera-bound timeline marks. Ordinary annotation marks
are retained. Both shots must remain nonempty, and the parked frame may not
switch to another shot. The worker binds actual source identity, both original
row and camera names, and the old inclusive boundary. It predicts and verifies
the complete row table (including saved camera-data identities, set/default
flags and bounded additional scalar annotations), not just the two numbers.
Input ambiguity, missing camera, stale old boundary, nonadjacent rows, unsafe
metadata or marker conflicts are rejected; inputs are never overwritten.
This capability does not convert marker tracks or expose full legacy production
functionality. Use the original provider to inspect the copied table if required.

#### Optional Linux fixed-frame camera A/B (viewport only)

In the open saved review copy, stop playback, use Object Mode, select Solid
shading in a single non-Quad 3D View and turn Lock Camera to View off.
Sidebar > Camera > Fixed-frame Camera A/B. Pick two different local cameras,
confirm the exact open copy, and use Show A / Show B. The comparison uses
the area-local camera: no frame change, scene-camera change, file save or
render. Restore Original View releases and restores the captured view. If the
view has been changed by somebody else, use Release Without Restoring instead.
This is not a cross-file/candidate viewer and does not compare rendered images.
