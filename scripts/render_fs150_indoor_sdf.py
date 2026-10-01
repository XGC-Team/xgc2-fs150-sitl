#!/usr/bin/env python3
import argparse
import json
import math
import re
import os
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

from pathlib import Path

IRIS_MOTOR_CONSTANT = 5.84e-06
IRIS_REFERENCE_HOVER_THRUST = 0.706963405
FS150_TARGET_HOVER_THRUST = 0.30
FS150_TOTAL_MASS = 0.310
FS150_BASE_MASS = 0.275
IRIS_BASE_MASS = 1.5
IRIS_BASE_INERTIA = (0.029125, 0.029125, 0.055225)
FS150_EQUIVALENT_INERTIA_SCALE = 0.35
# The shared FS150 landing pads end at z=-0.033 m in base_link. The old
# 0.11 m Iris box supported the model 22 mm above those pads. Match its
# vertical support extent without moving the visual, body/IMU frame or COM.
# XY and rotor collision geometry remain the existing coarse Iris envelope;
# this contact-height correction is not a full FS150 airframe calibration.
FS150_BODY_COLLISION_SIZE = (0.47, 0.47, 0.066)
FS150_BODY_VISUAL_POSE = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
FS150_BODY_VISUAL_SCALE = (1.0, 1.0, 1.0)
FS150_ROTOR_POSES = {
    "rotor_0": (0.13, -0.22, 0.023, 0.0, 0.0, 0.0),
    "rotor_1": (-0.13, 0.2, 0.023, 0.0, 0.0, 0.0),
    "rotor_2": (0.13, 0.22, 0.023, 0.0, 0.0, 0.0),
    "rotor_3": (-0.13, -0.2, 0.023, 0.0, 0.0, 0.0),
}
FS150_ROTOR_Z = 0.023
FS150_ROTOR_MASS = 0.005
IRIS_ROTOR_INERTIA = (9.75e-07, 0.000273104, 0.000274004)
FS150_ROTOR_INERTIA = tuple(
    value * FS150_EQUIVALENT_INERTIA_SCALE for value in IRIS_ROTOR_INERTIA
)
FS150_PROP_RADIUS = 0.128
FS150_PROP_COLLISION_RADIUS = FS150_PROP_RADIUS
FS150_PROP_LENGTH = 0.005
FS150_PROP_VISUAL_SCALE = (1.0, 1.0, 1.0)
FS150_PROP_VISUAL_POSE = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
# Hover-test correction from the total-mass scaled FS150 model. Further
# correction should use
# motorConstant_next = motorConstant_current * (hover_thrust / 0.30)^2.
FS150_MOTOR_CONSTANT = 5.33969944334e-06
FS150_MOMENT_CONSTANT = 0.06
FS150_MOTOR_TIME_CONSTANT_UP = 0.006
FS150_MOTOR_TIME_CONSTANT_DOWN = 0.012
FS150_ROTOR_DRAG_COEFFICIENT = 2e-05
FS150_ROLLING_MOMENT_COEFFICIENT = 1e-07


def description_package():
    try:
        return Path(subprocess.check_output(['rospack', 'find', 'fs150_description'], text=True).strip())
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError('fs150_description is required for the FS150 visual model') from exc


def apply_visual_assets(root, description_root=None, resolve_resources=True):
    package = Path(description_root) if description_root else description_package()
    source = ET.parse(package/'urdf/fs150_visual.urdf').getroot()
    model = root.find('model')
    body = model.find("link[@name='base_link']")
    origins = {'base_link': '0 0 0 0 0 0'}
    visual_links={link.get('name') for link in source.findall('link') if link.find('visual') is not None}
    for joint in source.findall('joint'):
        if joint.find('child').get('link') not in visual_links:
            continue
        if joint.find('parent').get('link') != 'base_link':
            raise ValueError('FS150 visual joints must be relative to base_link')
        origin = joint.find('origin')
        origins[joint.find('child').get('link')] = origin.get('xyz')+' '+origin.get('rpy','0 0 0')
    for link in model.findall('link'):
        if link.get('name') == 'base_link' or link.get('name', '').startswith('rotor_'):
            for visual in list(link.findall('visual')):
                link.remove(visual)
    count = 0
    for link in source.findall('link'):
        for visual in link.findall('visual'):
            target = ET.SubElement(body, 'visual', name='fs150_photo_'+link.get('name'))
            ET.SubElement(target, 'pose').text = origins[link.get('name')]
            mesh = visual.find('geometry/mesh')
            geometry = ET.SubElement(target, 'geometry')
            output_mesh = ET.SubElement(geometry, 'mesh')
            uri = mesh.get('filename')
            prefix = 'package://fs150_description/models/'
            if not uri.startswith(prefix):
                raise ValueError('FS150 visual mesh must belong to fs150_description/models')
            relative = uri[len('package://fs150_description/'):]
            asset = package/relative
            if not asset.is_file():
                raise FileNotFoundError(str(asset))
            ET.SubElement(output_mesh, 'uri').text = asset.as_uri() if resolve_resources else 'model://'+relative[len('models/'):]
            ET.SubElement(output_mesh, 'scale').text = mesh.get('scale','1 1 1')
            count += 1
    if count != 5:
        raise ValueError('FS150 appearance must contain a body and four rotors')
    return [('shared FS150 visual meshes (static rotor appearance)',count)]


