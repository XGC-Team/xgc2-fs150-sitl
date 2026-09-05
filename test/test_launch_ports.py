#!/usr/bin/env python3
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
        return re.sub(r"\$\(arg ([^)]+)\)",
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
