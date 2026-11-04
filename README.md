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

The completed JSON result includes the absolute `screenshot_path`, scene/camera names, dimensions, render engine, byte size, format, and SHA-256. The mailbox remains local to the Windows Blender/CLI user. The uploader described below can send only the PNG produced for a completed `capture_screenshot` job; it does not upload projects or unrelated files.

Iterate locally by submitting a modeling job, waiting for its result, then submitting a follow-up job (for example `move_object`, `set_dimensions`, or `create_material`) and capturing another screenshot. `duplicate_object` is restricted to mesh objects and copies mesh data. `delete_object` is intentionally explicit and irreversible through this add-on; use it only for a named object you intend to remove.

### Google Drive screenshot transfer (Windows)

The optional local uploader uses the Windows user's own Google OAuth identity. It does not use Arena's Google Drive connector authorization and does not create a public listener. The OAuth file is read locally at runtime and is never part of the repository:

```text
google_oauth_client.json
```

Place the Google Cloud **Desktop app** OAuth JSON at the repository root under that exact name. `.gitignore` excludes it. Do not paste its contents or any token into Arena. On the first setup, run this from PowerShell in the repository root:

```powershell
python -m arena_workshop authorize-drive
```

This validates the Installed OAuth JSON, opens Google's authorization page in your browser, and requests only the `drive.file` scope. Choose the same Google account that Arena's Drive connector can access, review and explicitly approve the requested access, then allow the browser to return to the local loopback callback. If the Google consent screen is in Testing, the account may also need to be listed as a test user. The flow uses PKCE and a temporary `127.0.0.1` callback; the authorization code is handled locally. No code or token needs to be copied. The refresh token is DPAPI-protected for the current Windows user at:

```text
%LOCALAPPDATA%\ArenaBlenderWorkshop\drive_tokens.dpapi
```

There is no plaintext fallback. If Windows-protected storage is unavailable, authorization fails instead of writing a plaintext token. Re-run `authorize-drive` if consent was denied, revoked, or the refresh token is no longer accepted.

When the add-on has completed a screenshot job and the CLI is waiting for its result, the PNG upload happens automatically:

```powershell
python -m arena_workshop capture_screenshot --wait --timeout 180
```

The upload creates or reuses an app-owned Drive folder named **ArenaBlenderWorkshop Screenshots** and stores the PNG there. The Drive filename contains the job ID (`arena-blender-<job_id>.png`); the file description and app-private metadata also associate it with that job. A repeated upload of the same job and identical PNG reuses the existing Drive file; if the same job ID is associated with different image bytes, it fails rather than creating another file. Uploads are limited to 20 MiB and retry transient network/service failures up to three attempts. The local screenshot is never deleted when an upload succeeds or fails.

The completed mailbox result retains the screenshot metadata and adds `result.drive_upload` with status, Drive file ID, filename, MIME type, and retrieval reference, or a structured error. To upload/retry a previously completed screenshot, use:

```powershell
python -m arena_workshop upload-screenshot --job-id <job_id>
```

The existing immediate-return CLI behavior is unchanged: without `--wait`, it prints the job ID and exits before Blender has produced a result, so that invocation cannot upload automatically. Use `upload-screenshot` after the result exists. The local queue still does not let a remote Arena session submit jobs to Windows; this feature only handles local screenshot results. A successful Drive upload is not itself proof that Arena retrieved or visually inspected the image. The Drive file must be retrieved and inspected separately through the connected Arena integration.

## One-command Blender 5.2 add-on install and update (Windows)

The repository includes `update_blender_addon.ps1`. It uses the Python standard library and Git already required by this project; it does not download Blender, need administrator access, or restart Blender. The install location is `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\arena_workshop`.

### Initial setup