def apply_camera(root, enabled=False, robot_namespace='uav1', model_name='uav1',
                 fps=None, horizontal_fov=None, description_root=None):
    """Optional ideal ROS colour camera; disabled output has no camera sensor/plugin."""
    body=root.find("model/link[@name='base_link']")
    for sensor in list(body.findall("sensor[@name='fs150_front_camera']")):
        body.remove(sensor)
    if not enabled:
        return [('front camera disabled (sensor omitted)',0)]
    namespace=robot_namespace.strip('/')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(/[A-Za-z][A-Za-z0-9_]*)*',namespace):
        raise ValueError('Camera namespace must identify one robot')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',model_name):
        raise ValueError('Invalid camera model name')
    package=Path(description_root) if description_root else description_package()
    urdf=ET.parse(package/'urdf/fs150_visual.urdf').getroot()
    origin=urdf.find("joint[@name='camera_link_joint']/origin")
    if origin is None:
        raise ValueError('fs150_description camera_link_joint is required')
    profile_path=Path(__file__).resolve().parents[1]/'config/camera.json'
    if not profile_path.is_file():
        profile_path=Path(_rospack_find('gazebo_sim_fs150_sitl'))/'config/camera.json'
    profile=json.loads(profile_path.read_text())
    rate=profile['fps'] if fps is None else float(fps)
    fov=profile['horizontal_fov_rad'] if horizontal_fov is None else float(horizontal_fov)
    if not math.isfinite(rate) or not 0<rate<=30:
        raise ValueError('FS150 camera rate must be in (0,30] Hz')
    if not math.isfinite(fov) or not 0<fov<math.pi:
        raise ValueError('Camera HFOV must be between zero and pi radians')
    width,height=profile['width'],profile['height']
    focal=width/(2*math.tan(fov/2))
    sensor=ET.SubElement(body,'sensor',name='fs150_front_camera',type='camera')
    ET.SubElement(sensor,'pose').text=origin.get('xyz')+' '+origin.get('rpy','0 0 0')
    ET.SubElement(sensor,'always_on').text='false'
    ET.SubElement(sensor,'visualize').text='false'
    ET.SubElement(sensor,'update_rate').text=str(rate)
    camera=ET.SubElement(sensor,'camera',name='fs150_front')
    ET.SubElement(camera,'horizontal_fov').text=str(fov)
    image=ET.SubElement(camera,'image')
    for key,value in [('width',width),('height',height),('format','R8G8B8')]:
        ET.SubElement(image,key).text=str(value)
    clip=ET.SubElement(camera,'clip')
    ET.SubElement(clip,'near').text=str(profile['near_m'])
    ET.SubElement(clip,'far').text=str(profile['far_m'])
    plugin=ET.SubElement(sensor,'plugin',name='fs150_front_camera_ros',filename='libgazebo_ros_camera.so')
    values={'robotNamespace':'/'+namespace,'cameraName':'camera2',
            'imageTopicName':'image','cameraInfoTopicName':'camera_info',
            'frameName':'xgc/robots/'+model_name+'/camera_optical_frame',
            'updateRate':0,'Cx':width/2,'Cy':height/2,'CxPrime':width/2,'focalLength':focal,
            'distortionK1':0,'distortionK2':0,'distortionK3':0,'distortionT1':0,'distortionT2':0,
            'hackBaseline':0}
    for key,value in values.items():ET.SubElement(plugin,key).text=str(value)
    return [('front camera enabled (ideal pinhole, ROS camera2/image)',1)]


