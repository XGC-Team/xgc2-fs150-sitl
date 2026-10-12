#!/usr/bin/env python3
"""Late/replaced master bootstrap and fixed UDP binding, no PX4 or Gazebo.

XGC_LONG_TESTS=1 includes the 60-second master outage cell.
"""
import importlib.util
import json
import os
from pathlib import Path
import random
import select
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from xmlrpc.server import SimpleXMLRPCServer

ROOT = Path(__file__).resolve().parents[1]


def private_port():
    for _ in range(200):
        port = random.randrange(20000, 40001)
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise RuntimeError("no private master port available")


class Master:
    def __init__(self, port):
        self.identity, self.loads = 101, 0
        self.run_id = ""
        self.parameters = {}
        self.clock_requested = threading.Event()
        self.server = SimpleXMLRPCServer(("127.0.0.1", port), allow_none=True, logRequests=False)
        self.server.register_function(lambda caller: [1, "pid", self.identity], "getPid")
        self.server.register_function(self.get, "getParam")
        self.server.register_function(self.set, "setParam")
        self.server.register_function(lambda *args: [1, "deleted", 0], "deleteParam")
        self.server.register_function(lambda *args: [1, "absent", False], "hasParam")
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .05})
        self.thread.start()

    def get(self, caller, name):
        if name == "/use_sim_time":
            self.clock_requested.set()
        if name == "/run_id":
            return [1, "run", self.run_id] if self.run_id else [-1, "absent", ""]
        for prefix, document in self.parameters.items():
            if name == prefix or name.startswith(prefix + "/"):
                for key in name[len(prefix):].strip("/").split("/"):
                    if key:
                        document = document[key]
                return [1, "value", document]
        return [-1, "absent", ""]

    def set(self, caller, name, value):
        self.loads += 1
        self.parameters[name] = value
        return [1, "loaded", 0]

    def close(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()


def resources(pid):
    fields = Path("/proc/%d/stat" % pid).read_text().rsplit(")", 1)[1].split()
    return ((int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK"),
            len(list(Path("/proc/%d/task" % pid).iterdir())), len(list(Path("/proc/%d/fd" % pid).iterdir())))


def launcher_worker(args):
    spec = importlib.util.spec_from_file_location("mavros_launcher", ROOT / "scripts/start_mavros.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module.MasterTransport.make_connection
    def counted(transport, host):
        with open(os.environ["ATTEMPT_FILE"], "a") as output:
            output.write("attempt\n")
        return original(transport, host)
    module.MasterTransport.make_connection = counted
    random.seed(23)
    return module.main(args)


class MavrosStartOrderTest(unittest.TestCase):
    def exercise(self, duration):
        with tempfile.TemporaryDirectory(prefix="mavros-start-test-") as directory:
            root = Path(directory)
            attempts = root / "attempts"
            port, udp_port = private_port(), private_port()
            environment = dict(os.environ, ROS_MASTER_URI="http://127.0.0.1:%d" % port,
                               ROS_HOME=str(root / "ros"), ATTEMPT_FILE=str(attempts))
            # This disposable node binds the allocated UDP port before its FCU
            # exists. The test checks the launcher's composition, not MAVLink.
            child = root / "node.py"
            child.write_text('''#!/usr/bin/env python3
import os, signal, socket, xmlrpc.client
master = xmlrpc.client.ServerProxy(os.environ["ROS_MASTER_URI"])
url = master.getParam("/fixture", "/uav1/mavros/fcu_url")[2]
port = int(url.split("@")[0].rsplit(":", 1)[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("127.0.0.1", port))
print("bound " + str(os.getpid()), flush=True)
signal.signal(signal.SIGTERM, lambda *args: sock.close())
try:
    while True:
        data, address = sock.recvfrom(64)
        sock.sendto(data, address)
except OSError:
    pass
''')
            child.chmod(0o755)
            log_path = root / "launcher.log"
            with log_path.open("w+") as log:
                process = subprocess.Popen([sys.executable, __file__, "--worker", str(child), "/uav1", "mavros", "",
                    "fcu_url=udp://:%d@127.0.0.1:15300" % udp_port, "gcs_url="], env=environment,
                    stdout=subprocess.PIPE, stderr=log, universal_newlines=True)
                master = None
                node_pid = None
                try:
                    time.sleep(.5)
                    self.assertIsNone(process.poll())
                    self.assertFalse(select.select([process.stdout], [], [], 0)[0])
                    before = resources(process.pid)
                    deadline = time.monotonic() + duration
                    while time.monotonic() < deadline:
                        time.sleep(min(.25, max(0, deadline - time.monotonic())))
                    after = resources(process.pid)
                    count = len(attempts.read_text().splitlines())
                    log.flush()
                    log.seek(0)
                    lines = log.read().splitlines()
                    self.assertLessEqual(count, 18 if duration == 60 else 8)
                    self.assertLessEqual(len(lines), 7 if duration == 60 else 2)
                    self.assertEqual(after[1:], before[1:])
                    if duration == 60:
                        self.assertLess(after[0] - before[0], 1.2)
                    master = Master(port)
                    self.assertTrue(master.clock_requested.wait(35))
                    self.assertEqual(master.loads, 0)
                    self.assertFalse(select.select([process.stdout], [], [], 0)[0])
                    master.parameters["/use_sim_time"] = True
                    self.assertTrue(select.select([process.stdout], [], [], 35)[0])
                    line = process.stdout.readline().strip()
                    self.assertTrue(line.startswith("bound "), line)
                    node_pid = int(line.split()[1])
                    self.assertEqual(master.loads, 2)  # One document, two leaf parameters.
                    master.run_id = "first-run"
                    time.sleep(10.2)
                    self.assertIsNone(process.poll(), "the first run id was mistaken for a replacement")
                    for restart in range(2):
                        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
                            peer.settimeout(3)
                            peer.sendto(str(restart).encode(), ("127.0.0.1", udp_port))
                            self.assertEqual(peer.recv(64), str(restart).encode())
                    self.assertEqual(master.loads, 2)
                    master.identity = 102
                    self.assertEqual(process.wait(timeout=15), 1)
                    self.assertFalse(Path("/proc/%d" % node_pid).exists())
                    print(json.dumps({"peer": "MAVROS master", "outage_seconds": duration,
                        "cpu_seconds": after[0] - before[0], "attempts": count, "log_lines": len(lines),
                        "threads": [before[1], after[1]], "fds": [before[2], after[2]], "parameter_writes": 2}))
                finally:
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    process.stdout.close()
                    if master is not None:
                        master.close()

    def test_late_master_fixed_port_and_master_replacement(self):
        self.exercise(1)

    @unittest.skipUnless(os.environ.get("XGC_LONG_TESTS") == "1", "60-second outage cell")
    def test_master_down_for_sixty_seconds(self):
        self.exercise(60)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        sys.exit(launcher_worker(sys.argv[2:]))
    unittest.main()
