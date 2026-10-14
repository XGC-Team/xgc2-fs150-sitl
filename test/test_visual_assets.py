#!/usr/bin/env python3
"""Shared FS150 appearance must not modify the existing SITL plant."""
import copy
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PKG/'scripts'))
from render_fs150_indoor_sdf import apply_visual_assets, render_indoor_sdf


def physics(root):
    root=copy.deepcopy(root)
    for link in root.findall('model/link'):
        for visual in list(link.findall('visual')):link.remove(visual)
    # Compare parsed values, independent of XML indentation.
    def canonical(e):return (e.tag,sorted(e.attrib.items()),(e.text or '').strip(),tuple(canonical(c) for c in e))
    return canonical(root)


class SharedVisualsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.description=Path(subprocess.check_output(['rospack','find','fs150_description'],text=True).strip())

    def test_applying_shared_meshes_preserves_all_physics_and_is_idempotent(self):
        root=ET.parse(PKG/'models/fs150/iris.sdf').getroot()
        before=physics(root)
        apply_visual_assets(root,self.description)
        self.assertEqual(before,physics(root))
        first=ET.tostring(root)
        apply_visual_assets(root,self.description)
        self.assertEqual(first,ET.tostring(root))
        self.assertEqual(len(root.findall('model/link/visual')),5)
        for visual in root.findall('model/link/visual'):
            self.assertTrue(visual.findtext('geometry/mesh/uri').startswith(self.description.as_uri()+'/models/fs150_lod10k/'))
            self.assertIsNone(visual.find('material'))
        for i in range(4):
            visual=root.find("model/link[@name='base_link']/visual[@name='fs150_photo_rotor_%d']" % i)
            plugin=visual.find('plugin')
            self.assertEqual(plugin.get('filename'),'libxgc2_fs150_rotor_visual.so')
            self.assertEqual(plugin.findtext('rotor_link'),'rotor_%d' % i)
            self.assertEqual(tuple(map(float,visual.findtext('pose').split()[:3])),
                             ((.045 if i in (0,2) else -.045),
                              (-.0536190265 if i in (0,3) else .0536190265),.023))

    def test_indoor_renderer_retains_visual_assets_and_existing_motor_parameters(self):
        with patch('render_fs150_indoor_sdf.description_package',return_value=self.description):
            output,_=render_indoor_sdf(str(PKG/'models/fs150/iris.sdf'))
        root=ET.fromstring(output)
        self.assertEqual(len(root.findall('model/link/visual')),5)
        rotor=root.find("model/link[@name='rotor_0']")
        self.assertEqual(tuple(map(float,rotor.findtext('pose').split()[:3])),(.13,-.22,.023))
        self.assertEqual(rotor.findall('visual'),[])
        plugins=root.findall("model/plugin")
        motors=[p for p in plugins if p.find('motorConstant') is not None]
        self.assertEqual(len(motors),4)
        self.assertTrue(all(float(p.findtext('motorConstant'))>0 for p in motors))

    def test_rendered_ground_support_matches_physical_landing_collider(self):
        # Visual units remain metre/Z_UP; contact is authored independently of LOD.
        urdf=ET.parse(self.description/'urdf/fs150_visual.urdf').getroot()
        visual=urdf.find("link[@name='base_link']/visual")
        mesh=visual.find('geometry/mesh')
        dae=ET.parse(self.description/mesh.get('filename').split('package://fs150_description/')[1])
        ns={'c':'http://www.collada.org/2005/11/COLLADASchema'}
        self.assertEqual(dae.findtext('c:asset/c:up_axis',namespaces=ns),'Z_UP')
        self.assertEqual(float(dae.find('c:asset/c:unit',ns).get('meter')),1.0)
        physical=ET.parse(self.description/'urdf/fs150_photo.urdf').getroot()
        landing=physical.find("link[@name='base_link']/collision[@name='landing']")
        origin=landing.find('origin')
        self.assertEqual(tuple(map(float,origin.get('rpy').split())),(0.0,0.0,0.0))
        landing_bottom=float(origin.get('xyz').split()[2])-float(landing.find('geometry/box').get('size').split()[2])/2
        with patch('render_fs150_indoor_sdf.description_package',return_value=self.description):
            output,_=render_indoor_sdf(str(PKG/'models/fs150/iris.sdf'))
        collision=ET.fromstring(output).find("model/link[@name='base_link']/collision[@name='base_link_inertia_collision']")
        center_z=float(collision.findtext('pose').split()[2])
        height=float(collision.findtext('geometry/box/size').split()[2])
        self.assertAlmostEqual(center_z-height/2,landing_bottom,places=10)

if __name__=='__main__':unittest.main()
