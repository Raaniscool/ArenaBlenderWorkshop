import math
import unittest
from datetime import datetime, timedelta, timezone

from arena_workshop.operations import (
    TEST_OBJECT,
    TEST_SCENE,
    OperationError,
    execute_job,
)
from arena_workshop.protocol import JobValidationError, validate_job


class FakeMesh:
    def __init__(self, name):
        self.name = name
        self.vertices = []
        self.polygons = []
        self.materials = []

    def from_pydata(self, vertices, edges, faces):
        self.vertices = list(vertices)
        self.polygons = list(faces)

    def update(self):
        pass


class FakeNodeSocket:
    def __init__(self):
        self.default_value = None


class FakeNodeInputs(dict):
    def __init__(self):
        super().__init__((key, FakeNodeSocket()) for key in ("Base Color", "Roughness", "Metallic"))


class FakeNode:
    def __init__(self):
        self.name = "Principled BSDF"
        self.type = "BSDF_PRINCIPLED"
        self.inputs = FakeNodeInputs()


class FakeNodes(list):
    def __init__(self):
        super().__init__([FakeNode()])

    def get(self, name):
        return next((node for node in self if node.name == name), None)


class FakeNodeTree:
    def __init__(self):
        self.nodes = FakeNodes()


class FakeDataBlock:
    def __init__(self):
        self._custom_properties = {}

    def get(self, key, default=None):
        return self._custom_properties.get(key, default)

    def __getitem__(self, key):
        return self._custom_properties[key]

    def __setitem__(self, key, value):
        self._custom_properties[key] = value


class FakeMaterial(FakeDataBlock):
    def __init__(self, name):
        super().__init__()
        self.name = name
        self.diffuse_color = None
        self.roughness = None
        self.metallic = None
        self.use_nodes = False
        self.node_tree = FakeNodeTree()


class FakeMaterials(dict):
    def new(self, name):
        if name in self:
            name = name + ".001"
        material = FakeMaterial(name)
        self[name] = material
        return material

    def remove(self, material):
        self.pop(material.name, None)


class FakeObject(FakeDataBlock):
    def __init__(self, name, mesh, data_objects):
        super().__init__()
        self._name = name
        self.data = mesh
        self._data_objects = data_objects
        self._collections = []
        self.location = (0.0, 0.0, 0.0)
        self.rotation_euler = (0.0, 0.0, 0.0)
        self.scale = (1.0, 1.0, 1.0)

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, new_name):
        old_name = self._name
        self._data_objects.pop(old_name, None)
        self._name = new_name
        self._data_objects[new_name] = self
        for collection in self._collections:
            collection.rename(old_name, new_name, self)


class FakeSceneObjects(dict):
    def link(self, obj):
        self[obj.name] = obj
        obj._collections.append(self)

    def rename(self, old_name, new_name, obj):
        self.pop(old_name, None)
        self[new_name] = obj


class FakeSceneCollection:
    def __init__(self, scene_objects):
        self.objects = scene_objects


class FakeScene:
    def __init__(self, name):
        self.name = name
        self.objects = FakeSceneObjects()
        self.collection = FakeSceneCollection(self.objects)


class FakeScenes(dict):
    def new(self, name):
        if name in self:
            raise ValueError("scene exists")
        scene = FakeScene(name)
        self[name] = scene
        return scene


class FakeObjects(dict):
    def __init__(self):
        super().__init__()
        self.scenes = []

    def new(self, name, mesh):
        unique_name = name
        suffix = 1
        while unique_name in self:
            unique_name = "{}.{}".format(name, suffix)
            suffix += 1
        obj = FakeObject(unique_name, mesh, self)
        self[unique_name] = obj
        return obj

    def remove(self, obj, do_unlink=True):
        self.pop(obj.name, None)
        if do_unlink:
            for collection in list(obj._collections):
                collection.pop(obj.name, None)


