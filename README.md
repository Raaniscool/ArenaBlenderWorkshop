# Arena Blender Workshop

Minimal MVP path: Arena Agent Mode submits a structured job to the existing Linear queue; a Windows worker polls Linear over outbound HTTPS; the worker hands validated JSON to Blender through a local atomic file mailbox; a Blender 5.2 add-on executes a fixed allowlisted operation and returns a JSON result through the mailbox; the worker reports the result to Linear.

No local HTTP listener, port forwarding, tunnel, arbitrary shell execution, or arbitrary remote Python execution is used.

## Current implementation phase

The repository currently contains the **local protocol and Blender mailbox bridge**:

- `arena_workshop/protocol.py` strictly validates version 1.0 jobs and permits only `hello_test` and `create_test_object`.
- `arena_workshop/mailbox.py` uses atomic same-volume file renames under `%LOCALAPPDATA%\ArenaBlenderWorkshop\queue`.
- `arena_workshop/__init__.py` is a Blender add-on that polls the mailbox with Blender application timers and executes operations on Blender's main thread. `create_test_object` creates one fixed cube in a scene named `ArenaWorkshopTest`; it does not save the `.blend` file or change the active scene.
- `python -m arena_workshop hello_test` or `python -m arena_workshop create_test_object` enqueues a fixed local smoke-test job; it accepts no custom operation payload.
- Add `--wait` to print the result as formatted JSON after Blender completes it. The default timeout is 60 seconds; use `--timeout SECONDS` to change it. Waiting polls the same job and never resubmits it.
- `tests/test_protocol_mailbox.py` tests validation and file-mailbox behavior without Blender or Windows.

The Linear API worker and Windows credential setup have **not** been implemented. No credentials or external settings are stored here. Blender itself is not available in this development sandbox, so the add-on has not been exercised inside Blender 5.2 yet.

## Install the add-on in Blender 5.2 on Windows

This repository uses Blender's legacy add-on package layout (`bl_info` in `arena_workshop/__init__.py`). Install the package folder in the per-user add-ons directory:

1. Close Blender 5.2 before copying files. In File Explorer, enter `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons` in the address bar. Create the missing `scripts\addons` folders if necessary.
2. Copy the repository's **`arena_workshop` folder** into that directory. The resulting file must be `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\arena_workshop\__init__.py`.
3. **Do not overwrite an existing `arena_workshop` folder.** If one is already there, first make a separate backup copy (for example `arena_workshop.backup`) and compare the contents; stop rather than replacing files you need.
4. Start Blender 5.2. Open **Edit → Preferences → Add-ons**, search for **Arena Blender Workshop MVP**, and enable its checkbox. If it is not listed, check the folder layout and Blender version; do not install over another copy.
5. Keep this Blender process open, with the add-on enabled, while using the CLI. The add-on's timer runs inside Blender; a closed Blender process cannot consume jobs. Use the same Windows account for Blender and the CLI because both use that account's `%LOCALAPPDATA%` mailbox.

To verify the add-on is running, run `python -m arena_workshop hello_test --wait` from the repository root. A completed result containing `blender_version` beginning with `5.2` verifies that this Blender instance consumed the job. There is no separate add-on status indicator.

To uninstall safely, disable the add-on in **Edit → Preferences → Add-ons**, close Blender, then remove only the `arena_workshop` folder you installed in `scripts\addons`. Do not remove the mailbox or any `.blend` files as part of uninstalling. If you backed up an earlier add-on folder, restore it only after removing this copy.

## Local smoke test

Run these from the repository root in a Windows terminal while Blender 5.2 is open with the add-on enabled:

```text
python -m unittest discover -s tests -v
python -m arena_workshop hello_test --wait
python -m arena_workshop create_test_object --wait
```

The first command tests the local Python package. The smoke-test commands enqueue one job each, wait up to 60 seconds, and print the result as formatted JSON. For example, to allow up to 120 seconds:

```text
python -m arena_workshop create_test_object --wait --timeout 120
```

A successful `hello_test` reports Blender's version. A successful `create_test_object` reports `scene_name: ArenaWorkshopTest`, `object_name: ArenaWorkshopTestCube`, 8 vertices, and 6 polygons. Running it again reports `created: false` rather than making a duplicate. Neither operation saves the current `.blend` file. Use a disposable Blender startup for the smoke test and do not save it over an existing project.

When `--wait` is omitted, the existing behavior is preserved: the command prints the job ID and result-file path immediately. With `--wait`, exit code `0` means completed, `1` means the job failed or returned an unexpected status, and `2` means the timeout elapsed. A timeout does not cancel or resubmit the queued job; Blender may still finish it later.

## MVP sequence

1. Test protocol/mailbox locally.
2. Install and smoke-test the add-on in Blender 5.2 using the steps above.
3. After you configure and approve the Linear OAuth app, add the outbound-only Linear worker and safe credential retrieval.
4. Run a fresh `create_test_object` job through Arena → Linear → worker → Blender → Linear → Arena.
5. Add the two-chat test and image transfer only after the first end-to-end result succeeds.

OAuth scopes intended for the worker: `read`, `issues:create`, `comments:create`. The worker must be restricted to the BlenderArena (BLE) team before it is enabled.

## Run the current tests

From the repository root, with Python 3 installed:

```text
python -m unittest discover -s tests -v
```
