import os
import socket

from app.port_manager import PortManager, ProcessInfo


def test_parse_lsof_output():
    output = """
COMMAND   PID USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
Python  12345 user   12u  IPv4 0x9c22a8a0f6c3      0t0  TCP 127.0.0.1:8000 (LISTEN)
"""
    parsed = PortManager.parse_lsof_output(output)
    assert parsed == {"pid": 12345, "name": "Python"}


def test_parse_ss_output():
    output = """
LISTEN 0 128 127.0.0.1:8000 0.0.0.0:* users:(\"python\",pid=54321,fd=3)
"""
    parsed = PortManager.parse_ss_output(output)
    assert parsed == {"pid": 54321, "name": "python"}


def test_is_port_in_use():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
    except PermissionError:
        sock.close()
        return
    sock.listen(1)
    port = sock.getsockname()[1]

    manager = PortManager(project_root=os.getcwd())
    assert manager.is_port_in_use(port) is True

    sock.close()
    assert manager.is_port_in_use(port) is False


def test_find_available_port_skips_used():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
    except PermissionError:
        sock.close()
        return
    sock.listen(1)
    used_port = sock.getsockname()[1]

    manager = PortManager(project_root=os.getcwd())
    candidate = manager.find_available_port(used_port, used_port + 2)
    assert candidate in {used_port + 1, used_port + 2}

    sock.close()


def test_belongs_to_project_true_for_run_py():
    manager = PortManager(project_root="/Users/lifulin/Desktop/GoldPrice")
    cmdline = "python /Users/lifulin/Desktop/GoldPrice/run.py"
    assert manager.belongs_to_project(cmdline) is True


def test_belongs_to_project_false_for_other():
    manager = PortManager(project_root="/Users/lifulin/Desktop/GoldPrice")
    cmdline = "python /tmp/other/run.py"
    assert manager.belongs_to_project(cmdline) is False


def test_resolve_port_stops_previous_instance():
    class DummyManager(PortManager):
        def __init__(self):
            super().__init__(project_root="/Users/lifulin/Desktop/GoldPrice")
            self.stopped = []
            self.checks = 0

        def is_port_in_use(self, port):
            return True

        def get_process_using_port(self, port):
            return ProcessInfo(
                pid=123,
                name="python",
                cmdline="python /Users/lifulin/Desktop/GoldPrice/run.py",
            )

        def stop_process(self, pid, timeout=5):
            self.stopped.append(pid)
            return True

        def wait_for_port_release(self, port, timeout=5):
            return True

    manager = DummyManager()
    port = manager.resolve_port(8000, 8001, 8100)

    assert port == 8000
    assert manager.stopped == [123]


def test_resolve_port_uses_fallback_for_other_process():
    class DummyManager(PortManager):
        def is_port_in_use(self, port):
            return True

        def get_process_using_port(self, port):
            return ProcessInfo(pid=999, name="nginx", cmdline="nginx: master")

        def find_available_port(self, start, end):
            return 8002

    manager = DummyManager(project_root="/Users/lifulin/Desktop/GoldPrice")
    port = manager.resolve_port(8000, 8001, 8100)

    assert port == 8002
