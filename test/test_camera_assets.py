#!/usr/bin/env python3
import copy
import math
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

PKG=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PKG/'scripts'))
from render_fs150_indoor_sdf import apply_camera

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

if __name__=='__main__':unittest.main()
