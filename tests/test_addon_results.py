import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import arena_workshop as addon


class EmptyObjects:
    def get(self, name):
        return None


class TestScene:
    def __init__(self):
        self.name = "Scene"
        self.objects = EmptyObjects()


class TestScenes:
    def __init__(self):
        self.startup_scene = TestScene()

    def get(self, name):
        return self.startup_scene if name == "Scene" else None


class TestBpy:
    def __init__(self):
        self.data = type("Data", (), {"scenes": TestScenes()})()


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
    def test_execute_uses_scene_captured_at_registration(self):
        previous_bpy, previous_scene = addon._bpy, addon._startup_scene
        bpy_instance = TestBpy()
        startup_scene = bpy_instance.data.scenes.get("Scene")
        job = {"job_id": "scene-target"}
        addon._bpy, addon._startup_scene = bpy_instance, startup_scene
        try:
            with patch.object(addon, "execute_job", return_value={"scene_name": "Scene"}) as execute:
                self.assertEqual(addon._execute(job), {"scene_name": "Scene"})
            execute.assert_called_once_with(bpy_instance, job, startup_scene=startup_scene)
        finally:
            addon._bpy, addon._startup_scene = previous_bpy, previous_scene

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
        previous = (addon._bpy, addon._mailbox, addon._startup_scene, addon._registered)
        test_bpy = TestBpy()
        addon._bpy = test_bpy
        addon._mailbox = mailbox
        addon._startup_scene = test_bpy.data.scenes.get("Scene")
        addon._registered = True
        try:
            self.assertEqual(addon._poll_mailbox(), addon._POLL_SECONDS)
        finally:
            addon._bpy, addon._mailbox, addon._startup_scene, addon._registered = previous

        self.assertEqual(mailbox.result["status"], "failed")
        self.assertEqual(mailbox.result["job_id"], "missing-object-job")
        self.assertIsNone(mailbox.result["result"])
        self.assertEqual(mailbox.result["error"]["code"], "object_not_found")
        self.assertIn("Absent", mailbox.result["error"]["message"])
        self.assertIn("completed_at", mailbox.result)


if __name__ == "__main__":
    unittest.main()
