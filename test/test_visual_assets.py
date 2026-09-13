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

if __name__=='__main__':unittest.main()
