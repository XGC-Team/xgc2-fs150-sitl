#!/usr/bin/env python3
import copy
import math
import os
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

PKG=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PKG/'scripts'))
from render_fs150_indoor_sdf import apply_camera,render_indoor_sdf

def installed_simple_lidar_package():
    package=Path(subprocess.check_output(['rospack','find','xgc2_simple_lidar'],text=True).strip()).resolve()
    roscpp=Path(subprocess.check_output(['rospack','find','roscpp'],text=True).strip()).resolve()
    if package.parent != roscpp.parent:
        raise AssertionError('xgc2_simple_lidar must resolve from the installed ROS share directory')
    for relative in ('models/sensor.xacro','models/sensor.sdf.xacro'):
        if not (package/relative).is_file():
            raise AssertionError('installed xgc2_simple_lidar is missing {}'.format(relative))
    return package

class CameraAssetsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.description=Path(subprocess.check_output(['rospack','find','fs150_description'],text=True).strip())
    def root(self):return ET.parse(PKG/'models/fs150/iris.sdf').getroot()
    def test_disabled_camera_has_no_sensor_or_plugin_and_does_not_change_plant(self):
        root=self.root();before=ET.tostring(root)
        apply_camera(root,False,description_root=self.description)
        self.assertEqual(before,ET.tostring(root))
        apply_camera(root,True,description_root=self.description)
        apply_camera(root,False,description_root=self.description)
        self.assertEqual(before,ET.tostring(root))
    def test_camera_is_at_urdf_lens_and_publishes_ideal_native_size(self):
        root=self.root();apply_camera(root,True,'/uav2','uav2',description_root=self.description)
        sensor=root.find("model/link/sensor[@name='fs150_front_camera']")
        self.assertEqual(sensor.get('type'),'camera')
        origin=ET.parse(self.description/'urdf/fs150_visual.urdf').getroot().find("joint[@name='camera_link_joint']/origin")
        self.assertEqual(sensor.findtext('pose'),origin.get('xyz')+' '+origin.get('rpy'))
        self.assertEqual((sensor.findtext('camera/image/width'),sensor.findtext('camera/image/height')),('1920','1080'))
        self.assertEqual(float(sensor.findtext('update_rate')),15)
        plugin=sensor.find('plugin')
        self.assertEqual(plugin.findtext('robotNamespace'),'/uav2')
        self.assertEqual(plugin.findtext('cameraName'),'camera2')
        self.assertEqual(plugin.findtext('imageTopicName'),'image')
        self.assertEqual(plugin.findtext('cameraInfoTopicName'),'camera_info')
        self.assertEqual(plugin.findtext('frameName'),'xgc/robots/uav2/camera_optical_frame')
        self.assertAlmostEqual(float(plugin.findtext('focalLength')),960)
        for key in ('distortionK1','distortionK2','distortionK3','distortionT1','distortionT2'):
            self.assertEqual(float(plugin.findtext(key)),0)
        first=ET.tostring(root);apply_camera(root,True,'/uav2','uav2',description_root=self.description)
        self.assertEqual(first,ET.tostring(root))
    def test_explicit_rate_and_fov_adjust_render_and_camera_info_together(self):
        root=self.root();apply_camera(root,True,fps=30,horizontal_fov=1.2,description_root=self.description)
        sensor=root.find("model/link/sensor[@name='fs150_front_camera']")
        self.assertEqual(float(sensor.findtext('update_rate')),30)
        self.assertAlmostEqual(float(sensor.findtext('plugin/focalLength')),960/math.tan(.6))
        self.assertEqual(float(sensor.findtext('camera/horizontal_fov')),1.2)
        for kwargs in ({'fps':0},{'fps':31},{'horizontal_fov':math.pi},{'horizontal_fov':float('nan')},{'robot_namespace':'../bad'}):
            with self.assertRaises(ValueError):apply_camera(self.root(),True,description_root=self.description,**kwargs)

    def test_simple_lidar_is_optional_and_renders_the_shared_xacro_per_robot(self):
        base=str(PKG/'models/fs150/iris.sdf')
        pose='0 0 0.12 0 0 0'
        with patch('render_fs150_indoor_sdf.description_package',return_value=self.description):
            with patch.dict(os.environ,{'ROS_PACKAGE_PATH':str(PKG),'CMAKE_PREFIX_PATH':''}):
                with patch('render_fs150_indoor_sdf._rospack_find') as find_package:
                    disabled,_=render_indoor_sdf(base)
                    find_package.assert_not_called()
            disabled_root=ET.fromstring(disabled)
            self.assertEqual(disabled_root.findall(".//sensor[@name='simple_lidar']"),[])

            shared_package=installed_simple_lidar_package()
            with patch('render_fs150_indoor_sdf._rospack_find',return_value=str(shared_package)) as find_package:
                first,_=render_indoor_sdf(
                    base,enable_simple_lidar=True,robot_namespace='/uav1',simple_lidar_pose=pose,
                )
                second,_=render_indoor_sdf(
                    base,enable_simple_lidar=True,robot_namespace='/uav2',simple_lidar_pose=pose,
                )
                self.assertEqual(find_package.call_count,2)

        def sensor_from(xml,namespace):
            root=ET.fromstring(xml)
            sensors=root.findall(".//sensor[@name='simple_lidar']")
            self.assertEqual(len(sensors),1)
            sensor=sensors[0]
            self.assertIs(sensor,root.find("model/link[@name='base_link']/sensor[@name='simple_lidar']"))
            self.assertEqual(sensor.findtext('pose'),pose)
            self.assertEqual(float(sensor.findtext('update_rate')),10)
            self.assertEqual(int(sensor.findtext('ray/scan/horizontal/samples')),360)
            self.assertEqual(int(sensor.findtext('ray/scan/vertical/samples')),16)
            self.assertEqual(float(sensor.findtext('ray/range/max')),20)
            plugin=sensor.find('plugin')
            self.assertEqual(plugin.findtext('robotNamespace'),namespace)
            return root,sensor

        first_root,first_sensor=sensor_from(first,'/uav1')
        second_root,second_sensor=sensor_from(second,'/uav2')
        self.assertEqual(first_sensor.findtext('plugin/robotNamespace')+'/simple_lidar/points','/uav1/simple_lidar/points')
        self.assertEqual(second_sensor.findtext('plugin/robotNamespace')+'/simple_lidar/points','/uav2/simple_lidar/points')

        def without_sensor(root):
            base_link=root.find("model/link[@name='base_link']")
            sensor=base_link.find("sensor[@name='simple_lidar']")
            if sensor is not None:
                base_link.remove(sensor)
            for element in root.iter():
                if element.text is not None:
                    element.text=element.text.strip() or None
                if element.tail is not None:
                    element.tail=element.tail.strip() or None
            return ET.tostring(root)

        self.assertEqual(without_sensor(first_root),without_sensor(disabled_root))
        self.assertEqual(without_sensor(second_root),without_sensor(disabled_root))

if __name__=='__main__':unittest.main()