1. Install Git for Windows and Python (the same `python` command used for the CLI). For a fresh checkout, run `git clone --branch arena/aadcacbd-arenablenderworkshop --single-branch https://github.com/Raaniscool/ArenaBlenderWorkshop.git C:\Users\Raani\Documents\ArenaBlenderWorkshop`. If already cloned, confirm the checkout is on `arena/aadcacbd-arenablenderworkshop`.
2. Ensure the checkout is clean. Close Blender normally.
3. From the repository directory, run:

   ```powershell
   .\update_blender_addon.ps1
   ```

   On first install the script creates missing Blender `scripts\addons` directories and installs the package. Start Blender and enable **Arena Blender Workshop MVP** once in **Edit → Preferences → Add-ons**.

### Updating later

Close Blender normally, open PowerShell in the repository directory, and run the same one command:

```powershell
.\update_blender_addon.ps1
```

The updater verifies the repository and exact expected branch, refuses uncommitted or untracked changes, checks for running `blender.exe` / `blender-launcher.exe` processes, runs `git pull --ff-only`, stages and verifies the add-on, backs up any current install, and replaces only the `arena_workshop` package. It reports the pulled commit, install path, and backup path. Existing backups are never automatically deleted. Blender preferences, other add-ons, mailbox contents, and `.blend` projects are not touched.

If Blender is running, the updater stops before pulling or installing; close Blender using **File → Quit** or its normal window close, then rerun the command. It never force-stops or restarts Blender. A dirty checkout or a different branch also stops safely; save/commit or move the local changes elsewhere, then rerun from the expected branch. Git pull failures leave the installed add-on unchanged.

Backups are stored under `%LOCALAPPDATA%\ArenaBlenderWorkshop\addon-backups\arena_workshop_<timestamp>_<id>`. If an installation step fails, the updater attempts to restore the previous package and prints whether rollback succeeded plus the backup path. If it reports rollback needs attention, keep Blender closed and restore from that backup: rename the current `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\arena_workshop` directory aside (do not delete it), then copy the backup directory to that exact `arena_workshop` location. Do not replace or remove any other add-on. Keep backups until the new install has been verified.

## Local CLI and Windows tests

Run commands from the repository root in PowerShell while Blender 5.2 is open with the add-on enabled. The CLI exposes only the allowlisted operations. `--wait` polls the result for that single enqueued job; it does not resubmit. Default timeout is 60 seconds; `--timeout SECONDS` changes it. Exit codes: `0` completed (including successful upload), `1` failed/unexpected Blender result, `2` timed out, `3` screenshot upload or upload-result persistence failed. A Drive upload failure does not remove the screenshot or mark a successful Blender capture as failed; its separate `result.drive_upload` object contains the error. Omitting `--wait` keeps the previous behavior of printing the job ID and result path immediately.

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

Each successful call prints structured JSON. Check the `screenshot_path` in both capture results; the original `Cube` is not targeted by this workflow. The test checks the existing CLI/API results and adds a fake-`bpy` sequential workflow regression, but **does not replace executing this procedure in Blender 5.2**. If local Drive authorization is configured, a waited screenshot job automatically reports its Drive upload status and file ID as well as its local path; this documentation does not claim a real Windows/Blender upload was tested.

## Current limitations

- No Linear worker or Linear integration is included.
- Screenshot rendering uses the captured scene's active camera and current render engine; the camera view may need manual framing, and scenes without a linked camera fail cleanly. Render performance depends on the user's installed engine/device.
- Screenshots are always retained locally. When the local Windows user authorizes Drive, the CLI can upload a screenshot and record its Drive file ID; Arena retrieval and actual visual inspection remain separate and must be verified independently.
- `delete_object` is deliberately destructive for the named object. There is no arbitrary code, unrestricted operator, `.blend` save, or automatic scene cleanup.
- Automated operations use a Blender API test double; real Blender 5.2 enable/render testing remains necessary for this screenshot implementation.

## Run tests and compilation checks

From the repository root:

```text
python -m unittest discover -s tests -v
python -m unittest tests.test_addon_updater -v
python -m compileall -q arena_workshop tests
```
