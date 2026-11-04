# Arena Blender Workshop

A local Blender connector using a strict JSON protocol and an atomic file mailbox. The Blender add-on polls the mailbox using a Blender application timer and runs the fixed operation allowlist on Blender's main thread. The bridge opens no network listener and does not use arbitrary Python, shell commands, or unrestricted Blender operators.

## Phase 3B: startup-scene modeling and screenshot feedback

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
| `duplicate_object` | `object_name`, `new_name` | Copies a named mesh and its data into the startup scene; default placement offsets one Blender unit on X. Optional `location` overrides placement. |
| `set_dimensions` | `object_name`, `dimensions` | Sets positive X/Y/Z dimensions in Blender units. |
| `delete_object` | `object_name` | Deletes only the explicitly named startup-scene object. This is destructive and has no undo step in the add-on. |
| `capture_screenshot` | none | Renders the captured startup scene through its active camera. Optional `width` (64–1280) and `height` (64–720); defaults to 640×480. |

Vectors are three numeric values except `base_color`, which has four. Location, rotation, scale, color, roughness, and metallic are range-checked; object/material names are bounded and checked. Unknown fields and operations are rejected. Name conflicts and missing targets return structured failure results rather than replacing objects or materials.

At add-on initialization, the target is captured from Blender's existing normal startup scene (normally `Scene`, containing the original `Cube`) and retained for every job, even if the user later switches the active scene. Initialization is deferred through a Blender application timer, outside the restricted add-on registration context. Jobs do not create a separate scene or change the active scene. Newly created and duplicated objects are linked to the captured startup scene. Objects and materials are preserved unless an operation explicitly names them; `delete_object` is the only deletion operation. Modeling results report the actual target scene name. Creating a primitive with a retried job ID is idempotent; a different job cannot silently replace an object with the same name. No operation saves or overwrites the `.blend` file.

### Screenshot feedback loop

`capture_screenshot` renders the captured startup scene using its existing active camera and the current render engine. Blender temporarily sets a bounded PNG resolution (default 640×480, maximum 1280×720), disables render-window display for the capture, and restores the scene's render filepath, output format, resolution, display mode, and Cycles sample count afterward. It does not change the active scene, camera, workspace, or save the `.blend` file. A missing/unlinked camera and render failures return structured job errors.

Screenshots are retained at:

```text
%LOCALAPPDATA%\ArenaBlenderWorkshop\queue\screenshots\<job_id>.png
```

The completed JSON result includes the absolute `screenshot_path`, scene/camera names, dimensions, render engine, byte size, format, and SHA-256. The mailbox is local to the Windows Blender/CLI user; it does **not** upload images to Arena. To let Arena inspect a result, attach the PNG from the returned path in the Arena conversation. This manual attachment is currently required; the repository has no authenticated screenshot-transfer service.

Iterate visually by submitting a modeling job, waiting for its result, attaching the returned PNG for review, then submitting a follow-up job (for example `move_object`, `set_dimensions`, or `create_material`) and capturing another screenshot. `duplicate_object` is restricted to mesh objects and copies mesh data. `delete_object` is intentionally explicit and irreversible through this add-on; use it only for a named object you intend to remove.

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

### Compact Blender 5.2 verification (PowerShell)

Run the unit suite from the repository root, then enable the add-on in Blender 5.2 and keep Blender open. The following workflow generates unique names, uses only its own test objects, checks each CLI exit code, captures screenshots before and after cleanup, and attempts to remove test objects even if a step fails. The test material becomes unused after object cleanup; remove only that generated material by name in Blender's Material Properties if you also want to clean it up.

```powershell
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Unit tests failed with exit code $LASTEXITCODE" }

function Invoke-ABWJob {
    param([string[]]$CliArgs)
    $output = & python -m arena_workshop @CliArgs --wait --timeout 180 2>&1
    $exitCode = $LASTEXITCODE
    $output | ForEach-Object { Write-Host $_ }
    if ($exitCode -ne 0) {
        throw "Arena Blender Workshop job failed with exit code ${exitCode}: $($CliArgs -join ' ')"
    }
}

$tag = "ABWVerify_$([guid]::NewGuid().ToString('N').Substring(0,8))"
$source = "${tag}_Source"
$copy = "${tag}_Copy"
$material = "${tag}_Material"
$createdObjects = [System.Collections.Generic.List[string]]::new()
$materialCreated = $false
try {
    Invoke-ABWJob -CliArgs @('create_primitive', '--primitive-type', 'cube', '--object-name', $source, '--location', '2', '0', '0')
    $createdObjects.Add($source)
    Invoke-ABWJob -CliArgs @('duplicate_object', '--object-name', $source, '--new-name', $copy, '--location', '4', '0', '0')
    $createdObjects.Add($copy)
    Invoke-ABWJob -CliArgs @('set_dimensions', '--object-name', $copy, '--dimensions', '1', '1.5', '2')
    Invoke-ABWJob -CliArgs @('create_material', '--material-name', $material, '--object-name', $copy, '--base-color', '0.2', '0.5', '0.8', '1', '--roughness', '0.4', '--metallic', '0.2')
    $materialCreated = $true
    Invoke-ABWJob -CliArgs @('capture_screenshot', '--width', '640', '--height', '480')
    Invoke-ABWJob -CliArgs @('delete_object', '--object-name', $copy)
    $createdObjects.Remove($copy) | Out-Null
    Invoke-ABWJob -CliArgs @('delete_object', '--object-name', $source)
    $createdObjects.Remove($source) | Out-Null
    Invoke-ABWJob -CliArgs @('capture_screenshot', '--width', '640', '--height', '480')
}
finally {
    for ($i = $createdObjects.Count - 1; $i -ge 0; $i--) {
        try {
            Invoke-ABWJob -CliArgs @('delete_object', '--object-name', $createdObjects[$i])
        }
        catch {
            Write-Warning "Test-object cleanup failed: $_"
        }
    }
    if ($materialCreated) {
        Write-Host "Remove only the unused test material '$material' in Blender if desired."
    }
}
```

Each successful call prints structured JSON. Check the `screenshot_path` in both capture results; the original `Cube` is not targeted by this workflow. The test checks the existing CLI/API results and adds a fake-`bpy` sequential workflow regression, but **does not replace executing this procedure in Blender 5.2**. For Arena visual review, manually attach a PNG from the reported local path; the queue does not upload image bytes.

## Current limitations

- No Linear worker or Linear integration is included.
- Screenshot rendering uses the captured scene's active camera and current render engine; the camera view may need manual framing, and scenes without a linked camera fail cleanly. Render performance depends on the user's installed engine/device.
- Screenshots are local files. Arena cannot fetch them automatically; manual PNG attachment is required for visual inspection.
- `delete_object` is deliberately destructive for the named object. There is no arbitrary code, unrestricted operator, `.blend` save, or automatic scene cleanup.
- Automated operations use a Blender API test double; real Blender 5.2 enable/render testing remains necessary for this screenshot implementation.

## Run tests and compilation checks

From the repository root:

```text
python -m unittest discover -s tests -v
python -m compileall -q arena_workshop tests
```
