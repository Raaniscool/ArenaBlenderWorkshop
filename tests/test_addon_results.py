import unittest
from datetime import datetime, timedelta, timezone

import arena_workshop as addon


class EmptyObjects:
    def get(self, name):
        return None


class TestScene:
    def __init__(self):
        self.name = "ArenaWorkshopTest"
        self.objects = EmptyObjects()


class TestScenes:
    def get(self, name):
        return None

    def new(self, name):
        return TestScene()


class TestBpy:
    data = type("Data", (), {"scenes": TestScenes()})()


class TestMailbox:
    root = "fake-mailbox"

    def __init__(self, job):
        self.job = job
        self.result = None

    def claim_next(self, allowed_workspaces):
        return self.job

    def write_result(self, result):
        self.result = result


class AddonResultTests(unittest.TestCase):
    def test_missing_object_is_written_as_structured_failure_result(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        job = {
            "protocol_version": "1.0",
            "job_id": "missing-object-job",
            "workspace_id": "test",
            "operation": "move_object",
            "parameters": {"object_name": "Absent", "location": [0, 0, 0]},
            "status": "queued",
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "deadline": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "result": None,
            "error": None,
        }
        mailbox = TestMailbox(job)
        previous = (addon._bpy, addon._mailbox, addon._registered)
        addon._bpy, addon._mailbox, addon._registered = TestBpy(), mailbox, True
        try:
            self.assertEqual(addon._poll_mailbox(), addon._POLL_SECONDS)
        finally:
            addon._bpy, addon._mailbox, addon._registered = previous

        self.assertEqual(mailbox.result["status"], "failed")
        self.assertEqual(mailbox.result["job_id"], "missing-object-job")
        self.assertIsNone(mailbox.result["result"])
        self.assertEqual(mailbox.result["error"]["code"], "object_not_found")
        self.assertIn("Absent", mailbox.result["error"]["message"])
        self.assertIn("completed_at", mailbox.result)


if __name__ == "__main__":
    unittest.main()
