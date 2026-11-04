"""Arena Blender Workshop add-on (Blender 5.2 target).

The add-on is deliberately local-only: it watches a filesystem mailbox and
executes a small allowlist from Blender's main-thread timer. It opens no port.
"""

bl_info = {
    "name": "Arena Blender Workshop MVP",
    "author": "Arena Blender Workshop",
    "version": (0, 3, 0),
    "blender": (5, 2, 0),
    "location": "3D View > Sidebar > Arena Workshop",
    "description": "Process allowlisted Arena jobs from a local file mailbox",
    "category": "System",
}

import logging
from datetime import datetime, timezone

from .mailbox import FileMailbox, default_queue_root
from .operations import OperationError, execute_job

_LOG = logging.getLogger("arena_blender_workshop")
_POLL_SECONDS = 0.5
_bpy = None
_mailbox = None
_registered = False


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _execute(job):
    return execute_job(_bpy, job)


def _failure_response(job, code, message):
    return {
        "protocol_version": job.get("protocol_version", "1.0"),
        "job_id": job.get("job_id", "unknown"),
        "status": "failed",
        "result": None,
        "error": {"code": code, "message": message},
        "completed_at": _utc_now(),
    }


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
        response = {
            "protocol_version": job["protocol_version"],
            "job_id": job["job_id"],
            "status": "completed",
            "result": _execute(job),
            "error": None,
            "completed_at": _utc_now(),
        }
    except OperationError as exc:
        _LOG.warning("Job %s failed: %s", job.get("job_id", "unknown"), exc.code)
        response = _failure_response(job, exc.code, exc.message)
    except Exception as exc:
        _LOG.exception("Job %s failed", job.get("job_id", "unknown"))
        response = _failure_response(
            job,
            "blender_operation_failed",
            "Blender operation failed ({}).".format(type(exc).__name__),
        )

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
