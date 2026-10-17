#!/usr/bin/env python3
"""Actual product definitions/launchers, with no ROS master or UDP socket."""
import importlib.util
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE_RUNNER = ROOT.parent / "px4-sitl-112/scripts/run_px4_sitl.sh"
RUNNER = Path(os.environ.get("XGC_PX4_SITL_RUNNER", SOURCE_RUNNER if SOURCE_RUNNER.is_file()
                             else "/opt/ros/noetic/lib/px4_sitl_1_12/run_px4_sitl.sh"))
SOURCE_MAVLINK = RUNNER.parent.parent / "config/px4-rc.mavlink"
MAVLINK = SOURCE_MAVLINK if SOURCE_MAVLINK.is_file() else Path("/opt/ros/noetic/share/px4_sitl_1_12/config/px4-rc.mavlink")


def command(definition_id, ordinal):
    definition = json.loads((ROOT / "process-definitions" / (definition_id + ".json")).read_text())["definitions"][0]
    values = {name: parameter["default"] for name, parameter in definition["parameters"]["properties"].items()
              if "default" in parameter}
    values["namespace"] = "/uav" + str(ordinal + 1)
    if "sitlInstanceId" in definition["parameters"]["properties"]:
        values["sitlInstanceId"] = ordinal
    def render(text):
        return re.sub(r"\$\{([^}]+)\}", lambda match: str(values[match.group(1)]).lower()
                      if isinstance(values[match.group(1)], bool) else str(values[match.group(1)]), text)
    return ([render(arg) for arg in definition["command"]["args"]],
            {key: render(value) for key, value in definition["command"].get("env", {}).items()})


class ImmediateEvent:
    def is_set(self):
        return False

    def wait(self, timeout):
        return False


class Master:
    def getPid(self, caller):
        return [1, "pid", 101]

    def getParam(self, caller, name):
        return [1, "run", "fixture"]

    def deleteParam(self, *args):
        return [1, "deleted", 0]

    def __exit__(self, *args):
        return False