# Rendering the shared lidar takes one xacro process per robot, and xacro spends
# about 0.3 s of it importing roslaunch to resolve $(arg ...). A fleet renders
# the same scan for every robot, only the namespace differs, so the xacro output
# is kept per scan in the user's cache directory with a placeholder where the
# namespace goes. XGC2_FS150_RENDER_CACHE_DIR names another directory; empty, it
# turns the cache off.
RENDER_CACHE_ENV = 'XGC2_FS150_RENDER_CACHE_DIR'
RENDER_CACHE_FORMAT = '1'
RENDER_CACHE_PLACEHOLDER = '/xgc2_render_cache_namespace'
RENDER_CACHE_LOCK_SECONDS = 10.0
_NOFOLLOW = getattr(os, 'O_NOFOLLOW', 0)


def render_cache_directory():
    """The directory for rendered xacro, or None when the cache is off or has no home."""
    configured = os.environ.get(RENDER_CACHE_ENV)
    if configured is not None:
        return configured if os.path.isabs(configured) else None
    base = os.environ.get('XDG_CACHE_HOME')
    if not base or not os.path.isabs(base):
        home = os.path.expanduser('~')
        if not os.path.isabs(home):
            return None
        base = os.path.join(home, '.cache')
    return os.path.join(base, 'xgc2', 'fs150-sitl', 'simple-lidar')


class SimpleLidarRenderCache:
    """Rendered ``sensor.sdf.xacro`` for one scan, with the namespace left out.

    The key is a digest of everything the output depends on but the namespace:
    the xacro sources, the xacro executable and the other arguments. An entry is
    stored only after rendering with the placeholder, with the namespace put
    back, reproduces the document xacro rendered for the real namespace, so a
    template that uses the namespace in any other way is never cached; the
    scan is then marked unsupported and rendered directly. Only plain namespaces
    (``/uav1``, ``/fleet/uav1``) are substituted, and templates that read
    anything but ``$(arg ...)`` are never cached. Every failure to read or write
    the cache falls back to rendering with xacro.
    """

    def __init__(self, directory, key):
        self.directory = directory
        self.entry = os.path.join(directory, key + '.xml')
        self.unsupported = os.path.join(directory, key + '.unsupported')

    @classmethod
    def for_scan(cls, template, namespace, scan):
        """The cache for this scan, or None when this render must not use one."""
        directory = render_cache_directory()
        if (directory is None or not re.fullmatch(r'(/[A-Za-z0-9_]+)+', namespace)
                or RENDER_CACHE_PLACEHOLDER in namespace):
            return None
        executable = shutil.which('xacro')
        if executable is None:
            return None
        template = Path(template)
        try:
            sources = sorted({template, *template.parent.rglob('*.xacro')})
            texts = [source.read_bytes() for source in sources]
            status = os.stat(executable)
        except OSError:
            return None
        if any(re.search(rb'\$\((?!arg\s)|load_yaml', text) for text in texts):
            return None
        import hashlib  # about 3 ms of OpenSSL: only a render that uses the cache needs it
        digest = hashlib.sha256()
        for part in (RENDER_CACHE_FORMAT, executable, str(status.st_size), str(status.st_mtime_ns), *scan):
            digest.update(os.fsencode(part) + b'\0')
        for source, text in zip(sources, texts):
            digest.update(source.relative_to(template.parent).as_posix().encode() + b'\0' + text + b'\0')
        return cls(directory, digest.hexdigest()[:32])

    def load(self, namespace):
        """The cached document for this namespace, or None."""
        try:
            with open(self.entry, 'rb') as handle:
                text = handle.read().decode('utf-8')
            document = ET.fromstring(text.replace(RENDER_CACHE_PLACEHOLDER, namespace))
        except (OSError, UnicodeDecodeError, ET.ParseError):
            return None
        return document if len(document.findall("sensor[@name='simple_lidar']")) == 1 else None

    def render(self, namespace, xacro):
        """The parsed xacro output for `namespace`; ``xacro(namespace)`` renders it without the cache."""
        document = self.load(namespace)
        if document is not None:
            return document
        if os.path.exists(self.unsupported):
            return ET.fromstring(xacro(namespace))
        try:
            os.makedirs(self.directory, mode=0o700, exist_ok=True)
        except OSError:
            return ET.fromstring(xacro(namespace))
        lock = self._lock_fills()
        try:
            document = self.load(namespace)
            return document if document is not None else self._fill(namespace, xacro)
        finally:
            if lock is not None:
                os.close(lock)

    def _lock_fills(self):
        """Take the directory's fill lock, so a fleet rendering at once renders each scan once.

        Returns the descriptor that holds the lock, or None when there is none to hold: an
        unlockable directory, or a holder that kept it past the timeout (a stuck xacro).
        """
        try:
            import fcntl
            descriptor = os.open(os.path.join(self.directory, '.fill.lock'), os.O_CREAT | os.O_RDWR | _NOFOLLOW, 0o600)
        except (ImportError, OSError):
            return None
        deadline = time.monotonic() + RENDER_CACHE_LOCK_SECONDS
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return descriptor
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.02)
            except OSError:
                break
        os.close(descriptor)
        return None

    def _fill(self, namespace, xacro):
        try:
            descriptor, temporary = tempfile.mkstemp(prefix='.tmp-', suffix='.xml', dir=self.directory)
        except OSError:
            return ET.fromstring(xacro(namespace))
        try:
            # The check render runs beside the real one, so a cold cache costs
            # the first robot no more time than before, only a second process.
            import threading
            checked = []

            def render_with_placeholder():
                try:
                    checked.append(xacro(RENDER_CACHE_PLACEHOLDER))
                except Exception:  # whatever it is, the scan is then not cached
                    checked.append(None)

            checker = threading.Thread(target=render_with_placeholder)
            try:
                checker.start()
            except RuntimeError:  # no thread to be had: check after the real render
                checker = None
            try:
                document = ET.fromstring(xacro(namespace))
            finally:
                if checker is not None:
                    checker.join()
            if checker is None:
                render_with_placeholder()
            generic = checked[0]
            supported = False
            if generic is not None:
                try:
                    reproduced = ET.fromstring(generic.replace(RENDER_CACHE_PLACEHOLDER, namespace))
                    supported = (ET.tostring(reproduced) == ET.tostring(document)
                                 and len(reproduced.findall("sensor[@name='simple_lidar']")) == 1)
                except ET.ParseError:
                    pass
            try:
                if supported:
                    with os.fdopen(descriptor, 'wb') as handle:
                        descriptor = None
                        handle.write(generic.encode('utf-8'))
                    os.replace(temporary, self.entry)
                    temporary = None
                else:
                    os.close(os.open(self.unsupported, os.O_CREAT | os.O_WRONLY | _NOFOLLOW, 0o600))
            except (OSError, ValueError):
                pass  # the render is right; only the next robot pays for it
            return document
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass


