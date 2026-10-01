#!/usr/bin/env python3
"""The FS150 model runs only Gazebo plugins whose output something reads.

Runs without ROS: the renderer's visual-asset step is patched out.
"""
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / 'scripts'))
from render_fs150_indoor_sdf import MULTIROTOR_BASE_PLUGIN, render_indoor_sdf  # noqa: E402

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


if __name__ == '__main__':
    unittest.main()