def mavros_parameters(ordinal, extra_settings=()):
    args, environment = command("mavros-px4-sitl", ordinal)
    spec = importlib.util.spec_from_file_location("mavros_vector_fixture", ROOT / "scripts/start_mavros.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args.extend(extra_settings)
    captured = {}
    def load(command, **kwargs):
        with open(command[2]) as stream:
            documents = list(yaml.safe_load_all(stream))
        captured.update(documents[-1])
    # Installed configuration files are unrelated to the resolved FCU identity.
    # Keep main's real parameter assembly, temporary YAML and bootstrap call.
    args[4] = ""
    child = mock.Mock()
    child.poll.return_value = 0
    child.returncode = 0
    with mock.patch.dict(os.environ, dict(environment, ROS_MASTER_URI="http://fixture.invalid")), \
            mock.patch.object(module.xmlrpc.client, "ServerProxy", return_value=Master()), \
            mock.patch.object(module.subprocess, "run", side_effect=load), \
            mock.patch.object(module.subprocess, "Popen", return_value=child), \
            mock.patch.object(module.threading, "Event", ImmediateEvent), \
            mock.patch.object(module.signal, "signal"):
        if module.main(args[1:]) != 0:
            raise AssertionError("launcher did not return its child's status")
    return captured


def sitl_vector(ordinal, directory):
    args, environment = command("px4-sitl-fs150", ordinal)
    captured = {}
    class Executed(Exception):
        pass
    def execute(path, argv):
        captured["argv"] = argv
        raise Executed()
    environment = dict(environment)
    with mock.patch.dict(os.environ, environment), \
            mock.patch.object(sys, "argv", args), \
            mock.patch("os.access", side_effect=lambda path, mode: path.endswith("/px4_sitl_1_12/run_px4_sitl.sh")), \
            mock.patch("os.path.isfile", return_value=True), \
            mock.patch("os.execv", side_effect=execute):
        try:
            runpy.run_path(str(ROOT / "scripts/start_sitl.py"), run_name="__main__")
        except Executed:
            pass
    argv = captured["argv"][1:]
    runtime = directory / "runtime"
    (runtime / "bin").mkdir(parents=True)
    (runtime / "etc/init.d-posix").mkdir(parents=True)
    (runtime / "etc/init.d-posix/rcS").write_text("# disposable startup boundary\n")
    binary = runtime / "bin/px4"
    binary.write_text("#!/usr/bin/env python3\nimport json,pathlib,sys\n"
                      "print(json.dumps({'argv':sys.argv[1:],'params':pathlib.Path('px4-rc.params').read_text()}))\n")
    binary.chmod(0o755)
    parameters = directory / "parameters"
    parameters.write_text("# empty scientific parameter fixture\n")
    for flag, value in (("--runtime-root", runtime), ("--work-dir", directory / "work"), ("--param-file", parameters)):
        argv[argv.index(flag) + 1] = str(value)
    child_environment = dict(os.environ, PX4_SITL_MAVLINK_SCRIPT=str(MAVLINK), **environment)
    output = subprocess.check_output(["bash", str(RUNNER), *argv], env=child_environment, text=True)
    return json.loads(output)


def native_offboard_ports(ordinal):
    output = subprocess.check_output(["sh", "-c", 'px4_instance="$1"; mavlink() { echo "$@"; }; . "$2"',
                                      "fixture", str(ordinal), str(MAVLINK)], text=True)
    fields = next(line.split() for line in output.splitlines() if "-m onboard" in line)
    return int(fields[fields.index("-u") + 1]), int(fields[fields.index("-o") + 1])


class ProcessStartupVectorsTest(unittest.TestCase):
    def check_fleet(self, count):
        urls, identities = set(), set()
        for ordinal in range(count):
            with self.subTest(ordinal=ordinal), tempfile.TemporaryDirectory(prefix="px4-native-vector-") as directory:
                parameters = mavros_parameters(ordinal)
                local, remote = native_offboard_ports(ordinal)
                self.assertEqual(parameters["fcu_url"], f"udp://:{remote}@127.0.0.1:{local}")
                self.assertEqual(parameters["target_system_id"], ordinal + 1)
                self.assertEqual(parameters["target_component_id"], 1)
                vector = sitl_vector(ordinal, Path(directory))
                self.assertEqual(vector["argv"][vector["argv"].index("-i") + 1], str(ordinal))
                self.assertNotIn("param set MAV_SYS_ID", vector["params"], "SITL must retain rcS's native instance identity")
                urls.add(parameters["fcu_url"])
                identities.add(parameters["target_system_id"])
        self.assertEqual(len(urls), count)
        self.assertEqual(len(identities), count)

    def test_three_native_startup_vectors(self):
        self.check_fleet(3)

    def test_seven_native_startup_vectors(self):
        self.check_fleet(7)

    def test_sitl_does_not_override_native_instance_identity(self):
        for ordinal in (0, 6):
            with self.subTest(ordinal=ordinal), tempfile.TemporaryDirectory(prefix="px4-native-id-") as directory, \
                    mock.patch.dict(os.environ, {"PX4_SITL_MAV_SYS_ID": "99"}):
                vector = sitl_vector(ordinal, Path(directory))
                self.assertEqual(vector["argv"][vector["argv"].index("-i") + 1], str(ordinal))
                self.assertNotIn("param set MAV_SYS_ID", vector["params"])

    def test_mavros_rejects_second_identity_authority(self):
        for setting in ("fcu_url=udp://:1@127.0.0.1:2", "target_system_id=42", "target_component_id=2"):
            with self.subTest(setting=setting), self.assertRaises(SystemExit):
                mavros_parameters(0, [setting])

    def test_standalone_defaults_use_instance_zero(self):
        for name in ("px4-sitl-fs150", "mavros-px4-sitl"):
            definition = json.loads((ROOT / "process-definitions" / (name + ".json")).read_text())["definitions"][0]
            self.assertEqual(definition["parameters"]["properties"]["sitlInstanceId"]["default"], 0)


if __name__ == "__main__":
    unittest.main()