def _render_simple_lidar_xacro(template, namespace, scan):
    return subprocess.check_output(['xacro', str(template), 'namespace:=' + namespace] + scan, text=True)


def apply_simple_lidar(root, enabled=False, robot_namespace='uav1',
                       pose='0 0 0.12 0 0 0', acceleration='gpu', rate_hz=10,
                       range_meters=20, hfov_deg=360, vfov_deg=180/math.pi,
                       hres=360, vres=16):
    """Optionally append the shared ideal world-XYZ lidar sensor to base_link."""
    model=root.find('model')
    body=None if model is None else model.find("link[@name='base_link']")
    if body is None:
        raise ValueError('FS150 base_link is required for the simple lidar')
    for sensor in list(body.findall("sensor[@name='simple_lidar']")):
        body.remove(sensor)
    if not enabled:
        return [('simple lidar disabled (sensor omitted)',0)]

    if acceleration not in ('cpu','gpu'):
        raise ValueError('simple lidar acceleration must be cpu or gpu')
    for name,value,maximum in [('rate_hz',rate_hz,100),('range_meters',range_meters,200),('hfov_deg',hfov_deg,360),('vfov_deg',vfov_deg,180)]:
        if not math.isfinite(value) or not 0 < value <= maximum:
            raise ValueError('invalid simple lidar '+name)
    if not 2 <= hres <= 4096 or not 2 <= vres <= 4096:
        raise ValueError('simple lidar scan resolutions must be in [2,4096]')
    package=Path(_rospack_find('xgc2_simple_lidar'))
    template=package/'models/sensor.sdf.xacro'
    namespace=robot_namespace.strip('/')
    namespace='/'+namespace if namespace else '/'
    scan=[
        'pose:='+pose,
        'acceleration:='+acceleration,
        'rate:='+str(rate_hz),
        'max_range:='+str(range_meters),
        'samples:='+str(hres),
        'layers:='+str(vres),
        'horizontal_fov:='+str(math.radians(hfov_deg)),
        'vertical_fov:='+str(math.radians(vfov_deg)),
    ]
    def render(namespace):
        return _render_simple_lidar_xacro(template,namespace,scan)
    cache=SimpleLidarRenderCache.for_scan(template,namespace,scan)
    sensor_root=ET.fromstring(render(namespace)) if cache is None else cache.render(namespace,render)
    sensors=sensor_root.findall("sensor[@name='simple_lidar']")
    if len(sensors)!=1:
        raise RuntimeError('xgc2_simple_lidar xacro must render exactly one simple_lidar sensor')
    body.append(sensors[0])
    return [('simple lidar enabled (ideal world XYZ points)',1)]


