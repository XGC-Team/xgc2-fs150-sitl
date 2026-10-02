#!/usr/bin/env python3
"""Targeted aggregation, field omission/edit and actual-overlay tests."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'scripts/generate_native_flight_model.py'
SPEC = importlib.util.spec_from_file_location('native_flight_asset', SCRIPT)
asset = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(asset)
SDF = ROOT / 'models/fs150/iris.sdf'
PARAMS = ROOT / 'config/generated/fs150-sitl.params'


class NativeFlightAssetTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
        self.sdf = self.work / 'iris.sdf'
        self.sdf.write_bytes(SDF.read_bytes())
        self.params = self.work / 'actual.params'
        self.params.write_bytes(PARAMS.read_bytes())
        self.catalog = self.work / 'owner-names.json'
        # Name-selection fixture, not a production default/range table.
        self.catalog.write_text(json.dumps({'names': ['MC_ROLLRATE_P', 'MPC_THR_HOVER', 'MC_ROLL_P']}))

    def generate(self):
        return asset.generate(self.sdf, self.params, self.catalog)

    def edit(self, callback):
        tree = ET.parse(self.sdf)
        callback(tree.getroot().find('model'))
        tree.write(self.sdf, encoding='utf-8', xml_declaration=True)

    def test_original_sdf_independent_aggregate_and_source_coefficients(self):
        model = self.generate()
        # Independently calculated from the six original inertials and the
        # four declared rotor poses. These are regression answers, never
        # input physics/defaults used by the production generator.
        self.assertAlmostEqual(model['mass'], 0.31, places=14)
        self.assertAlmostEqual(model['center_of_mass'][0], 0, places=15)
        self.assertAlmostEqual(model['center_of_mass'][1], 0, places=15)
        self.assertAlmostEqual(model['center_of_mass'][2], 0.00046 / 0.31, places=15)
        expected = [0.002774116589354839, 0.002609097189354839, 0.00515920977]
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(model['inertia'][i][j], expected[i] if i == j else 0, places=14)
        self.assertEqual([r['motor_number'] for r in model['rotors']], [0, 1, 2, 3])
        self.assertEqual([r['spin'] for r in model['rotors']], ['ccw', 'ccw', 'cw', 'cw'])
        self.assertEqual([r['reaction_torque_sign'] for r in model['rotors']], [-1, -1, 1, 1])
        source = ET.parse(SDF).getroot().find('model')
        plugins = {int(p.findtext('motorNumber')): p for p in source.findall('plugin')
                   if p.get('filename') == 'libgazebo_motor_model.so'}
        for rotor in model['rotors']:
            plugin = plugins[rotor['motor_number']]
            self.assertEqual(rotor['kf'], float(plugin.findtext('motorConstant')))
            self.assertEqual(rotor['km'], float(plugin.findtext('motorConstant')) * float(plugin.findtext('momentConstant')))
            self.assertEqual(rotor['tau_up'], float(plugin.findtext('timeConstantUp')))
            self.assertEqual(rotor['tau_down'], float(plugin.findtext('timeConstantDown')))
            self.assertEqual(rotor['max_rot_velocity'], float(plugin.findtext('maxRotVelocity')))
            self.assertEqual(rotor['control_channel']['input_scaling'], 1000)
            self.assertEqual(rotor['control_channel']['zero_position_armed'], 100)
            self.assertEqual(rotor['control_channel']['zero_position_disarmed'], 0)
        self.assertEqual(len(model['control_channels']), 8)
        self.assertEqual([c['bound_motor_number'] for c in model['control_channels'][4:]], [None]*4)
        self.assertEqual(model['sources']['sdf']['sha256'], hashlib.sha256(self.sdf.read_bytes()).hexdigest())

    def test_rotated_inertial_tensor_and_mass_com_edits_are_consumed(self):
        original = self.generate()
        def rotate_inertial(model):
            inertial = model.find("link[@name='base_link']/inertial")
            inertial.find('pose').text = '0 0 0 0 0 {}'.format(math.pi / 2)
            inertia = inertial.find('inertia')
            for key, value in {'ixx': .002, 'iyy': .003, 'izz': .004, 'ixy': .0002}.items():
                inertia.find(key).text = str(value)
        self.edit(rotate_inertial)
        rotated = self.generate()
        self.assertAlmostEqual(rotated['inertia'][0][0]-original['inertia'][0][0], .003-.00186885417, places=14)
        self.assertAlmostEqual(rotated['inertia'][1][1]-original['inertia'][1][1], .002-.00186885417, places=14)
        self.assertAlmostEqual(rotated['inertia'][0][1], -.0002, places=14)
        self.edit(lambda model: setattr(model.find("link[@name='/imu_link']/inertial/pose"), 'text', '.1 .2 .3 0 0 0'))
        moved = self.generate()
        self.assertAlmostEqual(moved['center_of_mass'][0], .015*.1/.31, places=15)
        self.assertAlmostEqual(moved['center_of_mass'][1], .015*.2/.31, places=15)
        self.assertAlmostEqual(moved['center_of_mass'][2], (.00046+.015*.3)/.31, places=15)
        self.assertNotEqual(moved['inertia'], rotated['inertia'])
        self.edit(lambda model: setattr(model.find("link[@name='/imu_link']/inertial/mass"), 'text', '.03'))
        self.assertAlmostEqual(self.generate()['mass'], .325, places=14)

    def test_rotor_fields_and_channel_scaling_edits_are_not_replaced(self):
        def change(model):
            motor = model.find("plugin[@name='front_right_motor_model']")
            for key, value in {'motorConstant': '6e-6', 'momentConstant': '.08', 'timeConstantUp': '.02',
                               'timeConstantDown': '.03', 'maxRotVelocity': '1300', 'turningDirection': 'cw'}.items():
                motor.find(key).text = value
            model.find("link[@name='rotor_0']/pose").text = '.14 -.23 .025 0 0 0'
            channel = model.find("plugin[@name='mavlink_interface']/control_channels/channel[@name='rotor1']")
            channel.find('input_scaling').text = '1200'
            channel.find('zero_position_armed').text = '80'
        self.edit(change)
        rotor = self.generate()['rotors'][0]
        self.assertEqual(rotor['position_from_base_link'], [.14, -.23, .025])
        self.assertEqual(rotor['kf'], 6e-6)
        self.assertEqual(rotor['km'], 6e-6*.08)
        self.assertEqual((rotor['tau_up'], rotor['tau_down'], rotor['max_rot_velocity']), (.02, .03, 1300))
        self.assertEqual(rotor['reaction_torque_sign'], 1)
        self.assertEqual(rotor['control_channel']['input_scaling'], 1200)
        self.assertEqual(rotor['control_channel']['zero_position_armed'], 80)

    def test_missing_required_source_fields_fail_without_fallback(self):
        for expression, tag in [
            ("link[@name='base_link']/inertial", 'mass'),
            ("link[@name='base_link']/inertial/inertia", 'ixy'),
            ("link[@name='rotor_0']", 'pose'),
            ("plugin[@name='front_right_motor_model']", 'motorConstant'),
            ("plugin[@name='front_right_motor_model']", 'momentConstant'),
            ("plugin[@name='front_right_motor_model']", 'timeConstantUp'),
            ("plugin[@name='front_right_motor_model']", 'timeConstantDown'),
            ("plugin[@name='front_right_motor_model']", 'maxRotVelocity'),
            ("plugin[@name='mavlink_interface']/control_channels/channel[@name='rotor1']", 'input_scaling'),
            ("plugin[@name='mavlink_interface']/control_channels/channel[@name='rotor1']", 'zero_position_armed'),
            ("plugin[@name='mavlink_interface']/control_channels/channel[@name='rotor1']", 'zero_position_disarmed'),
        ]:
            with self.subTest(field=expression+'/'+tag):
                self.sdf.write_bytes(SDF.read_bytes())
                self.edit(lambda model: model.find(expression).remove(model.find(expression+'/'+tag)))
                with self.assertRaises(asset.ModelError):
                    self.generate()

    def test_invalid_numbers_topology_and_non_parallel_layout_fail(self):
        cases = [
            ("link[@name='base_link']/inertial/mass", 'nan'),
            ("link[@name='base_link']/inertial/inertia/ixx", '-.1'),
            ("plugin[@name='front_right_motor_model']/timeConstantUp", '0'),
            ("plugin[@name='front_right_motor_model']/maxRotVelocity", 'inf'),
            ("plugin[@name='front_right_motor_model']/motorNumber", '1'),
            ("plugin[@name='front_right_motor_model']/linkName", 'absent'),
            ("joint[@name='rotor_0_joint']/axis/xyz", '1 0 0'),
            ("joint[@name='rotor_0_joint']/axis/xyz", '0 0 -1'),
            ("joint[@name='rotor_0_joint']/axis/use_parent_model_frame", '0'),
            ("link[@name='rotor_0']/pose", '0.13 -.22 .023 0 .1 0'),
            ("joint[@name='/imu_joint']/axis/limit/upper", '.1'),
        ]
        for expression, value in cases:
            with self.subTest(field=expression):
                self.sdf.write_bytes(SDF.read_bytes())
                self.edit(lambda model: setattr(model.find(expression), 'text', value))
                with self.assertRaises(asset.ModelError):
                    self.generate()
        self.sdf.write_bytes(SDF.read_bytes())
        self.edit(lambda model: model.find("link[@name='rotor_0']/pose").set('relative_to', 'unresolved'))
        with self.assertRaises(asset.ModelError):
            self.generate()

    def test_actual_override_intersection_keeps_full_key_value_provenance(self):
        model = self.generate()
        records = {record['name']: record for record in model['parameter_records']}
        self.assertEqual(model['fcu_overrides'], {'MC_ROLLRATE_P': float(records['MC_ROLLRATE_P']['value_text']),
                                                'MPC_THR_HOVER': float(records['MPC_THR_HOVER']['value_text'])})
        self.assertEqual(model['fcu_unprovided_names'], ['MC_ROLL_P'])
        self.assertIn('MPC_USE_HTE', model['fcu_excluded_source_names'])
        self.assertIn('MPC_USE_HTE', records)
        raw = next(line for line in self.params.read_text().splitlines() if '\tMC_ROLLRATE_P\t' in line)
        self.assertEqual(records['MC_ROLLRATE_P']['value_text'], raw.split()[3])
        self.params.write_text(self.params.read_text().replace(raw, raw.replace(raw.split()[3], '.125')))
        changed = self.generate()
        self.assertEqual(changed['fcu_overrides']['MC_ROLLRATE_P'], .125)
        self.assertNotEqual(model['sources']['parameters']['sha256'], changed['sources']['parameters']['sha256'])
        self.assertEqual(model['mass'], changed['mass'])
        self.params.write_text('\n'.join(line for line in self.params.read_text().splitlines()
                                         if '\tMC_ROLLRATE_P\t' not in line) + '\n')
        removed = self.generate()
        self.assertNotIn('MC_ROLLRATE_P', removed['fcu_overrides'])
        self.assertIn('MC_ROLLRATE_P', removed['fcu_unprovided_names'])

    def test_overlay_and_owner_catalog_negative_controls(self):
        original = self.params.read_text()
        rows = [r for r in original.splitlines() if r and not r.startswith('#')]
        for modified in [original+'\n'+rows[0]+'\n',
                         original.replace(rows[0], '4 1 MC_ROLLRATE_P nan 9'),
                         original.replace(rows[0], '4 1 MC_ROLLRATE_P 0.1 99'),
                         original.replace(rows[0], '4 1 TEST_ENUM 1.5 6')]:
            self.params.write_text(modified)
            with self.assertRaises(asset.ModelError):
                self.generate()
        self.params.write_text(original)
        for names in [[], ['MC_ROLLRATE_P', 'MC_ROLLRATE_P'], ['invalid-name']]:
            self.catalog.write_text(json.dumps({'names': names}))
            with self.assertRaises(asset.ModelError):
                self.generate()

    def test_cli_determinism_and_no_partial_output_on_failure(self):
        first, second = self.work/'first.json', self.work/'second.json'
        first_header, second_header = self.work/'first.hpp', self.work/'second.hpp'
        args = [sys.executable, str(SCRIPT), '--sdf', str(self.sdf), '--params', str(self.params),
                '--fcu-name-catalog', str(self.catalog)]
        subprocess.run(args+['--output', str(first), '--cpp-output', str(first_header)], check=True)
        subprocess.run(args+['--output', str(second), '--cpp-output', str(second_header)], check=True)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(first_header.read_bytes(), second_header.read_bytes())
        self.assertIn('std::array<FcuOverride, 2>', first_header.read_text())
        self.assertNotIn('MPC_USE_HTE', first_header.read_text())
        self.assertIn('parameters_sha256', first_header.read_text())
        before = first.read_bytes()
        before_header = first_header.read_bytes()
        self.params.write_text('4 1 MC_ROLLRATE_P nan 9\n')
        failed = subprocess.run(args+['--output', str(first), '--cpp-output', str(first_header)], capture_output=True, text=True)
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(first.read_bytes(), before)
        self.assertEqual(first_header.read_bytes(), before_header)
        self.assertIn('must be finite', failed.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
