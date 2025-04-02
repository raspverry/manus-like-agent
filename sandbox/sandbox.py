# sandbox/sandbox.py
"""
Dockerサンドボックス環境を用いてShellコマンドやPython実行を隔離する。
"""
import os
import logging
import docker
import uuid
from typing import Tuple

from config import CONFIG

logger = logging.getLogger(__name__)

class DockerSandbox:
    def __init__(self):
        self.workspace_dir = CONFIG["system"]["workspace_dir"]
        self.image_name = CONFIG["docker"]["image_name"]
        self.allow_sudo = CONFIG["security"]["allow_sudo"]
        self.allow_network = CONFIG["security"]["allow_network"]
        self.memory_limit = CONFIG["docker"]["memory_limit"]
        self.cpu_limit = CONFIG["docker"]["cpu_limit"]
        
        self.client = docker.from_env()
        self.containers = {}
    
    def _get_or_create_container(self, container_id: str = None):
        if container_id is None:
            container_id = f"manus-sandbox-{uuid.uuid4().hex[:8]}"
        
        if container_id in self.containers:
            container = self.containers[container_id]
            container.reload()
            if container.status != "running":
                container.start()
            return container
        
        network_mode = "bridge" if self.allow_network else "none"
        
        container = self.client.containers.run(
            self.image_name,
            command="sleep infinity",
            detach=True,
            remove=True,
            name=container_id,
            network_mode=network_mode,
            mem_limit=self.memory_limit,
            cpu_period=100000,
            cpu_quota=int(self.cpu_limit * 100000),
            volumes={
                self.workspace_dir: {
                    "bind": "/home/ubuntu/workspace",
                    "mode": "rw"
                }
            },
            working_dir="/home/ubuntu/workspace"
        )
        
        self.containers[container_id] = container
        return container
    
    def execute_command(self, container_id: str, command: str, cwd: str = "/home/ubuntu/workspace") -> Tuple[str, str, int]:
        container = self._get_or_create_container(container_id)
        cmd_str = f"bash -c 'cd {cwd} && {command}'"
        exit_code, output = container.exec_run(cmd_str, demux=True, tty=True, privileged=self.allow_sudo)
        stdout, stderr = output if output else (b"", b"")
        return stdout.decode("utf-8"), stderr.decode("utf-8"), exit_code
    
    def execute_python(self, container_id: str, code: str, cwd: str = "/home/ubuntu/workspace"):
        container = self._get_or_create_container(container_id)
        # 一時ファイルにコードを書き込んで実行
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py", dir=self.workspace_dir) as f:
            f.write(code.encode("utf-8"))
            script_name = os.path.basename(f.name)
        
        cmd = f"python3 {script_name}"
        return self.execute_command(container_id, cmd, cwd)
    
    def cleanup(self):
        for cid, container in list(self.containers.items()):
            try:
                container.stop()
            except:
                pass
        self.containers.clear()

_sandbox_instance = None

def get_sandbox():
    global _sandbox_instance
    if _sandbox_instance is None:
        _sandbox_instance = DockerSandbox()
    return _sandbox_instance