def _bool_arg(value):
    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise argparse.ArgumentTypeError("expected boolean value, got %r" % value)


def _rospack_find(package):
    return subprocess.check_output(["rospack", "find", package], text=True).strip()


def default_base_sdf():
    return resolve_base_sdf(None)


def default_output_path():
    return os.path.join(os.path.expanduser("~"), ".xgc2", "fs150_sitl", "iris_indoor.sdf")


def _candidate_base_sdfs(preferred):
    if preferred:
        yield preferred

    try:
        fs150_root = _rospack_find("gazebo_sim_fs150_sitl")
        yield os.path.join(fs150_root, "models", "fs150", "iris.sdf")
    except subprocess.CalledProcessError:
        pass

    try:
        px4_root = _rospack_find("gazebo_sim_px4_1_12")
        yield os.path.join(px4_root, "models", "iris", "iris.sdf")
    except subprocess.CalledProcessError:
        pass

    ros_distro = os.environ.get("ROS_DISTRO", "noetic")
    yield os.path.join("/opt", "ros", ros_distro, "share", "gazebo_sim_px4_1_12", "models", "iris", "iris.sdf")

    for prefix in os.environ.get("CMAKE_PREFIX_PATH", "").split(os.pathsep):
        if prefix:
            yield os.path.join(prefix, "share", "gazebo_sim_px4_1_12", "models", "iris", "iris.sdf")


def resolve_base_sdf(preferred):
    seen = set()
    checked = []
    for candidate in _candidate_base_sdfs(preferred):
        candidate = os.path.abspath(os.path.expanduser(candidate))
        if candidate in seen:
            continue
        seen.add(candidate)
        checked.append(candidate)
        if os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError(
        "could not find FS150/PX4 iris.sdf; checked: %s" % ", ".join(checked)
    )


def _remove_children(parent, predicate):
    removed = []
    for child in list(parent):
        if predicate(child):
            parent.remove(child)
            removed.append(child)
    return removed


def _remove_named_plugin(root, plugin_name):
    removed = []
    for parent in root.iter():
        removed.extend(
            _remove_children(
                parent,
                lambda child: child.tag == "plugin"
                and child.attrib.get("name") == plugin_name,
            )
        )
    return removed


def _remove_include_by_name(root, include_name):
    removed = []
    for parent in root.iter():
        removed.extend(
            _remove_children(
                parent,
                lambda child: child.tag == "include"
                and child.findtext("name") == include_name,
            )
        )
    return removed


def _remove_joint_by_name(root, joint_name):
    removed = []
    for parent in root.iter():
        removed.extend(
            _remove_children(
                parent,
                lambda child: child.tag == "joint"
                and child.attrib.get("name") == joint_name,
            )
        )
    return removed


def _remove_plugin_tag(root, plugin_name, tag):
    removed = []
    for plugin in root.iter("plugin"):
        if plugin.attrib.get("name") != plugin_name:
            continue
        for elem in list(plugin):
            if elem.tag == tag:
                plugin.remove(elem)
                removed.append(elem)
    return removed


def _set_text(elem, text):
    elem.text = "{:.12g}".format(float(text))


def _set_vector(elem, values):
    elem.text = " ".join("{:.12g}".format(float(value)) for value in values)


def _scaled_iris_base_inertia(mass):
    ratio = float(mass) / IRIS_BASE_MASS
    return tuple(
        value * ratio * FS150_EQUIVALENT_INERTIA_SCALE
        for value in IRIS_BASE_INERTIA
    )