class FakeMeshes(dict):
    def new(self, name):
        unique_name = name
        suffix = 1
        while unique_name in self:
            unique_name = "{}.{}".format(name, suffix)
            suffix += 1
        mesh = FakeMesh(unique_name)
        self[unique_name] = mesh
        return mesh

    def remove(self, mesh):
        self.pop(mesh.name, None)


class FakeBpy:
    def __init__(self):
        scenes = FakeScenes()
        active_scene = scenes.new("UserScene")
        objects = FakeObjects()
        self.data = type("FakeData", (), {})()
        self.data.scenes = scenes
        self.data.objects = objects
        self.data.meshes = FakeMeshes()
        self.data.materials = FakeMaterials()
        self.context = type("FakeContext", (), {"scene": active_scene})()
        self.app = type("FakeApp", (), {"version_string": "5.2.0 test fake"})()


def make_job(operation, parameters, job_id="job-001"):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "protocol_version": "1.0",
        "job_id": job_id,
        "workspace_id": "test",
        "operation": operation,
        "parameters": parameters,
        "status": "queued",
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "deadline": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "result": None,
        "error": None,
    }


def validated(job):
    return validate_job(job, {"test"})


class ModelingProtocolTests(unittest.TestCase):
    def test_accepts_each_new_operation(self):
        cases = [
            ("create_primitive", {"primitive_type": "cube", "object_name": "Block"}),
            ("move_object", {"object_name": "Block", "location": [1, 2, 3]}),
            ("rotate_object", {"object_name": "Block", "rotation": [10, 20, 30]}),
            ("scale_object", {"object_name": "Block", "scale": [1, 2, 3]}),
            ("rename_object", {"object_name": "Block", "new_name": "NewBlock"}),
            ("create_material", {
                "material_name": "Mat", "object_name": "Block",
                "base_color": [0.2, 0.4, 0.6, 1.0], "roughness": 0.5, "metallic": 0.1,
            }),
        ]
        for operation, params in cases:
            with self.subTest(operation=operation):
                self.assertEqual(validated(make_job(operation, params))["operation"], operation)

    def test_create_primitive_rejects_invalid_type_name_vector_and_extra_fields(self):
        base = {"primitive_type": "cube", "object_name": "Block"}
        invalid = [
            dict(base, primitive_type="monkey"),
            dict(base, object_name="  "),
            dict(base, location=[0, 1]),
            dict(base, shell="echo unsafe"),
        ]
        for params in invalid:
            with self.subTest(params=params), self.assertRaises(JobValidationError):
                validated(make_job("create_primitive", params))

    def test_transform_protocols_reject_bad_vectors(self):
        cases = [
            ("move_object", {"object_name": "Block", "location": [0, 0, float("inf")]}),
            ("rotate_object", {"object_name": "Block", "rotation": [0, True, 0]}),
            ("scale_object", {"object_name": "Block", "scale": [1, 0, 1]}),
        ]
        for operation, params in cases:
            with self.subTest(operation=operation), self.assertRaises(JobValidationError):
                validated(make_job(operation, params))

    def test_rename_protocol_rejects_invalid_names_and_extra_keys(self):
        for params in (
            {"object_name": "Block", "new_name": ""},
            {"object_name": "Block", "new_name": "New", "extra": 1},
        ):
            with self.subTest(params=params), self.assertRaises(JobValidationError):
                validated(make_job("rename_object", params))

    def test_material_protocol_rejects_out_of_range_values(self):
        base = {
            "material_name": "Mat", "object_name": "Block",
            "base_color": [0.2, 0.4, 0.6, 1.0], "roughness": 0.5, "metallic": 0.1,
        }
        invalid = [
            dict(base, base_color=[0.2, 0.4, 1.1, 1.0]),
            dict(base, roughness=1.1),
            dict(base, metallic=-0.1),
        ]
        for params in invalid:
            with self.subTest(params=params), self.assertRaises(JobValidationError):
                validated(make_job("create_material", params))

    def test_unknown_or_non_string_operation_is_rejected(self):
        for operation in ("run_python", ["create_primitive"]):
            with self.subTest(operation=operation), self.assertRaises(JobValidationError):
                validated(make_job(operation, {}))


