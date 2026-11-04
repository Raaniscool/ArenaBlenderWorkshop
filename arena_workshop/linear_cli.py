"""Local setup and runner commands for the outbound-only Linear worker."""

import argparse
import getpass
import logging
import os
import sys
import time

from .linear_api import LinearApi, LinearApiError, LinearCredentialStore
from .linear_worker import LinearWorker, WindowsMutex, WorkerError


def configure_credentials(client_id, client_secret, store=None, api_factory=LinearApi):
    """Validate OAuth credentials, discard the test token, and DPAPI-store secrets."""
    if not isinstance(client_id, str) or not client_id.strip():
        raise LinearApiError("invalid_credentials", "A Linear OAuth client ID is required.")
    if not isinstance(client_secret, str) or not client_secret:
        raise LinearApiError("invalid_credentials", "A Linear OAuth client secret is required.")
    api = api_factory(client_id.strip(), client_secret)
    api.authenticate_and_forget()
    (store or LinearCredentialStore()).save(client_id.strip(), client_secret)
    return True


def configure_main(argv=None, input_fn=input, secret_prompt=getpass.getpass, store=None, api_factory=LinearApi):
    parser = argparse.ArgumentParser(
        prog="python -m arena_workshop configure-linear",
        description="Validate and DPAPI-protect the Linear worker OAuth client credentials on this Windows user profile.",
    )
    parser.parse_args(argv)
    if os.name != "nt":
        print("Linear worker credentials require Windows DPAPI; no plaintext fallback is available.", file=sys.stderr)
        return 2
    client_secret = None
    try:
        client_id = input_fn("Linear OAuth client ID: ").strip()
        client_secret = secret_prompt("Linear OAuth client secret (input hidden): ")
        configure_credentials(client_id, client_secret, store=store, api_factory=api_factory)
    except (LinearApiError, OSError) as exc:
        code = getattr(exc, "code", "credential_setup_failed")
        print("Linear credential setup failed ({}): {}".format(code, getattr(exc, "message", "local storage failed")), file=sys.stderr)
        return 1
    finally:
        client_secret = None
    print("Linear credentials validated and stored using Windows DPAPI for this Windows user.")
    print("The access token was discarded; the worker requests a fresh token when it starts.")
    return 0


def worker_main(argv=None, store=None, api_factory=LinearApi, worker_factory=LinearWorker, mutex_factory=WindowsMutex):
    parser = argparse.ArgumentParser(
        prog="python -m arena_workshop linear-worker",
        description="Run the outbound-only, single-instance Linear-to-Blender mailbox worker.",
    )
    parser.add_argument("--once", action="store_true", help="perform one reconciliation cycle and exit")
    parser.add_argument("--poll-interval", type=float, default=5.0, metavar="SECONDS",
                        help="poll delay (1-60 seconds, default 5)")
    args = parser.parse_args(argv)
    if not 1.0 <= args.poll_interval <= 60.0:
        parser.error("--poll-interval must be between 1 and 60 seconds")
    if os.name != "nt":
        print("The Linear worker requires Windows and a Windows named mutex.", file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        with mutex_factory():
            credential_store = store or LinearCredentialStore()
            credentials = credential_store.load()
            if credentials is None:
                raise LinearApiError("authorization_required", "Run configure-linear on this Windows PC first.")
            api = api_factory(credentials["client_id"], credentials["client_secret"])
            worker = worker_factory(api)
            if args.once:
                worker.initialize()
                worker.run_once()
            else:
                worker.run_forever(poll_interval=args.poll_interval, sleep=time.sleep)
    except (LinearApiError, WorkerError, OSError) as exc:
        code = getattr(exc, "code", "worker_start_failed")
        message = getattr(exc, "message", "The Linear worker could not continue.")
        print("Linear worker stopped ({}): {}".format(code, message), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0
