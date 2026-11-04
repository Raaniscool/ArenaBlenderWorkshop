"""Strict, dependency-free job protocol shared by the worker and Blender add-on."""

import json
import re
from datetime import datetime, timedelta, timezone

PROTOCOL_VERSION = "1.0"
MAX_JOB_BYTES = 16 * 1024
MAX_JOB_AGE = timedelta(hours=1)
MAX_JOB_LIFETIME = timedelta(minutes=30)
MAX_CLOCK_SKEW = timedelta(minutes=5)
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REQUIRED_FIELDS = {
    "protocol_version",
    "job_id",
    "workspace_id",
    "operation",
    "parameters",
    "status",
    "created_at",
    "deadline",
    "result",
    "error",
}


class JobValidationError(ValueError):
    """A job violates the protocol or local allowlist."""


def _reject_constant(value):
    raise JobValidationError("non-finite_json_number")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise JobValidationError("duplicate_json_key")
        result[key] = value
    return result


def _parse_utc(value, field):
    if not isinstance(value, str) or len(value) > 40:
        raise JobValidationError("invalid_" + field)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except (TypeError, ValueError):
        raise JobValidationError("invalid_" + field)
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise JobValidationError("timestamp_must_be_utc")
    return parsed.astimezone(timezone.utc)


def decode_job(raw, allowed_workspaces, now=None):
    """Decode and validate an incoming job. Only queued MVP operations are accepted."""
    if isinstance(raw, bytes):
        if len(raw) > MAX_JOB_BYTES:
            raise JobValidationError("job_too_large")
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise JobValidationError("invalid_utf8")
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_JOB_BYTES:
        raise JobValidationError("job_too_large_or_not_text")
    try:
        job = json.loads(raw, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except JobValidationError:
        raise
    except (json.JSONDecodeError, TypeError):
        raise JobValidationError("invalid_json")
    return validate_job(job, allowed_workspaces=allowed_workspaces, now=now)


def validate_job(job, allowed_workspaces, now=None):
    if not isinstance(job, dict) or set(job) != _REQUIRED_FIELDS:
        raise JobValidationError("invalid_job_fields")
    if job["protocol_version"] != PROTOCOL_VERSION:
        raise JobValidationError("unsupported_protocol_version")

    job_id = job["job_id"]
    if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
        raise JobValidationError("invalid_job_id")

    workspace_id = job["workspace_id"]
    if not isinstance(workspace_id, str) or not _WORKSPACE_ID.fullmatch(workspace_id):
        raise JobValidationError("invalid_workspace_id")
    if workspace_id not in set(allowed_workspaces):
        raise JobValidationError("workspace_not_allowed")

    if job["status"] != "queued" or job["result"] is not None or job["error"] is not None:
        raise JobValidationError("invalid_initial_state")

    created_at = _parse_utc(job["created_at"], "created_at")
    deadline = _parse_utc(job["deadline"], "deadline")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    if created_at > now + MAX_CLOCK_SKEW:
        raise JobValidationError("created_at_in_future")
    if created_at < now - MAX_JOB_AGE:
        raise JobValidationError("job_too_old")
    if deadline <= now:
        raise JobValidationError("job_expired")
    if deadline <= created_at or deadline - created_at > MAX_JOB_LIFETIME:
        raise JobValidationError("invalid_deadline")

    operation = job["operation"]
    params = job["parameters"]
    if not isinstance(params, dict):
        raise JobValidationError("parameters_must_be_object")

    if operation == "hello_test":
        if set(params) != {"message"}:
            raise JobValidationError("invalid_hello_test_parameters")
        message = params["message"]
        if not isinstance(message, str) or not message.strip() or len(message) > 256:
            raise JobValidationError("invalid_hello_test_message")
    elif operation == "create_test_object":
        if params:
            raise JobValidationError("create_test_object_takes_no_parameters")
    else:
        raise JobValidationError("unsupported_operation")

    return dict(job)
