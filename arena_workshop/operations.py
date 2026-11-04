"""Restricted Blender data API operations; no bpy.ops or arbitrary code execution."""

import hashlib
import json
import math
from math import cos, pi, sin

from .protocol import JobValidationError

TEST_SCENE = "ArenaWorkshopTest"
TEST_OBJECT = "ArenaWorkshopTestCube"
_TAG_OPERATION = "arena_workshop_operation"
_TAG_JOB_ID = "arena_workshop_job_id"
_TAG_FINGERPRINT = "arena_workshop_fingerprint"


class OperationError(RuntimeError):
    """A safe, structured operation failure suitable for a mailbox result."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _fingerprint(job):
    payload = json.dumps(
        {"operation": job["operation"], "parameters": job["parameters"]},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _retry_matches(datablock, job):
    stored_job_id = datablock.get(_TAG_JOB_ID)
    if stored_job_id != job["job_id"]:
        return False
    if (datablock.get(_TAG_OPERATION) != job["operation"]
            or datablock.get(_TAG_FINGERPRINT) != _fingerprint(job)):
        raise OperationError(
            "idempotency_conflict",
            "This job ID was already used with different operation data.",
        )
    return True


def _tag(datablock, job):
    datablock[_TAG_OPERATION] = job["operation"]
    datablock[_TAG_JOB_ID] = job["job_id"]
    datablock[_TAG_FINGERPRINT] = _fingerprint(job)


def _get_test_scene(bpy):
    scene = bpy.data.scenes.get(TEST_SCENE)
    if scene is None:
        scene = bpy.data.scenes.new(TEST_SCENE)
    return scene


def _find_object(scene, name):
    obj = scene.objects.get(name)
    if obj is None:
        raise OperationError(
            "object_not_found",
            "Object {!r} was not found in scene {}.".format(name, TEST_SCENE),
        )
    return obj


def _mesh_data(primitive_type):
    if primitive_type == "cube":
        return (
            [
                (-1.0, -1.0, -1.0), (1.0, -1.0, -1.0),
                (1.0, 1.0, -1.0), (-1.0, 1.0, -1.0),
                (-1.0, -1.0, 1.0), (1.0, -1.0, 1.0),
                (1.0, 1.0, 1.0), (-1.0, 1.0, 1.0),
            ],
            [
                (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
                (1, 5, 6, 2), (2, 6, 7, 3), (4, 0, 3, 7),
            ],
        )
    if primitive_type == "plane":
        return (
            [(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0),
             (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)],
            [(0, 1, 2, 3)],
        )
    if primitive_type in {"cylinder", "cone"}:
        segments = 32
        lower = [(cos(2 * pi * i / segments), sin(2 * pi * i / segments), -1.0)
                 for i in range(segments)]
        if primitive_type == "cylinder":
            upper = [(x, y, 1.0) for x, y, _ in lower]
            vertices = lower + upper
            sides = [
                (i, (i + 1) % segments, segments + (i + 1) % segments, segments + i)
                for i in range(segments)
            ]
            return vertices, sides + [
                tuple(reversed(range(segments))),
                tuple(range(segments, segments * 2)),
            ]
        apex_index = segments
        vertices = lower + [(0.0, 0.0, 1.0)]
        sides = [(i, (i + 1) % segments, apex_index) for i in range(segments)]
        return vertices, sides + [tuple(reversed(range(segments)))]
    if primitive_type == "uv_sphere":
        segments = 32
        rings = 16
        vertices = [(0.0, 0.0, 1.0)]
        for ring in range(1, rings):
            phi = pi * ring / rings
            radius = sin(phi)
            z = cos(phi)
            vertices.extend(
                (radius * cos(2 * pi * segment / segments),
                 radius * sin(2 * pi * segment / segments), z)
                for segment in range(segments)
            )
        bottom_index = len(vertices)
        vertices.append((0.0, 0.0, -1.0))
        faces = []
        first_ring = 1
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            faces.append((0, first_ring + segment, first_ring + next_segment))
        for ring in range(rings - 2):
            upper = 1 + ring * segments
            lower = upper + segments
            for segment in range(segments):
                next_segment = (segment + 1) % segments
                faces.append((upper + segment, upper + next_segment,
                              lower + next_segment, lower + segment))
        last_ring = 1 + (rings - 2) * segments
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            faces.append((last_ring + segment, bottom_index, last_ring + next_segment))
        return vertices, faces
    raise OperationError("unsupported_primitive", "The primitive type is not allowed.")


def _remove_created(bpy, obj, mesh):
    if obj is not None:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
    if mesh is not None:
        try:
            bpy.data.meshes.remove(mesh)
        except Exception:
            pass


def _new_mesh_object(bpy, scene, name, primitive_type):
    vertices, faces = _mesh_data(primitive_type)
    mesh = None
    obj = None
    try:
        mesh = bpy.data.meshes.new(name + "Mesh")
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        if obj.name != name:
            raise OperationError("object_name_conflict", "Blender could not preserve the requested object name.")
        scene.collection.objects.link(obj)
        return obj, mesh
    except OperationError:
        _remove_created(bpy, obj, mesh)
        raise
    except Exception as exc:
        _remove_created(bpy, obj, mesh)
        raise OperationError(
            "blender_creation_failed",
            "Blender could not create the mesh object ({}).".format(type(exc).__name__),
        ) from exc


def _test_object_result(obj, mesh, created):
    result = {
        "object_name": obj.name,
        "scene_name": TEST_SCENE,
        "created": created,
    }
    if created:
        result["vertex_count"] = len(mesh.vertices)
        result["polygon_count"] = len(mesh.polygons)
    else:
        result["message"] = "The test object already exists; no duplicate was created."
    return result


def _create_test_object(bpy):
    scene = _get_test_scene(bpy)
    existing = scene.objects.get(TEST_OBJECT)
    if existing is not None:
        mesh = existing.data
        return _test_object_result(existing, mesh, False)
    if bpy.data.objects.get(TEST_OBJECT) is not None:
        raise OperationError(
            "object_name_conflict",
            "An object named {} already exists outside the test scene.".format(TEST_OBJECT),
        )
    obj, mesh = _new_mesh_object(bpy, scene, TEST_OBJECT, "cube")
    return _test_object_result(obj, mesh, True)


def _create_primitive(bpy, job):
    params = job["parameters"]
    scene = _get_test_scene(bpy)
    existing = bpy.data.objects.get(params["object_name"])
    if existing is not None:
        existing_in_scene = scene.objects.get(params["object_name"])
        if existing_in_scene is not None and _retry_matches(existing_in_scene, job):
            return {
                "object_name": existing_in_scene.name,
                "scene_name": TEST_SCENE,
                "primitive_type": params["primitive_type"],
                "created": False,
                "message": "This job already created the object; no duplicate was made.",
            }
        raise OperationError(
            "object_name_conflict",
            "Object {!r} already exists and will not be replaced.".format(params["object_name"]),
        )

    obj, mesh = _new_mesh_object(bpy, scene, params["object_name"], params["primitive_type"])
    try:
        obj.location = tuple(float(value) for value in params.get("location", (0.0, 0.0, 0.0)))
        obj.rotation_euler = tuple(math.radians(float(value))
                                   for value in params.get("rotation", (0.0, 0.0, 0.0)))
        obj.scale = tuple(float(value) for value in params.get("scale", (1.0, 1.0, 1.0)))
        _tag(obj, job)
    except Exception as exc:
        _remove_created(bpy, obj, mesh)
        raise OperationError(
            "blender_creation_failed",
            "Blender could not initialize the new object ({}).".format(type(exc).__name__),
        ) from exc
    return {
        "object_name": obj.name,
        "scene_name": TEST_SCENE,
        "primitive_type": params["primitive_type"],
        "created": True,
        "location": list(params.get("location", (0.0, 0.0, 0.0))),
        "rotation": list(params.get("rotation", (0.0, 0.0, 0.0))),
        "scale": list(params.get("scale", (1.0, 1.0, 1.0))),
        "vertex_count": len(mesh.vertices),
        "polygon_count": len(mesh.polygons),
    }


def _transform_object(bpy, job):
    params = job["parameters"]
    obj = _find_object(_get_test_scene(bpy), params["object_name"])
    operation = job["operation"]
    if operation == "move_object":
        values = tuple(float(value) for value in params["location"])
        obj.location = values
        result_field = "location"
    elif operation == "rotate_object":
        degrees = tuple(float(value) for value in params["rotation"])
        obj.rotation_euler = tuple(math.radians(value) for value in degrees)
        values = degrees
        result_field = "rotation"
    else:
        values = tuple(float(value) for value in params["scale"])
        obj.scale = values
        result_field = "scale"
    return {
        "object_name": obj.name,
        "scene_name": TEST_SCENE,
        result_field: list(values),
        "updated": True,
    }


def _rename_object(bpy, job):
    params = job["parameters"]
    scene = _get_test_scene(bpy)
    old_name = params["object_name"]
    new_name = params["new_name"]
    obj = scene.objects.get(old_name)
    if obj is None:
        renamed = scene.objects.get(new_name)
        if renamed is not None and _retry_matches(renamed, job):
            return {"old_name": old_name, "object_name": new_name,
                    "scene_name": TEST_SCENE, "renamed": False}
        raise OperationError(
            "object_not_found",
            "Object {!r} was not found in scene {}.".format(old_name, TEST_SCENE),
        )
    if old_name == new_name:
        return {"old_name": old_name, "object_name": new_name,
                "scene_name": TEST_SCENE, "renamed": False}
    collision = bpy.data.objects.get(new_name)
    if collision is not None:
        raise OperationError(
            "object_name_conflict",
            "Object {!r} already exists and will not be replaced.".format(new_name),
        )
    try:
        obj.name = new_name
        if obj.name != new_name:
            raise OperationError("object_name_conflict", "Blender could not preserve the requested name.")
        _tag(obj, job)
    except OperationError:
        raise
    except Exception as exc:
        raise OperationError(
            "blender_rename_failed",
            "Blender could not rename the object ({}).".format(type(exc).__name__),
        ) from exc
    return {"old_name": old_name, "object_name": new_name,
            "scene_name": TEST_SCENE, "renamed": True}


def _set_principled(material, color, roughness, metallic):
    material.diffuse_color = color
    material.roughness = roughness
    material.metallic = metallic
    material.use_nodes = True
    node_tree = material.node_tree
    if node_tree is None:
        return
    nodes = node_tree.nodes
    node = nodes.get("Principled BSDF")
    if node is None:
        node = next((candidate for candidate in nodes
                     if getattr(candidate, "type", None) == "BSDF_PRINCIPLED"), None)
    if node is None:
        raise OperationError(
            "material_node_missing",
            "Blender did not provide a Principled BSDF node for the new material.",
        )
    for socket_name, value in (("Base Color", color), ("Roughness", roughness), ("Metallic", metallic)):
        socket = node.inputs.get(socket_name)
        if socket is not None:
            socket.default_value = value


def _create_material(bpy, job):
    params = job["parameters"]
    scene = _get_test_scene(bpy)
    obj = _find_object(scene, params["object_name"])
    slots = getattr(obj.data, "materials", None)
    if slots is None:
        raise OperationError(
            "material_assignment_unsupported",
            "The target object does not support mesh material assignment.",
        )

    material = bpy.data.materials.get(params["material_name"])
    created = material is None
    if material is not None:
        if not _retry_matches(material, job):
            raise OperationError(
                "material_name_conflict",
                "Material {!r} already exists and will not be replaced.".format(params["material_name"]),
            )
    else:
        material = bpy.data.materials.new(params["material_name"])
        try:
            if material.name != params["material_name"]:
                raise OperationError("material_name_conflict", "Blender could not preserve the requested material name.")
            color = tuple(float(value) for value in params["base_color"])
            _set_principled(material, color, float(params["roughness"]), float(params["metallic"]))
            _tag(material, job)
        except OperationError:
            try:
                bpy.data.materials.remove(material)
            except Exception:
                pass
            raise
        except Exception as exc:
            try:
                bpy.data.materials.remove(material)
            except Exception:
                pass
            raise OperationError(
                "material_creation_failed",
                "Blender could not create the material ({}).".format(type(exc).__name__),
            ) from exc

    if material not in slots:
        slots.append(material)
    return {
        "material_name": material.name,
        "object_name": obj.name,
        "scene_name": TEST_SCENE,
        "base_color": list(params["base_color"]),
        "roughness": params["roughness"],
        "metallic": params["metallic"],
        "created": created,
        "assigned": True,
    }


def execute_job(bpy, job):
    """Execute one already-validated job using Blender's data API only."""
    operation = job["operation"]
    params = job["parameters"]
    if operation == "hello_test":
        active_scene = getattr(getattr(bpy, "context", None), "scene", None)
        return {
            "message": params["message"],
            "blender_version": bpy.app.version_string,
            "active_scene": active_scene.name if active_scene else None,
        }
    if operation == "create_test_object":
        return _create_test_object(bpy)
    if operation == "create_primitive":
        return _create_primitive(bpy, job)
    if operation in {"move_object", "rotate_object", "scale_object"}:
        return _transform_object(bpy, job)
    if operation == "rename_object":
        return _rename_object(bpy, job)
    if operation == "create_material":
        return _create_material(bpy, job)
    raise JobValidationError("unsupported_operation")
