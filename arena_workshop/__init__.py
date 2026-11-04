"""Arena Blender Workshop add-on (Blender 5.2 target).

The add-on is deliberately local-only: it watches a filesystem mailbox and
executes a small allowlist from Blender's main-thread timer. It opens no port.
"""

bl_info = {
    "name": "Arena Blender Workshop MVP",
    "author": "Arena Blender Workshop",
    "version": (0, 1, 0),
    "blender": (5, 2, 0),
    "location": "3D View > Sidebar > Arena Workshop",
    "description": "Process allowlisted Arena jobs from a local file mailbox",
    "category": "System",
}

import logging
from datetime import datetime, timezone

from .mailbox import FileMailbox, default_queue_root
from .protocol import JobValidationError

_LOG = logging.getLogger("arena_blender_workshop")
_POLL_SECONDS = 0.5
_TEST_SCENE = "ArenaWorkshopTest"
_TEST_OBJECT = "ArenaWorkshopTestCube"
_bpy = None
_mailbox = None
_registered = False


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _create_test_object():
    """Create one fixed, harmless cube in the designated test scene."""
    scene = _bpy.data.scenes.get(_TEST_SCENE)
    if scene is None:
        scene = _bpy.data.scenes.new(_TEST_SCENE)

    existing = scene.objects.get(_TEST_OBJECT)
    if existing is not None:
        return {
            "object_name": existing.name,
            "scene_name": scene.name,
            "created": False,
            "message": "The test object already exists; no duplicate was created.",
        }

    vertices = [
        (-1.0, -1.0, -1.0), (1.0, -1.0, -1.0),
        (1.0, 1.0, -1.0), (-1.0, 1.0, -1.0),
        (-1.0, -1.0, 1.0), (1.0, -1.0, 1.0),
        (1.0, 1.0, 1.0), (-1.0, 1.0, 1.0),
    ]
    faces = [
        (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
        (1, 5, 6, 2), (2, 6, 7, 3), (4, 0, 3, 7),
    ]
    mesh = _bpy.data.meshes.new(_TEST_OBJECT + "Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = _bpy.data.objects.new(_TEST_OBJECT, mesh)
    scene.collection.objects.link(obj)

    return {
        "object_name": obj.name,
        "scene_name": scene.name,
        "created": True,
        "vertex_count": len(mesh.vertices),
        "polygon_count": len(mesh.polygons),
    }


def _execute(job):
    if job["operation"] == "hello_test":
        return {
            "message": job["parameters"]["message"],
            "blender_version": _bpy.app.version_string,
            "active_scene": _bpy.context.scene.name if _bpy.context.scene else None,
        }
    if job["operation"] == "create_test_object":
        return _create_test_object()
    raise JobValidationError("unsupported_operation")


def _poll_mailbox():
    global _registered
    if not _registered or _mailbox is None:
        return None

    try:
        job = _mailbox.claim_next(allowed_workspaces={"test"})
    except Exception:
        _LOG.exception("Mailbox poll failed")
        return _POLL_SECONDS

    if job is None:
        return _POLL_SECONDS

    try:
        result = _execute(job)
        response = {
            "protocol_version": job["protocol_version"],
            "job_id": job["job_id"],
            "status": "completed",
            "result": result,
            "error": None,
            "completed_at": _utc_now(),
        }
    except Exception as exc:
        _LOG.exception("Job %s failed", job.get("job_id", "unknown"))
        response = {
            "protocol_version": job.get("protocol_version", "1.0"),
            "job_id": job.get("job_id", "unknown"),
            "status": "failed",
            "result": None,
            "error": {
                "code": "blender_operation_failed",
                "message": type(exc).__name__,
            },
            "completed_at": _utc_now(),
        }

    try:
        _mailbox.write_result(response)
    except Exception:
        _LOG.exception("Could not publish result for job %s", job.get("job_id", "unknown"))
    return _POLL_SECONDS


def register():
    global _bpy, _mailbox, _registered
    import bpy

    _bpy = bpy
    _mailbox = FileMailbox(default_queue_root())
    _registered = True
    if not bpy.app.timers.is_registered(_poll_mailbox):
        bpy.app.timers.register(_poll_mailbox, first_interval=_POLL_SECONDS)
    _LOG.info("Arena Blender Workshop mailbox active at %s", _mailbox.root)


def unregister():
    global _registered, _mailbox, _bpy
    _registered = False
    if _bpy is not None and _bpy.app.timers.is_registered(_poll_mailbox):
        _bpy.app.timers.unregister(_poll_mailbox)
    _mailbox = None
    _bpy = None
