# Arena Blender Workshop

A local Blender connector using a strict JSON protocol and an atomic file mailbox. The Blender add-on polls the mailbox using a Blender application timer and runs the fixed operation allowlist on Blender's main thread. The bridge opens no network listener and does not use arbitrary Python, shell commands, or unrestricted Blender operators.

## Phase 3A.1: basic modeling operations in the startup scene

The protocol remains version `1.0`; previous `hello_test` and `create_test_object` jobs continue to work. The current allowlist is:

| Operation | Required parameters | Optional parameters / behavior |
| --- | --- | --- |
| `hello_test` | `message` | Reports Blender version and the active scene (which may differ from the modeling target). |
| `create_test_object` | none | Creates or detects the fixed `ArenaWorkshopTestCube` in the captured startup scene. |
| `create_primitive` | `primitive_type`, `object_name` | Optional `location`, `rotation`, `scale`; types: `cube`, `uv_sphere`, `cylinder`, `plane`, `cone`. |
| `move_object` | `object_name`, `location` | Sets the object's location. |
| `rotate_object` | `object_name`, `rotation` | Sets Euler rotation in degrees (converted to Blender radians). |
| `scale_object` | `object_name`, `scale` | Sets the object's scale; zero components are rejected. |
| `rename_object` | `object_name`, `new_name` | Renames the existing object; does not create a replacement. |
| `create_material` | `material_name`, `object_name`, `base_color`, `roughness`, `metallic` | Creates a Principled material and assigns it to the named mesh object. `base_color` is linear RGBA. |

Vectors are three numeric values except `base_color`, which has four. Location, rotation, scale, color, roughness, and metallic are range-checked; object/material names are bounded and checked. Unknown fields and operations are rejected. Name conflicts and missing targets return structured failure results rather than replacing objects or materials.

At add-on registration, the target is resolved to Blender's existing normal startup scene (normally `Scene`, containing the original `Cube`) and retained for every job, even if the user later switches the active scene. Jobs do not create a separate scene or change the active scene. Newly created objects are linked to that startup scene. The original cube and unrelated existing objects and materials are preserved; only an explicitly named object is transformed, renamed, or assigned a newly created material. Modeling results report the actual target scene name. Creating a primitive with a retried job ID is idempotent; a different job cannot silently replace an object with the same name. Transforms are assignments and can be retried safely. No operation saves or overwrites the `.blend` file.

## Install or update the add-on in Blender 5.2 on Windows

This is a legacy add-on package (`bl_info` in `arena_workshop/__init__.py`). Its expected per-user folder is:

```text
%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\arena_workshop\
```

The installed package must include `__init__.py`, `mailbox.py`, `protocol.py`, and **`operations.py`**.

1. Close Blender 5.2. In File Explorer, enter `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons` in the address bar; create the missing `scripts\addons` folders if necessary.
2. For a new install, copy the repository's whole `arena_workshop` folder into `addons`.
3. To update the earlier Phase 2A install, first copy the existing installed `arena_workshop` folder to a separate backup location. Then replace its contents with the repository's current `arena_workshop` folder. Do not overwrite the old copy before making that backup; do not replace any other add-on folder.
4. Start Blender 5.2. Open **Edit → Preferences → Add-ons**, search **Arena Blender Workshop MVP**, and enable it. If Blender does not list it, check the path and ensure `arena_workshop\__init__.py` is directly inside the package folder.
5. Keep Blender open with the add-on enabled while sending jobs. The add-on timer runs inside Blender. Run the CLI as the same Windows user so it uses the same `%LOCALAPPDATA%\ArenaBlenderWorkshop\queue` mailbox.

A completed `hello_test` result with `blender_version` beginning `5.2` verifies that the running Blender instance consumed the job. There is no separate status indicator. For the smoke test, use a disposable Blender startup and do not save it over an existing project.

To uninstall, disable the add-on in **Edit → Preferences → Add-ons**, close Blender, then remove only the installed `arena_workshop` folder. Keep or restore the backup as needed. Do not delete the mailbox or any `.blend` project as part of uninstalling.

## Local CLI and Windows tests

Run commands from the repository root in PowerShell while Blender 5.2 is open with the add-on enabled. The CLI exposes only the allowlisted operations. `--wait` polls the result for that single enqueued job; it does not resubmit. Default timeout is 60 seconds; `--timeout SECONDS` changes it. Exit codes: `0` completed, `1` failed/unexpected result, `2` timed out. Omitting `--wait` keeps the previous behavior of printing the job ID and result path immediately.

Basic test sequence (use unique names if repeating the create commands):

```powershell
python -m unittest discover -s tests -v
python -m arena_workshop hello_test --wait --timeout 120
python -m arena_workshop create_test_object --wait --timeout 120
python -m arena_workshop create_primitive --primitive-type cube --object-name Phase3Cube --location 0 0 0 --rotation 0 0 0 --scale 1 1 1 --wait --timeout 120
python -m arena_workshop move_object --object-name Phase3Cube --location 1 2 3 --wait --timeout 120
python -m arena_workshop rotate_object --object-name Phase3Cube --rotation 0 0 45 --wait --timeout 120
python -m arena_workshop scale_object --object-name Phase3Cube --scale 2 2 2 --wait --timeout 120
python -m arena_workshop rename_object --object-name Phase3Cube --new-name Phase3CubeRenamed --wait --timeout 120
python -m arena_workshop create_material --material-name Phase3Material --object-name Phase3CubeRenamed --base-color 0.8 0.3 0.1 1 --roughness 0.35 --metallic 0.7 --wait --timeout 120
python -m arena_workshop create_primitive --primitive-type uv_sphere --object-name Phase3Sphere --wait --timeout 120
python -m arena_workshop create_primitive --primitive-type cylinder --object-name Phase3Cylinder --wait --timeout 120
python -m arena_workshop create_primitive --primitive-type plane --object-name Phase3Plane --wait --timeout 120
python -m arena_workshop create_primitive --primitive-type cone --object-name Phase3Cone --wait --timeout 120
```

The CLI validates modeling arguments before writing them to the mailbox. Protocol, mailbox, and fake-`bpy` operation tests run without Blender; they are not a substitute for running these commands with the real Blender 5.2 add-on.

## Current limitations

- No Linear worker or Linear integration is included in this phase.
- Automated operation tests use a small Blender API test double. Actual mesh/material behavior still requires the Windows Blender 5.2 runtime test above.
- Primitive geometry uses fixed lightweight defaults; there are no arbitrary dimensions, modifiers, file saves, deletions, or general-purpose scripts.

## Run tests and compilation checks

From the repository root:

```text
python -m unittest discover -s tests -v
python -m compileall -q arena_workshop tests
```
