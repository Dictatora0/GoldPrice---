import logging
import os
import getpass
import re
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ProcessInfo:
    pid: int
    name: str
    cmdline: Optional[str] = None
    user: Optional[str] = None


class PortManager:
    """Manage port conflicts safely for local server startup."""

    def __init__(self, project_root: Optional[str] = None, host: str = "127.0.0.1"):
        self.project_root = os.path.abspath(project_root or os.getcwd())
        self.host = host

    @staticmethod
    def parse_lsof_output(output: str) -> Optional[dict]:
        lines = [line for line in output.splitlines() if line.strip()]
        if len(lines) < 2:
            return None
        parts = lines[1].split()
        if len(parts) < 2:
            return None
        try:
            return {"pid": int(parts[1]), "name": parts[0]}
        except ValueError:
            return None

    @staticmethod
    def parse_ss_output(output: str) -> Optional[dict]:
        for line in output.splitlines():
            match = re.search(r'users:\(\(?\"?([^\",]+)\"?,pid=(\d+)', line)
            if match:
                return {"pid": int(match.group(2)), "name": match.group(1)}
        return None

    def _run_command(self, args: list) -> Tuple[int, str]:
        try:
            result = subprocess.run(
                args,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return result.returncode, result.stdout
        except FileNotFoundError:
            return 127, ""

    def is_port_in_use(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            return sock.connect_ex((self.host, port)) == 0

    def get_process_using_port(self, port: int) -> Optional[ProcessInfo]:
        info = None

        if shutil.which("lsof"):
            code, out = self._run_command(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"]
            )
            if code == 0:
                parsed = self.parse_lsof_output(out)
                if parsed:
                    info = ProcessInfo(pid=parsed["pid"], name=parsed["name"])

        if info is None and shutil.which("ss"):
            code, out = self._run_command(["ss", "-lptn", f"sport = :{port}"])
            if code == 0:
                parsed = self.parse_ss_output(out)
                if parsed:
                    info = ProcessInfo(pid=parsed["pid"], name=parsed["name"])

        if info is None:
            return None

        info.cmdline = self.get_process_cmdline(info.pid)
        info.user = self.get_process_user(info.pid)
        return info

    def get_process_cmdline(self, pid: int) -> Optional[str]:
        code, out = self._run_command(["ps", "-p", str(pid), "-o", "command="])
        if code == 0:
            return out.strip() or None
        return None

    def get_process_user(self, pid: int) -> Optional[str]:
        code, out = self._run_command(["ps", "-p", str(pid), "-o", "user="])
        if code == 0:
            return out.strip() or None
        return None

    def belongs_to_project(self, cmdline: Optional[str]) -> bool:
        if not cmdline:
            return False
        run_path = os.path.join(self.project_root, "run.py")
        if self.project_root in cmdline or run_path in cmdline:
            return True
        project_name = os.path.basename(self.project_root)
        if project_name and project_name in cmdline and "uvicorn" in cmdline:
            return True
        return False

    def is_system_pid(self, pid: int) -> bool:
        return pid in {0, 1} or pid < 100

    def stop_process(self, pid: int, timeout: int = 5) -> bool:
        if self.is_system_pid(pid):
            logger.warning("Refusing to stop system PID %s", pid)
            return False

        try:
            os.kill(pid, signal.SIGTERM)
        except PermissionError:
            logger.warning("No permission to stop PID %s", pid)
            return False
        except ProcessLookupError:
            return True

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            time.sleep(0.2)

        logger.warning("PID %s did not exit after SIGTERM", pid)
        return False

    def wait_for_port_release(self, port: int, timeout: int = 5) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.is_port_in_use(port):
                return True
            time.sleep(0.2)
        return False

    def find_available_port(self, start: int, end: int) -> Optional[int]:
        for port in range(start, end + 1):
            if not self.is_port_in_use(port):
                return port
        return None

    def resolve_port(self, preferred: int, start: int, end: int) -> int:
        if not self.is_port_in_use(preferred):
            return preferred

        info = self.get_process_using_port(preferred)
        if info:
            logger.info(
                "Port %s is already in use by PID %s (%s).",
                preferred,
                info.pid,
                info.name,
            )
            same_user = info.user is None or info.user == getpass.getuser()
            if self.belongs_to_project(info.cmdline) and same_user:
                logger.info("Stopping previous server instance...")
                if self.stop_process(info.pid):
                    if self.wait_for_port_release(preferred):
                        logger.info(
                            "Server restarted on http://%s:%s", self.host, preferred
                        )
                        return preferred
            else:
                logger.info(
                    "Port %s is used by another application (PID %s).",
                    preferred,
                    info.pid,
                )
        else:
            logger.info("Port %s is in use by an unknown process.", preferred)

        candidate = self.find_available_port(start, end)
        if candidate is None:
            raise RuntimeError("No available ports found in fallback range")
        logger.info("Starting server on available port: %s", candidate)
        logger.info("Server running at http://%s:%s", self.host, candidate)
        return candidate

    def start_server(self, app, port: int, start: int, end: int, run_server=None) -> int:
        resolved_port = self.resolve_port(port, start, end)
        if run_server is None:
            import uvicorn

            run_server = uvicorn.run
        run_server(app, host=self.host, port=resolved_port)
        return resolved_port
