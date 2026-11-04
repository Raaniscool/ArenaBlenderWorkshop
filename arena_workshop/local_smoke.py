"""Create one fixed, local-only smoke-test job for the Blender add-on."""

import argparse
import json
import math
import time
import uuid
from datetime import datetime, timedelta, timezone

from .mailbox import FileMailbox, default_queue_root

_DEFAULT_TIMEOUT_SECONDS = 60.0
_POLL_INTERVAL_SECONDS = 0.25


def create_smoke_job(operation, now=None):
    """Build one of the two protocol's fixed test jobs; accept no custom payload."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    if operation == "hello_test":
        parameters = {"message": "Arena Blender Workshop local add-on smoke test"}
    elif operation == "create_test_object":
        parameters = {}
    else:
        raise ValueError("operation must be hello_test or create_test_object")

    return {
        "protocol_version": "1.0",
        "job_id": "local-" + uuid.uuid4().hex,
        "workspace_id": "test",
        "operation": operation,
        "parameters": parameters,
        "status": "queued",
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "deadline": (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        "result": None,
        "error": None,
    }


def _positive_seconds(value):
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("timeout must be a number of seconds")
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("timeout must be a finite number greater than zero")
    return seconds


def wait_for_result(mailbox, job_id, timeout, poll_interval=_POLL_INTERVAL_SECONDS):
    """Poll one already-enqueued job until a result arrives or the timeout expires."""
    deadline = time.monotonic() + timeout
    while True:
        result = mailbox.read_result(job_id)
        if result is not None:
            return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(poll_interval, remaining))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Queue a fixed local Blender add-on smoke test")
    parser.add_argument("operation", choices=("hello_test", "create_test_object"))
    parser.add_argument(
        "--wait",
        action="store_true",
        help="wait for Blender to write the result and print it as formatted JSON",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_seconds,
        default=_DEFAULT_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help="maximum time to wait with --wait (default: 60 seconds)",
    )
    args = parser.parse_args(argv)

    job = create_smoke_job(args.operation)
    mailbox = FileMailbox(default_queue_root())
    # Enqueue exactly once. Waiting only polls the result for this job ID.
    mailbox.enqueue(job)
    result_path = mailbox.results / (job["job_id"] + ".json")

    if not args.wait:
        print(json.dumps({"job_id": job["job_id"], "result_path": str(result_path)}))
        return 0

    result = wait_for_result(mailbox, job["job_id"], args.timeout)
    if result is None:
        print(json.dumps({
            "job_id": job["job_id"],
            "status": "timeout",
            "timeout_seconds": args.timeout,
            "result_path": str(result_path),
            "message": "No Blender result arrived before the timeout; the job was not resubmitted.",
        }, indent=2))
        return 2

    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not isinstance(result, dict) or result.get("status") != "completed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