def _patch_motor_model(
    root,
    motor_constant,
    moment_constant,
    time_constant_up=FS150_MOTOR_TIME_CONSTANT_UP,
    time_constant_down=FS150_MOTOR_TIME_CONSTANT_DOWN,
    rotor_drag_coefficient=FS150_ROTOR_DRAG_COEFFICIENT,
    rolling_moment_coefficient=FS150_ROLLING_MOMENT_COEFFICIENT,
):
    report = []
    motor_count = 0
    moment_count = 0
    time_up_count = 0
    time_down_count = 0
    rotor_drag_count = 0
    rolling_moment_count = 0
    for plugin in root.iter("plugin"):
        motor = plugin.find("motorConstant")
        if motor is not None:
            _set_text(motor, motor_constant)
            motor_count += 1
        moment = plugin.find("momentConstant")
        if moment is not None:
            _set_text(moment, moment_constant)
            moment_count += 1
        time_up = plugin.find("timeConstantUp")
        if time_up is not None:
            _set_text(time_up, time_constant_up)
            time_up_count += 1
        time_down = plugin.find("timeConstantDown")
        if time_down is not None:
            _set_text(time_down, time_constant_down)
            time_down_count += 1
        rotor_drag = plugin.find("rotorDragCoefficient")
        if rotor_drag is not None:
            _set_text(rotor_drag, rotor_drag_coefficient)
            rotor_drag_count += 1
        rolling_moment = plugin.find("rollingMomentCoefficient")
        if rolling_moment is not None:
            _set_text(rolling_moment, rolling_moment_coefficient)
            rolling_moment_count += 1
    report.append(("motorConstant", motor_count))
    report.append(("momentConstant", moment_count))
    report.append(("timeConstantUp", time_up_count))
    report.append(("timeConstantDown", time_down_count))
    report.append(("rotorDragCoefficient", rotor_drag_count))
    report.append(("rollingMomentCoefficient", rolling_moment_count))
    return report


def _patch_body_geometry(root):
    report = []
    collision_count = 0
    visual_count = 0
    for link in root.iter("link"):
        if link.attrib.get("name") != "base_link":
            continue
        for collision in link.iter("collision"):
            if collision.attrib.get("name") != "base_link_inertia_collision":
                continue
            size = collision.find("./geometry/box/size")
            if size is not None:
                _set_vector(size, FS150_BODY_COLLISION_SIZE)
                collision_count += 1
        existing_visuals = list(link.findall("visual"))
        visual = next((v for v in existing_visuals if v.attrib.get("name") == "base_link_inertia_visual"), None)
        for candidate in existing_visuals:
            if candidate is not visual:
                link.remove(candidate)
        if visual is None:
            visual = ET.SubElement(link, "visual", {"name": "base_link_inertia_visual"})
            material = ET.SubElement(visual, "material")
            ET.SubElement(material, "ambient").text = "0.42 0.35 0.05 1"
            ET.SubElement(material, "diffuse").text = "0.84 0.71 0.10 1"
            ET.SubElement(material, "specular").text = "0.05 0.04 0.02 1"
            ET.SubElement(material, "emissive").text = "0 0 0 1"
        pose = visual.find("pose")
        if pose is None:
            pose = ET.Element("pose")
            visual.insert(0, pose)
        _set_vector(pose, FS150_BODY_VISUAL_POSE)
        geometry = visual.find("geometry")
        if geometry is None:
            geometry = ET.SubElement(visual, "geometry")
        for child in list(geometry):
            geometry.remove(child)
        mesh = ET.SubElement(geometry, "mesh")
        ET.SubElement(mesh, "scale").text = " ".join("{:.12g}".format(value) for value in FS150_BODY_VISUAL_SCALE)
        ET.SubElement(mesh, "uri").text = "model://fs150/meshes/iris.stl"
        visual_count += 1
    report.append(("base_link collision size", collision_count))
    report.append(("base_link mesh visual scale", visual_count))
    return report


def _patch_body_mass(root, body_mass):
    target_mass = FS150_BASE_MASS if body_mass is None else float(body_mass)
    ixx, iyy, izz = _scaled_iris_base_inertia(target_mass)

    for link in root.iter("link"):
        if link.attrib.get("name") != "base_link":
            continue
        inertial = link.find("inertial")
        if inertial is None:
            break
        mass = inertial.find("mass")
        inertia = inertial.find("inertia")
        if mass is None or inertia is None:
            break

        _set_text(mass, target_mass)
        values = {
            "ixx": ixx,
            "iyy": iyy,
            "izz": izz,
            "ixy": 0.0,
            "ixz": 0.0,
            "iyz": 0.0,
        }
        for tag, value in values.items():
            elem = inertia.find(tag)
            if elem is not None:
                _set_text(elem, value)
        return [("base_link mass", 1), ("base_link equivalent iris inertia", 1)]

    raise RuntimeError("base_link inertial block not found in source SDF")


