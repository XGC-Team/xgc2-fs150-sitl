#!/usr/bin/env python3
"""The simple-lidar render cache: one xacro render per scan, however many robots.

Most of this runs without ROS: `_render_simple_lidar_xacro` is replaced by a
function that renders a stand-in template and counts its calls. The last class
renders through the installed xgc2_simple_lidar xacro and compares complete
SDFs with the cache off and on; it is skipped without `xacro` and `rospack`.
"""
import fcntl
import itertools
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape
from unittest.mock import patch

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / 'scripts'))
import render_fs150_indoor_sdf as renderer  # noqa: E402

SDF = PKG / 'models/fs150/iris.sdf'
ENV = renderer.RENDER_CACHE_ENV
PLACEHOLDER = renderer.RENDER_CACHE_PLACEHOLDER

TEMPLATE = '<sdf xmlns:xacro="http://www.ros.org/wiki/xacro"><xacro:arg name="namespace" default="/robot"/>%s</sdf>\n'


@unittest.skipUnless(shutil.which('xacro'), 'needs the real xacro Python package')
class RealXacroDependencyTest(unittest.TestCase):
    """Update installed bytes while the entry point and top-level template stay fixed."""

    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix='render-cache-dependencies-'))
        self.addCleanup(shutil.rmtree, self.scratch, True)
        import xacro
        self.module = self.scratch / 'python/xacro'
        shutil.copytree(Path(xacro.__file__).parent, self.module,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.executable = self.scratch / 'bin/xacro'
        self.executable.parent.mkdir()
        shutil.copy2(shutil.which('xacro'), self.executable)
        self.models = self.scratch / 'share/lidar/models'
        self.models.mkdir(parents=True)
        self.external = self.scratch / 'share/common/rate.xml'
        self.external.parent.mkdir()
        self.write_rate('10')
        self.template = self.models / 'sensor.sdf.xacro'
        self.template.write_text('''<sdf xmlns:xacro="http://www.ros.org/wiki/xacro">
          <xacro:arg name="namespace" default="/robot"/>
          <xacro:include filename="../../common/rate.xml"/>
          <sensor name="simple_lidar"><update_rate>${scan_rate}</update_rate>
            <plugin><robotNamespace>$(arg namespace)</robotNamespace></plugin>
          </sensor></sdf>''')
        patcher = patch.dict(os.environ, {
            ENV: str(self.scratch / 'cache'),
            'PATH': str(self.executable.parent) + os.pathsep + os.environ['PATH'],
            'PYTHONPATH': str(self.module.parent) + os.pathsep + os.environ.get('PYTHONPATH', ''),
            'PYTHONDONTWRITEBYTECODE': '1',
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_rate(self, rate):
        self.external.write_text('<sdf xmlns:xacro="http://www.ros.org/wiki/xacro">'
                                 '<xacro:property name="scan_rate" value="%s"/></sdf>' % rate)

    def render(self, namespace='/uav1', cache=True):
        def direct(name):
            return renderer._render_simple_lidar_xacro(self.template, name, [])
        entry = renderer.SimpleLidarRenderCache.for_scan(self.template, namespace, []) if cache else None
        return entry.render(namespace, direct) if entry else ET.fromstring(direct(namespace))

    def assert_rate(self, rate):
        document = self.render('/uav2')
        self.assertEqual(document.findtext('sensor/update_rate'), rate)
        self.assertEqual(ET.tostring(document), ET.tostring(self.render('/uav2', cache=False)))
        self.assertTrue(list((self.scratch / 'cache').glob('*.xml')), 'exercise a real cache entry')

    def test_external_include_update_invalidates_warm_cache(self):
        self.assert_rate('10')
        status = self.external.stat()
        self.write_rate('20')
        os.utime(self.external, ns=(status.st_atime_ns, status.st_mtime_ns))
        self.assert_rate('20')
        self.assertEqual(len(list((self.scratch / 'cache').glob('*.xml'))), 2)

    def test_nested_absolute_include_update_invalidates_warm_cache(self):
        leaf = self.external.parent / 'nested/rate.xml'
        leaf.parent.mkdir()
        leaf.write_bytes(self.external.read_bytes())
        self.external.write_text('<sdf xmlns:xacro="http://www.ros.org/wiki/xacro">'
                                 '<xacro:include filename="nested/rate.xml"/></sdf>')
        self.template.write_text(self.template.read_text().replace('../../common/rate.xml', str(self.external)))
        self.assert_rate('10')
        leaf.write_text(leaf.read_text().replace('value="10"', 'value="30"'))
        self.assert_rate('30')

    def test_missing_external_include_does_not_return_the_warm_document(self):
        self.assert_rate('10')
        self.external.unlink()
        with self.assertRaises(subprocess.CalledProcessError):
            self.render()

    def test_python_module_update_invalidates_with_unchanged_entry_point(self):
        implementation = self.module / '__init__.py'
        implementation.write_text(implementation.read_text() + '''
_original_process_doc = process_doc
def process_doc(doc, *args, **kwargs):
    _original_process_doc(doc, *args, **kwargs)
    doc.getElementsByTagName('update_rate')[0].firstChild.data = '11'
''')
        self.assert_rate('11')
        status = implementation.stat()
        entry = self.executable.read_bytes(), self.executable.stat().st_mtime_ns
        implementation.write_text(implementation.read_text().replace("data = '11'", "data = '22'"))
        os.utime(implementation, ns=(status.st_atime_ns, status.st_mtime_ns))
        self.assertEqual(entry, (self.executable.read_bytes(), self.executable.stat().st_mtime_ns))
        self.assert_rate('22')
        self.assertEqual(len(list((self.scratch / 'cache').glob('*.xml'))), 2)


class FakeXacro:
    """Stands in for `xacro sensor.sdf.xacro namespace:=... <scan>`; counts its renders."""

    def __init__(self, delay=0.0, uppercase_namespace_twice=False):
        self.calls = []
        self.delay = delay
        self.uppercase = uppercase_namespace_twice
        self.lock = threading.Lock()

    def __call__(self, template, namespace, scan):
        with self.lock:
            self.calls.append((namespace, tuple(scan)))
        time.sleep(self.delay)
        values = dict(item.split(':=', 1) for item in scan)
        namespace = escape(namespace)
        extra = '<label>%s</label>' % namespace.upper() if self.uppercase else ''
        return (
            '<?xml version="1.0" ?>\n'
            '<!-- autogenerated by xacro from %s -->\n'
            '<sdf version="1.6">\n'
            '  <sensor name="simple_lidar" type="%s">\n'
            '    <pose>%s</pose>\n'
            '    <update_rate>%s</update_rate>\n'
            '    <plugin filename="libxgc2_simple_lidar.so" name="simple_lidar">\n'
            '      <robotNamespace>%s</robotNamespace>\n'
            '    </plugin>%s\n'
            '  </sensor>\n'
            '</sdf>\n'
        ) % (template, 'ray' if values['acceleration'] == 'cpu' else 'gpu_ray', values['pose'], values['rate'],
             namespace, extra)

    @property
    def namespaces(self):
        return [namespace for namespace, _ in self.calls]


class CacheTestCase(unittest.TestCase):
    """A package with a template, a fake xacro executable and an empty cache directory."""

    def setUp(self):
        scratch = Path(tempfile.mkdtemp(prefix='render-cache-test-'))
        self.addCleanup(shutil.rmtree, scratch, True)
        self.scratch = scratch
        self.cache = scratch / 'cache'
        self.models = scratch / 'share/xgc2_simple_lidar/models'
        self.models.mkdir(parents=True)
        self.template = self.models / 'sensor.sdf.xacro'
        self.template.write_text(TEMPLATE % '<xacro:include filename="sensor.xacro"/>')
        (self.models / 'sensor.xacro').write_text('<robot xmlns:xacro="x"/>\n')
        self.executable = scratch / 'bin/xacro'
        self.executable.parent.mkdir()
        self.executable.write_text('#!/bin/sh\nexit 1\n')
        self.executable.chmod(0o755)
        self.xacro = FakeXacro()
        environment = {ENV: str(self.cache), 'PATH': str(self.executable.parent) + os.pathsep + os.environ['PATH']}
        for patcher in (patch.dict(os.environ, environment),
                        patch.object(renderer, '_xacro_implementation_sources',
                                     return_value=(('fake',), {self.executable})),
                        patch.object(renderer, '_render_simple_lidar_xacro', self.xacro),
                        patch.object(renderer, '_rospack_find', return_value=str(self.models.parent))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def render(self, namespace='/uav1', **scan):
        """Render one robot's SDF text the way a renderer process does."""
        text, _ = renderer.render_indoor_sdf(
            str(SDF), robot_namespace=namespace, enable_simple_lidar=True, **scan)
        return text

    def entries(self):
        return sorted(path.name for path in self.cache.glob('*') if not path.name.startswith('.'))

    def sensor(self, text):
        return ET.fromstring(text).find("model/link[@name='base_link']/sensor[@name='simple_lidar']")


class RenderCacheTest(CacheTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch.object(renderer, 'apply_visual_assets', return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_scan_is_rendered_once_for_every_robot(self):
        first = self.render('/uav1')
        self.assertEqual(sorted(self.xacro.namespaces), sorted(['/uav1', PLACEHOLDER]))
        second = self.render('/uav2')
        third = self.render('/fleet/uav3')
        self.assertEqual(len(self.xacro.calls), 2, 'later robots must not run xacro')
        self.assertEqual(self.sensor(first).findtext('plugin/robotNamespace'), '/uav1')
        self.assertEqual(self.sensor(second).findtext('plugin/robotNamespace'), '/uav2')
        self.assertEqual(self.sensor(third).findtext('plugin/robotNamespace'), '/fleet/uav3')
        self.assertEqual(len(self.entries()), 1)

    def test_the_sdf_is_the_one_xacro_alone_would_give(self):
        for namespace, scan in itertools.product(
                ('uav1', '/uav2', 'fleet/uav3/', '/a_b_9'),
                ({}, {'simple_lidar_acceleration': 'cpu', 'simple_lidar_rate_hz': 12.5},
                 {'simple_lidar_pose': '0.1 0 0.2 0 0 1.5', 'simple_lidar_hres': 90})):
            with self.subTest(namespace=namespace, scan=scan):
                cached = self.render(namespace, **scan)
                again = self.render(namespace, **scan)
                with patch.dict(os.environ, {ENV: ''}):
                    uncached = self.render(namespace, **scan)
                self.assertEqual(cached, uncached)
                self.assertEqual(again, uncached)

    def test_every_other_argument_has_its_own_entry(self):
        self.render('/uav1')
        self.render('/uav1', simple_lidar_rate_hz=20)
        self.render('/uav1', simple_lidar_acceleration='cpu')
        self.render('/uav1', simple_lidar_pose='0 0 0.3 0 0 0')
        self.assertEqual(len(self.entries()), 4)
        count = len(self.xacro.calls)
        for scan in ({}, {'simple_lidar_rate_hz': 20}, {'simple_lidar_acceleration': 'cpu'},
                     {'simple_lidar_pose': '0 0 0.3 0 0 0'}):
            self.render('/uav7', **scan)
        self.assertEqual(len(self.xacro.calls), count)

    def test_a_changed_template_or_xacro_is_rendered_again(self):
        self.render('/uav1')
        self.template.write_text(TEMPLATE % '<!-- edited --><xacro:include filename="sensor.xacro"/>')
        self.render('/uav2')
        self.assertEqual(len(self.xacro.calls), 4)
        (self.models / 'sensor.xacro').write_text('<robot xmlns:xacro="x"><!-- edited --></robot>\n')
        self.render('/uav3')
        self.assertEqual(len(self.xacro.calls), 6)
        status = self.executable.stat()
        os.utime(self.executable, ns=(status.st_atime_ns, status.st_mtime_ns + 10**9))
        self.render('/uav4')
        self.assertEqual(len(self.xacro.calls), 8)
        self.render('/uav5')
        self.assertEqual(len(self.xacro.calls), 8)
        self.assertEqual(len(self.entries()), 4)

    def test_namespaces_that_are_not_plain_are_rendered_directly(self):
        for namespace in ('/', 'uav-1', 'uav 1', 'a&b', 'a"b', 'a.b', PLACEHOLDER + '_2'):
            before = len(self.xacro.calls)
            text = self.render(namespace)
            self.assertEqual(len(self.xacro.calls), before + 1, namespace)
            expected = '/' + namespace.strip('/') if namespace.strip('/') else '/'
            self.assertEqual(self.sensor(text).findtext('plugin/robotNamespace'), expected)
        self.assertFalse(self.cache.exists())

    def test_a_template_that_uses_the_namespace_otherwise_is_not_cached(self):
        self.xacro.uppercase = True
        first = self.render('/uav1')
        self.assertEqual(len(self.xacro.calls), 2)
        self.assertEqual(ET.fromstring(first).findtext('.//label'), '/UAV1')
        entries = self.entries()
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0].endswith('.unsupported'), entries)
        second = self.render('/uav2')
        self.assertEqual(len(self.xacro.calls), 3, 'an unsupported scan costs one render, as before')
        self.assertEqual(ET.fromstring(second).findtext('.//label'), '/UAV2')

    def test_templates_that_read_more_than_arguments_are_not_cached(self):
        for text in ('<a b="$(env HOME)"/>', '<a b="$(find roscpp)"/>', '<a b="$(optenv X)"/>',
                     '<a b="${load_yaml(\'x.yaml\')}"/>'):
            with self.subTest(text=text):
                self.template.write_text(TEMPLATE % text)
                before = len(self.xacro.calls)
                self.render('/uav1')
                self.render('/uav2')
                self.assertEqual(len(self.xacro.calls), before + 2)
        self.assertFalse(self.cache.exists())
        self.template.write_text(TEMPLATE % '<a b="$(arg namespace)"/>')
        self.render('/uav1')
        self.assertEqual(len(self.entries()), 1)

    def test_no_xacro_executable_means_no_cache(self):
        with patch.object(renderer.shutil, 'which', return_value=None):
            self.render('/uav1')
            self.render('/uav2')
        self.assertEqual(len(self.xacro.calls), 2)
        self.assertFalse(self.cache.exists())

    def test_unknown_xacro_implementation_means_no_cache(self):
        with patch.object(renderer, '_xacro_implementation_sources', return_value=None):
            self.render('/uav1')
            self.render('/uav2')
        self.assertEqual(len(self.xacro.calls), 2)
        self.assertFalse(self.cache.exists())

    def test_unresolved_include_dependencies_are_rendered_directly(self):
        for filename in ('$(arg source)', '${source}', '*.xacro', '../missing.xml'):
            with self.subTest(filename=filename):
                self.template.write_text(TEMPLATE % ('<xacro:include filename="%s"/>' % filename))
                before = len(self.xacro.calls)
                self.render('/uav1')
                self.render('/uav2')
                self.assertEqual(len(self.xacro.calls), before + 2)
        self.assertFalse(self.cache.exists())

    def test_unusable_cache_directories_fall_back_to_xacro(self):
        blocked = self.scratch / 'file'
        blocked.write_text('not a directory')
        with patch.dict(os.environ, {ENV: str(blocked / 'cache')}):
            self.render('/uav1')
            self.render('/uav2')
        self.assertEqual(len(self.xacro.calls), 2)
        if hasattr(os, 'geteuid') and os.geteuid() != 0:
            self.cache.mkdir()
            self.cache.chmod(stat.S_IRUSR | stat.S_IXUSR)
            self.addCleanup(self.cache.chmod, stat.S_IRWXU)
            before = len(self.xacro.calls)
            self.render('/uav1')
            self.render('/uav2')
            self.assertEqual(len(self.xacro.calls), before + 2)

    def test_a_damaged_entry_is_replaced(self):
        self.render('/uav1')
        entry, = self.cache.glob('*.xml')
        for damage in (b'<sdf><sensor', b'\xff\xfe\x00', b'<sdf version="1.6"/>', b''):
            entry.write_bytes(damage)
            before = len(self.xacro.calls)
            text = self.render('/uav2')
            self.assertEqual(len(self.xacro.calls), before + 2, damage)
            self.assertEqual(self.sensor(text).findtext('plugin/robotNamespace'), '/uav2')
            self.render('/uav3')
            self.assertEqual(len(self.xacro.calls), before + 2, 'healed entry must hit')

    def test_cache_directory_choice(self):
        home = str(self.scratch / 'home')
        with patch.dict(os.environ, {'HOME': home}):
            os.environ.pop(ENV)
            os.environ.pop('XDG_CACHE_HOME', None)
            expected = os.path.join(home, '.cache', 'xgc2', 'fs150-sitl', 'simple-lidar')
            self.assertEqual(renderer.render_cache_directory(), expected)
            with patch.dict(os.environ, {'XDG_CACHE_HOME': str(self.scratch / 'xdg')}):
                self.assertEqual(renderer.render_cache_directory(),
                                 str(self.scratch / 'xdg/xgc2/fs150-sitl/simple-lidar'))
            with patch.dict(os.environ, {'XDG_CACHE_HOME': 'relative/cache'}):
                self.assertEqual(renderer.render_cache_directory(), expected)
            with patch.dict(os.environ, {ENV: ''}):
                self.assertIsNone(renderer.render_cache_directory())
            with patch.dict(os.environ, {ENV: 'relative'}):
                self.assertIsNone(renderer.render_cache_directory())
            with patch.dict(os.environ, {ENV: '/elsewhere'}):
                self.assertEqual(renderer.render_cache_directory(), '/elsewhere')
            # No home: nothing is cached, and nothing is written to the working directory.
            with patch.object(renderer.os.path, 'expanduser', return_value='~'):
                self.assertIsNone(renderer.render_cache_directory())
                working = self.scratch / 'cwd'
                working.mkdir()
                previous = os.getcwd()
                os.chdir(working)
                try:
                    self.render('/uav1')
                finally:
                    os.chdir(previous)
                self.assertEqual(list(working.iterdir()), [])

    def test_robots_rendering_at_once_run_xacro_once(self):
        self.xacro.delay = 0.05
        results = {}

        def robot(index):
            results[index] = self.render('/uav%d' % index)

        threads = [threading.Thread(target=robot, args=(index,)) for index in range(1, 9)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(self.xacro.calls), 2)
        for index, text in results.items():
            self.assertEqual(self.sensor(text).findtext('plugin/robotNamespace'), '/uav%d' % index)

    def test_a_stuck_fill_does_not_block_other_robots_for_long(self):
        self.cache.mkdir()
        descriptor = os.open(str(self.cache / '.fill.lock'), os.O_CREAT | os.O_RDWR)
        self.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        with patch.object(renderer, 'RENDER_CACHE_LOCK_SECONDS', 0.2):
            started = time.monotonic()
            text = self.render('/uav1')
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(self.sensor(text).findtext('plugin/robotNamespace'), '/uav1')
        self.assertEqual(len(self.xacro.calls), 2)

    def test_a_cache_that_cannot_be_written_does_not_fail_the_render(self):
        def full(*_args):
            raise OSError(28, 'No space left on device')

        with patch.object(renderer.os, 'replace', full):
            first = self.render('/uav1')
            second = self.render('/uav2')
        self.assertEqual(self.sensor(first).findtext('plugin/robotNamespace'), '/uav1')
        self.assertEqual(self.sensor(second).findtext('plugin/robotNamespace'), '/uav2')
        self.assertEqual(self.entries(), [])
        self.assertEqual([name for name in os.listdir(str(self.cache)) if name.startswith('.tmp-')], [])
        self.render('/uav3')
        self.assertEqual(len(self.entries()), 1, 'the next robot fills the cache once the disk allows it')

    def test_a_failing_check_render_does_not_fail_the_robot_and_marks_the_scan_unsupported(self):
        def fails_for_the_placeholder(template, namespace, scan):
            if namespace == PLACEHOLDER:
                raise subprocess.CalledProcessError(1, 'xacro')
            return self.xacro(template, namespace, scan)

        with patch.object(renderer, '_render_simple_lidar_xacro', fails_for_the_placeholder):
            text = self.render('/uav1')
            self.render('/uav2')
        self.assertEqual(self.sensor(text).findtext('plugin/robotNamespace'), '/uav1')
        entries = self.entries()
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0].endswith('.unsupported'), entries)
        self.assertEqual(self.xacro.namespaces, ['/uav1', '/uav2'], 'the second robot renders directly')

    def test_the_check_render_runs_beside_the_real_one(self):
        self.xacro.delay = 0.5
        started = time.monotonic()
        self.render('/uav1')
        elapsed = time.monotonic() - started
        self.assertEqual(len(self.xacro.calls), 2)
        self.assertLess(elapsed, 0.9, 'two sequential renders of 0.5 s would take 1 s')

    def test_a_missing_thread_only_serializes_the_check_render(self):
        with patch.object(threading.Thread, 'start', side_effect=RuntimeError("can't start new thread")):
            first = self.render('/uav1')
        self.assertEqual(self.sensor(first).findtext('plugin/robotNamespace'), '/uav1')
        self.assertEqual(len(self.xacro.calls), 2)
        self.assertEqual(len(self.entries()), 1)
        self.render('/uav2')
        self.assertEqual(len(self.xacro.calls), 2, 'the entry was stored')

    def test_an_xacro_failure_is_still_an_error(self):
        def failing(template, namespace, scan):
            raise subprocess.CalledProcessError(1, 'xacro')

        with patch.object(renderer, '_render_simple_lidar_xacro', failing):
            with self.assertRaises(subprocess.CalledProcessError):
                self.render('/uav1')
        self.assertEqual([name for name in os.listdir(str(self.cache)) if name.startswith('.tmp-')], [])


def real_tools():
    """(xgc2_simple_lidar share directory, fs150_description directory) or None."""
    try:
        return (Path(subprocess.check_output(['rospack', 'find', 'xgc2_simple_lidar'], text=True).strip()),
                Path(subprocess.check_output(['rospack', 'find', 'fs150_description'], text=True).strip()))
    except (OSError, subprocess.CalledProcessError):
        return None


@unittest.skipUnless(shutil.which('xacro') and shutil.which('rospack') and real_tools(),
                     'needs xacro, rospack, xgc2_simple_lidar and fs150_description')
class RealXacroTest(unittest.TestCase):
    """Complete SDFs, byte for byte, with the cache off, cold and warm, through the installed xacro."""

    NAMESPACES = ('uav1', '/uav2', 'fleet/uav10/', 'a_b_9', 'x/y/z', 'robot')
    SCANS = (
        {},
        {'simple_lidar_acceleration': 'cpu'},
        {'simple_lidar_acceleration': 'cpu', 'simple_lidar_rate_hz': 12, 'simple_lidar_range_meters': 8,
         'simple_lidar_hfov_deg': 120, 'simple_lidar_vfov_deg': 40, 'simple_lidar_hres': 90,
         'simple_lidar_vres': 8},
        {'simple_lidar_acceleration': 'gpu', 'simple_lidar_rate_hz': 5.5, 'simple_lidar_range_meters': 20.9,
         'simple_lidar_hfov_deg': 359.9, 'simple_lidar_vfov_deg': 57.29577951308232,
         'simple_lidar_pose': '0.15 -0.02 0.2 0 0.1 3.14159'},
    )

    def setUp(self):
        self.share, self.description = real_tools()
        self.cache = Path(tempfile.mkdtemp(prefix='render-cache-real-'))
        self.addCleanup(shutil.rmtree, self.cache, True)
        patcher = patch.dict(os.environ, {ENV: str(self.cache)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def render(self, namespace, camera, scan):
        with patch.object(renderer, 'description_package', return_value=self.description):
            text, _ = renderer.render_indoor_sdf(
                str(SDF), enable_camera=camera, robot_namespace=namespace,
                model_name='m_' + namespace.strip('/').replace('/', '_'), enable_simple_lidar=True, **scan)
        return text

    def test_cached_sdfs_are_byte_identical_to_uncached_ones(self):
        cases = 0
        for scan in self.SCANS:
            # The camera does not touch the lidar, so it is varied for two namespaces only.
            for namespace, camera in [(name, False) for name in self.NAMESPACES] + [
                    (self.NAMESPACES[0], True), (self.NAMESPACES[2], True)]:
                with patch.dict(os.environ, {ENV: ''}):
                    expected = self.render(namespace, camera, scan)
                for state in ('first (cold for the first robot of a scan)', 'second (warm)'):
                    self.assertEqual(self.render(namespace, camera, scan), expected, (namespace, camera, scan, state))
                cases += 1
        self.assertEqual(cases, len(self.SCANS) * (len(self.NAMESPACES) + 2))
        self.assertEqual(len(list(self.cache.glob('*.xml'))), len(self.SCANS))
        self.assertEqual(list(self.cache.glob('*.unsupported')), [])

    def test_the_installed_template_is_cacheable_and_later_robots_skip_xacro(self):
        real = renderer._render_simple_lidar_xacro
        calls = []

        def counting(template, namespace, scan):
            calls.append(namespace)
            return real(template, namespace, scan)

        with patch.object(renderer, '_render_simple_lidar_xacro', counting):
            self.render('uav1', False, {})
            self.assertEqual(sorted(calls), sorted(['/uav1', PLACEHOLDER]))
            self.render('uav2', True, {})
            self.render('fleet/uav3', False, {})
        self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
