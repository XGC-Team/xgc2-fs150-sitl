from pathlib import Path
import subprocess


def replace(path, old, new, count=1):
    file = Path(path)
    text = file.read_text()
    if text.count(old) != count:
        raise RuntimeError(f'{path}: expected {count} occurrences, found {text.count(old)}')
    file.write_text(text.replace(old, new))

replace('launch/fs150.launch', '''  <arg name="sdk_udp_port" default="$(eval 14540 + int(arg('ID')))"/>
  <arg name="mavros_local_port" default="$(eval 14540 + int(arg('ID')))"/>
  <arg name="mavros_remote_port" default="$(eval 14580 + int(arg('ID')))"/>''', '''  <arg name="mavros_local_port" default="$(eval 15000 + int(arg('ID')))"/>
  <arg name="mavros_remote_port" default="$(eval 15300 + int(arg('ID')))"/>
  <arg name="sdk_udp_port" default="$(arg mavros_local_port)"/>''')
replace('launch/fs150.launch', 'MAVROS UDP ports 14540+N -> 14580+N.', 'MAVROS UDP ports 15000+N -> 15300+N (the PX4 runtime offboard segment).')
replace('README.md', 'For multiple vehicles, change both the PX4 instance and the MAVROS URL:', '''For another vehicle in an already-running Gazebo world, use a unique PX4
instance, ROS namespace, model name, and SITL node name. The work directory
and MAVROS ports follow the model name and instance automatically:''')
replace('README.md', '''  model_name:=fs150_4 \\
  fcu_url:=udp://:14544@localhost:14561''', '''  model_name:=fs150_4 \\
  ns:=uav2 \\
  sitl_node_name:=sitl_fs150_4 \\
  start_gazebo:=false''')
replace('README.md', 'The wrapper also exposes `mav_system_id`,', '''The packaged PX4 runtime uses the dedicated Offboard segment: MAVROS binds
`15000 + ID` and sends to the PX4 port `15300 + ID`. For example, `ID:=3`
uses `udp://:15003@localhost:15303`, and `ID:=4` uses
`udp://:15004@localhost:15304`. The Gazebo SDK destination defaults to the
same MAVROS local port. Changing only `mavros_local_port`,
`mavros_remote_port`, or `fcu_url` does not reconfigure the PX4 runtime's
`px4-rc.mavlink`; custom ports require a matching runtime configuration.

The wrapper also exposes `mav_system_id`,''')

path = Path('test/test_launch_ports.py')
if path.exists():
    raise RuntimeError(f'{path} already exists')
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text('''#!/usr/bin/env python3
"""Check the FS150 launch port contract without requiring ROS or PX4."""
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LaunchPortsTest(unittest.TestCase):
    def setUp(self):
        self.launch = ET.parse(ROOT / "launch/fs150.launch").getroot()
        self.defaults = {arg.attrib["name"]: arg.attrib.get("default", "")
                         for arg in self.launch.findall("arg")}

    def resolve(self, name, overrides=None):
        overrides = overrides or {}
        value = str(overrides.get(name, self.defaults[name]))
        if value.startswith("$(eval ") and value.endswith(")"):
            return str(eval(value[7:-1], {"__builtins__": {}}, {
                "arg": lambda key: self.resolve(key, overrides),
                "int": int, "str": str,
            }))
        return re.sub(r"\\$\\(arg ([^)]+)\\)",
                      lambda m: self.resolve(m.group(1), overrides), value)

    def test_default_instance_and_bidirectional_pair(self):
        self.assertEqual(self.resolve("ID"), "3")
        self.assertEqual(self.resolve("fcu_url"), "udp://:15003@localhost:15303")
        self.assertEqual(self.resolve("mav_system_id"), "4")

    def test_full_mavlink_identity_range_has_unique_port_pairs(self):
        local, remote = set(), set()
        for instance in range(255):
            args = {"ID": instance}
            self.assertEqual(self.resolve("mavros_local_port", args), str(15000 + instance))
            self.assertEqual(self.resolve("mavros_remote_port", args), str(15300 + instance))
            self.assertEqual(self.resolve("fcu_url", args),
                             f"udp://:{15000 + instance}@localhost:{15300 + instance}")
            self.assertEqual(self.resolve("sdk_udp_port", args), str(15000 + instance))
            local.add(int(self.resolve("mavros_local_port", args)))
            remote.add(int(self.resolve("mavros_remote_port", args)))
        self.assertEqual(len(local), 255)
        self.assertEqual(len(remote), 255)
        self.assertFalse(local & remote)
        self.assertNotIn(14550, local | remote)

    def test_explicit_url_and_port_overrides_remain_available(self):
        overrides = {"mavros_local_port": 16001, "mavros_remote_port": 16301}
        self.assertEqual(self.resolve("fcu_url", overrides), "udp://:16001@localhost:16301")
        self.assertEqual(self.resolve("sdk_udp_port", overrides), "16001")
        overrides["fcu_url"] = "udp://:17001@localhost:17301"
        self.assertEqual(self.resolve("fcu_url", overrides), overrides["fcu_url"])
        overrides["sdk_udp_port"] = 18001
        self.assertEqual(self.resolve("sdk_udp_port", overrides), "18001")

    def test_sdk_arg_is_declared_after_its_dependency(self):
        names = [arg.attrib["name"] for arg in self.launch.findall("arg")]
        self.assertLess(names.index("mavros_local_port"), names.index("sdk_udp_port"))

    def test_wrapper_forwards_resolved_contract_to_base(self):
        include = self.launch.find("include")
        forwarded = {arg.attrib["name"]: arg.attrib["value"] for arg in include.findall("arg")}
        for key in ("fcu_url", "sdk_udp_port", "ID", "mav_system_id", "ns", "start_gazebo"):
            self.assertEqual(forwarded[key], "$(arg " + key + ")")


if __name__ == "__main__":
    unittest.main()
''')
replace('.github/workflows/ci.yml', '''          fetch-depth: 2
  build-debs:''', '''          fetch-depth: 2
      - name: Check launch port contract
        run: python3 -m unittest discover -s test -p test_launch_ports.py -v
  build-debs:''')
subprocess.run(['python3', '-m', 'unittest', 'discover', '-s', 'test', '-p', 'test_launch_ports.py', '-v'], check=True)