def _patch_rotor_model(root):
    pose_count = 0
    mass_count = 0
    inertia_count = 0
    collision_count = 0
    visual_count = 0
    visual_pose_count = 0
    for link in root.iter("link"):
        name = link.attrib.get("name")
        if name not in FS150_ROTOR_POSES:
            continue
        pose = link.find("pose")
        if pose is not None:
            _set_vector(pose, FS150_ROTOR_POSES[name])
            pose_count += 1

        inertial = link.find("inertial")
        if inertial is not None:
            mass = inertial.find("mass")
            if mass is not None:
                _set_text(mass, FS150_ROTOR_MASS)
                mass_count += 1
            inertia = inertial.find("inertia")
            if inertia is not None:
                values = {
                    "ixx": FS150_ROTOR_INERTIA[0],
                    "iyy": FS150_ROTOR_INERTIA[1],
                    "izz": FS150_ROTOR_INERTIA[2],
                    "ixy": 0.0,
                    "ixz": 0.0,
                    "iyz": 0.0,
                }
                for tag, value in values.items():
                    elem = inertia.find(tag)
                    if elem is not None:
                        _set_text(elem, value)
                inertia_count += 1

        for collision in link.iter("collision"):
            cylinder = collision.find("./geometry/cylinder")
            if cylinder is None:
                continue
            length = cylinder.find("length")
            radius = cylinder.find("radius")
            if length is not None and radius is not None:
                _set_text(length, FS150_PROP_LENGTH)
                _set_text(radius, FS150_PROP_COLLISION_RADIUS)
                collision_count += 1

        for visual in link.iter("visual"):
            pose = visual.find("pose")
            if pose is None:
                pose = ET.Element("pose")
                visual.insert(0, pose)
            _set_vector(pose, FS150_PROP_VISUAL_POSE)
            visual_pose_count += 1
            scale = visual.find("./geometry/mesh/scale")
            if scale is not None:
                _set_vector(scale, FS150_PROP_VISUAL_SCALE)
                visual_count += 1

    return [
        ("rotor pose", pose_count),
        ("rotor mass", mass_count),
        ("rotor inertia", inertia_count),
        ("rotor collision cylinder", collision_count),
        ("rotor visual pose", visual_pose_count),
        ("rotor visual scale", visual_count),
    ]


# PX4 SITL's multirotor base plugin (named "rosbag" in the iris model) builds
# a motor-speed message on every world update and never publishes it: the
# advertise and publish calls are commented out upstream (PX4 v1.12.3 sitl_gazebo
# 822050a, still so on PX4-SITL_gazebo-classic main). Nothing reads it, so the
# rendered model omits it whichever base SDF it starts from.
MULTIROTOR_BASE_PLUGIN = "libgazebo_multirotor_base_plugin.so"


def _remove_multirotor_base_plugin(root):
    removed = []
    for parent in root.iter():
        removed.extend(
            _remove_children(
                parent,
                lambda child: child.tag == "plugin"
                and child.attrib.get("filename") == MULTIROTOR_BASE_PLUGIN,
            )
        )
    return [("plugin " + MULTIROTOR_BASE_PLUGIN + " (unpublished per-update message)", len(removed))]


def _remove_gps_model(root):
    return [
        ("gps include gps0", len(_remove_include_by_name(root, "gps0"))),
        ("gps joint gps0_joint", len(_remove_joint_by_name(root, "gps0_joint"))),
    ]