class ModelingOperationTests(unittest.TestCase):
    def setUp(self):
        self.bpy = FakeBpy()
        self.active_scene = self.bpy.context.scene

    def run_job(self, operation, parameters, job_id="job-001"):
        job = validated(make_job(operation, parameters, job_id=job_id))
        return execute_job(self.bpy, job)

    def test_create_each_primitive_with_expected_mesh(self):
        expected = {
            "cube": (8, 6),
            "uv_sphere": (482, 512),
            "cylinder": (64, 34),
            "plane": (4, 1),
            "cone": (33, 33),
        }
        for primitive_type, counts in expected.items():
            with self.subTest(primitive_type=primitive_type):
                result = self.run_job(
                    "create_primitive",
                    {"primitive_type": primitive_type, "object_name": primitive_type.title()},
                    job_id="primitive-" + primitive_type,
                )
                obj = self.bpy.data.objects[result["object_name"]]
                self.assertEqual((len(obj.data.vertices), len(obj.data.polygons)), counts)
                self.assertEqual(result["scene_name"], TEST_SCENE)
                self.assertTrue(result["created"])
                self.assertIs(self.bpy.context.scene, self.active_scene)

    def test_primitive_transforms_and_retry_are_idempotent(self):
        params = {
            "primitive_type": "cube", "object_name": "MovedBlock",
            "location": [4, -2, 1], "rotation": [0, 90, 0], "scale": [2, 3, 4],
        }
        first = self.run_job("create_primitive", params, job_id="primitive-retry")
        obj = self.bpy.data.objects["MovedBlock"]
        before_count = len(self.bpy.data.objects)
        second = self.run_job("create_primitive", params, job_id="primitive-retry")
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(len(self.bpy.data.objects), before_count)
        self.assertEqual(obj.location, (4.0, -2.0, 1.0))
        self.assertAlmostEqual(obj.rotation_euler[1], math.pi / 2)
        self.assertEqual(obj.scale, (2.0, 3.0, 4.0))
        self.assertIs(self.bpy.context.scene, self.active_scene)

    def test_existing_object_is_never_replaced(self):
        original = self.bpy.data.objects.new("Protected", FakeMesh("ProtectedMesh"))
        with self.assertRaisesRegex(OperationError, "already exists") as caught:
            self.run_job("create_primitive", {"primitive_type": "cube", "object_name": "Protected"})
        self.assertEqual(caught.exception.code, "object_name_conflict")
        self.assertIs(self.bpy.data.objects["Protected"], original)

    def test_create_test_object_remains_idempotent(self):
        first = self.run_job("create_test_object", {})
        second = self.run_job("create_test_object", {}, job_id="different-job")
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(len(self.bpy.data.objects), 1)

    def test_transforms_change_only_named_test_scene_object(self):
        created = self.run_job("create_test_object", {})
        target = self.bpy.data.objects[created["object_name"]]
        self.run_job("move_object", {"object_name": TEST_OBJECT, "location": [3, 2, 1]}, "move-1")
        self.run_job("rotate_object", {"object_name": TEST_OBJECT, "rotation": [0, 0, 180]}, "rotate-1")
        self.run_job("scale_object", {"object_name": TEST_OBJECT, "scale": [2, 2, 2]}, "scale-1")
        self.assertEqual(target.location, (3.0, 2.0, 1.0))
        self.assertAlmostEqual(target.rotation_euler[2], math.pi)
        self.assertEqual(target.scale, (2.0, 2.0, 2.0))
        self.assertIs(self.bpy.context.scene, self.active_scene)

    def test_rename_updates_same_object_and_retry_does_not_duplicate(self):
        self.run_job("create_test_object", {})
        original = self.bpy.data.objects[TEST_OBJECT]
        params = {"object_name": TEST_OBJECT, "new_name": "RenamedCube"}
        first = self.run_job("rename_object", params, "rename-1")
        second = self.run_job("rename_object", params, "rename-1")
        self.assertTrue(first["renamed"])
        self.assertFalse(second["renamed"])
        self.assertIs(self.bpy.data.objects["RenamedCube"], original)
        self.assertNotIn(TEST_OBJECT, self.bpy.data.objects)

    def test_rename_conflict_does_not_replace_target(self):
        self.run_job("create_test_object", {})
        original = self.bpy.data.objects[TEST_OBJECT]
        collision = self.bpy.data.objects.new("TakenName", FakeMesh("TakenMesh"))
        with self.assertRaises(OperationError) as caught:
            self.run_job("rename_object", {"object_name": TEST_OBJECT, "new_name": "TakenName"})
        self.assertEqual(caught.exception.code, "object_name_conflict")
        self.assertIs(self.bpy.data.objects[TEST_OBJECT], original)
        self.assertIs(self.bpy.data.objects["TakenName"], collision)

    def test_material_creation_assignment_and_retry(self):
        self.run_job("create_test_object", {})
        params = {
            "material_name": "WarmMetal", "object_name": TEST_OBJECT,
            "base_color": [0.8, 0.3, 0.1, 1.0], "roughness": 0.35, "metallic": 0.7,
        }
        first = self.run_job("create_material", params, "material-1")
        obj = self.bpy.data.objects[TEST_OBJECT]
        material = self.bpy.data.materials["WarmMetal"]
        second = self.run_job("create_material", params, "material-1")
        self.assertTrue(first["created"])
        self.assertTrue(first["assigned"])
        self.assertFalse(second["created"])
        self.assertEqual(obj.data.materials, [material])
        self.assertEqual(material.diffuse_color, tuple(params["base_color"]))
        self.assertEqual(material.node_tree.nodes[0].inputs["Roughness"].default_value, 0.35)
        self.assertEqual(material.node_tree.nodes[0].inputs["Metallic"].default_value, 0.7)

    def test_material_name_conflict_does_not_overwrite_existing_material(self):
        self.run_job("create_test_object", {})
        original = FakeMaterial("ProtectedMaterial")
        original.diffuse_color = (0.1, 0.2, 0.3, 1.0)
        self.bpy.data.materials[original.name] = original
        params = {
            "material_name": "ProtectedMaterial", "object_name": TEST_OBJECT,
            "base_color": [0.8, 0.8, 0.8, 1.0], "roughness": 0.2, "metallic": 0.5,
        }
        with self.assertRaises(OperationError) as caught:
            self.run_job("create_material", params)
        self.assertEqual(caught.exception.code, "material_name_conflict")
        self.assertIs(self.bpy.data.materials["ProtectedMaterial"], original)
        self.assertEqual(original.diffuse_color, (0.1, 0.2, 0.3, 1.0))

    def test_missing_objects_return_clear_errors_for_targeted_operations(self):
        cases = [
            ("move_object", {"object_name": "Absent", "location": [0, 0, 0]}),
            ("rotate_object", {"object_name": "Absent", "rotation": [0, 0, 0]}),
            ("scale_object", {"object_name": "Absent", "scale": [1, 1, 1]}),
            ("rename_object", {"object_name": "Absent", "new_name": "NewName"}),
            ("create_material", {
                "material_name": "Mat", "object_name": "Absent",
                "base_color": [0, 0, 0, 1], "roughness": 0.5, "metallic": 0,
            }),
        ]
        for operation, params in cases:
            with self.subTest(operation=operation), self.assertRaises(OperationError) as caught:
                self.run_job(operation, params)
            self.assertEqual(caught.exception.code, "object_not_found")
            self.assertIn("Absent", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
