#!/usr/bin/env python3
"""The FS150 model runs only Gazebo plugins whose output something reads.

With FS150_DESCRIPTION_TEST_ROOT pointing to the published description package,
runs without ROS; only visual loading is patched out, real collision resources
are still required. CI resolves the installed package through rospack by default.
"""
import sys
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / 'scripts'))
sys.path.insert(0, str(PKG.parent / 'scenes/xgc2_simple_lidar/python'))
import render_fs150_indoor_sdf as renderer  # noqa: E402
from render_fs150_indoor_sdf import MULTIROTOR_BASE_PLUGIN, prepare_frozen_model, render_indoor_sdf  # noqa: E402

SDF = PKG / 'models/fs150/iris.sdf'
# In model order: the four motor models (rotor forces), ground truth, the
# magnetometer and barometer (fed to PX4 by the mavlink interface), the PX4
# mavlink interface and the IMU (lockstep sensor stream).
EXPECTED_PLUGINS = ['libgazebo_motor_model.so'] * 4 + [
    'libgazebo_groundtruth_plugin.so',
    'libgazebo_magnetometer_plugin.so',
    'libgazebo_barometer_plugin.so',
    'libgazebo_mavlink_interface.so',
    'libgazebo_imu_plugin.so',
]


def plugins(root):
    return [plugin.get('filename') for plugin in root.iter('plugin')]


def canonical(element):
    return (element.tag, sorted(element.attrib.items()), (element.text or '').strip(),
            tuple(canonical(child) for child in element))


def render(base):
    with patch('render_fs150_indoor_sdf.apply_visual_assets', return_value=[]):
        output, report = render_indoor_sdf(str(base))
    return ET.fromstring(output), dict(report)


class ModelPluginsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The actual published collision description is the regression input.
        supplied = os.environ.get('FS150_DESCRIPTION_TEST_ROOT')
        cls.description = Path(supplied) if supplied else renderer.description_package()

    def setUp(self):
        patcher = patch.object(renderer, 'description_package', return_value=self.description)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_frozen_model_uses_robot_instance_ports_and_authored_camera_switch(self):
        row = {'slotId': 'px4-03', 'namespace': '/uav3',
               'kind': 'px4_multirotor', 'derived': {'modelId': 'fs150', 'sitlInstanceId': 5},
               'binding': {'applyModelDynamics': True, 'initialPose': {'x': 1.2, 'y': -0.9, 'z': 0, 'yaw': 0}, 'px4': {}}}
        with patch('render_fs150_indoor_sdf.apply_visual_assets', return_value=[]):
            value = prepare_frozen_model(row, str(SDF))
        self.assertEqual(value['format'], 'sdf')
        root = ET.fromstring(value['content'])
        mavlink = next(p for p in root.iter('plugin')
                       if p.get('filename') == 'libgazebo_mavlink_interface.so')
        self.assertEqual([mavlink.find(key).text for key in
                          ('mavlink_tcp_port', 'mavlink_udp_port', 'qgc_udp_port', 'sdk_udp_port')],
                         ['4565', '14565', '14550', '15005'])
        self.assertEqual(plugins(root), EXPECTED_PLUGINS)
        self.assertIsNone(root.find(".//sensor[@name='fs150_front_camera']"))

    def test_packaged_model_has_no_unpublished_multirotor_base_plugin(self):
        self.assertEqual(plugins(ET.parse(SDF).getroot()), EXPECTED_PLUGINS)

    def test_renderer_drops_it_from_any_base_and_changes_nothing_else(self):
        # A base SDF that still carries the plugin, like PX4's own iris model.
        root = ET.parse(SDF).getroot()
        legacy = ET.Element('plugin', name='rosbag', filename=MULTIROTOR_BASE_PLUGIN)
        for tag, text in (('robotNamespace', None), ('linkName', 'base_link'), ('rotorVelocitySlowdownSim', '10')):
            ET.SubElement(legacy, tag).text = text
        model = root.find('model')
        model.insert(list(model).index(model.find('plugin')), legacy)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / 'iris.sdf'
            ET.ElementTree(root).write(base)
            from_legacy, report = render(base)
        from_packaged, packaged_report = render(SDF)
        label = 'plugin ' + MULTIROTOR_BASE_PLUGIN + ' (unpublished per-update message)'
        self.assertEqual((report[label], packaged_report[label]), (1, 0))
        self.assertEqual(plugins(from_legacy), EXPECTED_PLUGINS)
        self.assertEqual(canonical(from_legacy), canonical(from_packaged))
        # Contact is one author-derived proxy, not the old Iris rotor envelope.
        model = from_packaged.find('model')
        collisions = model.findall('link/collision')
        self.assertEqual(len(collisions), 1)
        collision = model.find("link[@name='base_link']/collision")
        size = tuple(map(float, collision.findtext('geometry/box/size').split()))
        center = tuple(map(float, collision.findtext('pose').split()[:3]))
        lower, upper = renderer.airframe_collision_bounds(self.description)
        for axis in range(3):
            self.assertAlmostEqual(center[axis]-size[axis]/2, lower[axis], places=10)
            self.assertAlmostEqual(center[axis]+size[axis]/2, upper[axis], places=10)
        # Original IMPC y=+/-0.25: a strict gap between the two contact boxes.
        self.assertLess(size[1], 0.5)
        self.assertLess(upper[1]-0.25, lower[1]+0.25)
        base = ET.parse(SDF).getroot().find('model')
        self.assertEqual([canonical(j) for j in model.findall('joint')],
                         [canonical(j) for j in base.findall('joint')])
        for link in base.findall('link'):
            actual = model.find("link[@name='%s']" % link.get('name'))
            for field in ('pose', 'inertial/pose', 'inertial/mass',
                          'inertial/inertia/ixx', 'inertial/inertia/iyy', 'inertial/inertia/izz'):
                expected = list(map(float, link.findtext(field).split()))
                observed = list(map(float, actual.findtext(field).split()))
                for before, after in zip(expected, observed):
                    self.assertAlmostEqual(before, after, places=10)


class FrozenModelSelectionTest(unittest.TestCase):
    def test_asset_document_does_not_select_the_model(self):
        binding = {'applyModelDynamics': True, 'initialPose': {'x': 0, 'y': 0, 'z': 0, 'yaw': 0}, 'px4': {}}
        asset_only = {'slotId': 'px4-03', 'namespace': '/uav3', 'kind': 'px4_multirotor',
                      'physicalBinding': {'asset': {'px4': {'modelId': 'fs150'}}},
                      'derived': {'sitlInstanceId': 5}, 'binding': binding}
        with self.assertRaises(ValueError):
            prepare_frozen_model(asset_only, str(SDF))
        wrong_model = dict(asset_only, derived={'modelId': 'mocap_rotor', 'sitlInstanceId': 5})
        with self.assertRaises(ValueError):
            prepare_frozen_model(wrong_model, str(SDF))
        for instance in (-1, 244, True, 1.5):
            invalid = dict(asset_only, derived={'modelId': 'fs150', 'sitlInstanceId': instance})
            with self.assertRaises(ValueError):
                prepare_frozen_model(invalid, str(SDF))
        tracker = dict(asset_only, derived={'modelId': 'fs150', 'sitlInstanceId': 5},
                       binding=dict(binding, applyModelDynamics=False))
        with self.assertRaises(ValueError):
            prepare_frozen_model(tracker, str(SDF))


if __name__ == '__main__':
    unittest.main()