def _indent(elem, level=0):
    spaces = "\n" + level * "  "
    child_spaces = "\n" + (level + 1) * "  "
    children = list(elem)
    if children:
        if not elem.text or not elem.text.strip():
            elem.text = child_spaces
        for child in children:
            _indent(child, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = spaces
    elif level and (not elem.tail or not elem.tail.strip()):
        elem.tail = spaces


def render_indoor_sdf(
    base_sdf,
    strip_mag=False,
    strip_baro=False,
    motor_constant=FS150_MOTOR_CONSTANT,
    moment_constant=FS150_MOMENT_CONSTANT,
    body_mass=None,
    enable_camera=False,
    robot_namespace="uav1",
    model_name="uav1",
    camera_fps=None,
    camera_hfov=None,
    enable_simple_lidar=False,
    simple_lidar_pose='0 0 0.12 0 0 0',
    simple_lidar_acceleration='gpu',
    simple_lidar_rate_hz=10,
    simple_lidar_range_meters=20,
    simple_lidar_hfov_deg=360,
    simple_lidar_vfov_deg=180/math.pi,
    simple_lidar_hres=360,
    simple_lidar_vres=16,
):
    tree = ET.parse(base_sdf)
    root = tree.getroot()
    report = []
    report.extend(_patch_body_geometry(root))
    report.extend(_patch_rotor_model(root))
    report.extend(_remove_gps_model(root))
    report.extend(_remove_multirotor_base_plugin(root))
    report.extend(_patch_motor_model(root, motor_constant, moment_constant))
    report.extend(_patch_body_mass(root, body_mass))
    if strip_mag:
        report.append(("plugin magnetometer_plugin", len(_remove_named_plugin(root, "magnetometer_plugin"))))
        report.append(("mavlink_interface magSubTopic", len(_remove_plugin_tag(root, "mavlink_interface", "magSubTopic"))))
    if strip_baro:
        report.append(("plugin barometer_plugin", len(_remove_named_plugin(root, "barometer_plugin"))))
        report.append(("mavlink_interface baroSubTopic", len(_remove_plugin_tag(root, "mavlink_interface", "baroSubTopic"))))
    report.extend(apply_visual_assets(root))
    report.extend(apply_camera(root,enable_camera,robot_namespace,model_name,camera_fps,camera_hfov))
    report.extend(apply_simple_lidar(root,enable_simple_lidar,robot_namespace,simple_lidar_pose,
        simple_lidar_acceleration,simple_lidar_rate_hz,simple_lidar_range_meters,simple_lidar_hfov_deg,simple_lidar_vfov_deg,simple_lidar_hres,simple_lidar_vres))
    _indent(root)
    return ET.tostring(root, encoding="unicode"), report


def write_atomic(path, content):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".sdf", dir=directory or None)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser(description="Render an indoor FS150 SDF from an FS150/PX4 iris SDF.")
    parser.add_argument("--base-sdf", default=None,
                        help="Source SDF. Defaults to gazebo_sim_fs150_sitl/models/fs150/iris.sdf when available.")
    parser.add_argument("--output", default=default_output_path(), help="Output SDF path.")
    parser.add_argument("--strip-mag", type=_bool_arg, default=False)
    parser.add_argument("--strip-baro", type=_bool_arg, default=False)
    parser.add_argument("--motor-constant", type=float, default=FS150_MOTOR_CONSTANT,
                        help="Gazebo motor thrust coefficient. Default is calibrated from measured FS150 hover throttle.")
    parser.add_argument("--moment-constant", type=float, default=FS150_MOMENT_CONSTANT)
    parser.add_argument("--body-mass", type=float, default=None,
                        help="Optional base_link mass override. Defaults to no-GPS FS150_BASE_MASS with equivalent inertia.")
    parser.add_argument("--print-path", action="store_true", help="Print only the output path on stdout.")
    parser.add_argument('--enable-camera',type=_bool_arg,default=False)
    parser.add_argument('--robot-namespace',default='uav1')
    parser.add_argument('--model-name',default='uav1')
    parser.add_argument('--camera-fps',type=float,default=None)
    parser.add_argument('--camera-hfov',type=float,default=None,help='Ideal horizontal field of view, radians')
    parser.add_argument('--enable-simple-lidar',type=_bool_arg,default=False)
    parser.add_argument('--simple-lidar-pose',default='0 0 0.12 0 0 0')
    parser.add_argument('--simple-lidar-acceleration',choices=('cpu','gpu'),default='gpu')
    parser.add_argument('--simple-lidar-rate-hz',type=float,default=10)
    parser.add_argument('--simple-lidar-range-meters',type=float,default=20)
    parser.add_argument('--simple-lidar-hfov-deg',type=float,default=360)
    parser.add_argument('--simple-lidar-vfov-deg',type=float,default=180/math.pi)
    parser.add_argument('--simple-lidar-hres',type=int,default=360)
    parser.add_argument('--simple-lidar-vres',type=int,default=16)
    args = parser.parse_args()

    base_sdf = resolve_base_sdf(args.base_sdf)
    sdf, report = render_indoor_sdf(
        base_sdf,
        args.strip_mag,
        args.strip_baro,
        args.motor_constant,
        args.moment_constant,
        args.body_mass,
        args.enable_camera,args.robot_namespace,args.model_name,args.camera_fps,args.camera_hfov,
        args.enable_simple_lidar,args.simple_lidar_pose,
        args.simple_lidar_acceleration,args.simple_lidar_rate_hz,args.simple_lidar_range_meters,args.simple_lidar_hfov_deg,args.simple_lidar_vfov_deg,args.simple_lidar_hres,args.simple_lidar_vres,
    )
    write_atomic(args.output, sdf)

    if args.print_path:
        print(args.output)
    else:
        print("rendered: %s" % args.output)
        print("base_sdf: %s" % base_sdf)
        for label, count in report:
            print("updated %d x %s" % (count, label))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print("failed to resolve ROS package: %s" % exc, file=sys.stderr)
        raise SystemExit(1)
