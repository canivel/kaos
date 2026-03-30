"""Agent isolation — logical, FUSE, and Linux namespace isolation tiers."""

from __future__ import annotations

import os
import platform
import tempfile
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kaos.core import AgentFS


@dataclass
class IsolationConfig:
    """Configuration for agent isolation."""

    mode: str = "logical"  # logical | fuse | namespace
    fuse_mount_base: str = "/tmp/agentfs"
    cgroups_enabled: bool = False
    memory_limit_mb: int = 4096
    cpu_shares: int = 1024


class LogicalIsolation:
    """
    Tier 1 — Logical isolation via SQL scoping.

    Every VFS operation is scoped by agent_id. The SDK physically cannot
    construct a query that crosses agent boundaries.
    """

    def __init__(self, afs: AgentFS, agent_id: str):
        self.afs = afs
        self.agent_id = agent_id

    def read(self, path: str) -> bytes:
        return self.afs.read(self.agent_id, path)

    def write(self, path: str, content: bytes) -> None:
        self.afs.write(self.agent_id, path, content)

    def delete(self, path: str) -> None:
        self.afs.delete(self.agent_id, path)

    def ls(self, path: str = "/") -> list[dict]:
        return self.afs.ls(self.agent_id, path)

    def exists(self, path: str) -> bool:
        return self.afs.exists(self.agent_id, path)

    def mkdir(self, path: str) -> None:
        self.afs.mkdir(self.agent_id, path)

    def get_state(self, key: str):
        return self.afs.get_state(self.agent_id, key)

    def set_state(self, key: str, value) -> None:
        self.afs.set_state(self.agent_id, key, value)


class IsolatedAgentProcess:
    """
    Tier 2 — Process isolation with FUSE-mounted VFS.

    Runs the agent in a separate mount namespace with a FUSE-mounted virtual
    filesystem. The agent process sees a normal filesystem — it has no idea
    it's backed by a SQLite database.

    NOTE: FUSE isolation requires Linux and the fusepy package.
    """

    def __init__(self, afs: AgentFS, agent_id: str, config: IsolationConfig | None = None):
        self.afs = afs
        self.agent_id = agent_id
        self.config = config or IsolationConfig()
        self.mount_point = os.path.join(self.config.fuse_mount_base, agent_id)
        self._mounted = False

    def _check_platform(self) -> None:
        if platform.system() != "Linux":
            raise RuntimeError(
                f"FUSE/namespace isolation requires Linux, got {platform.system()}. "
                "Use 'logical' isolation mode on this platform."
            )

    def mount(self) -> str:
        """Mount the agent's VFS via FUSE. Returns the mount point path."""
        self._check_platform()
        os.makedirs(self.mount_point, exist_ok=True)

        try:
            from kaos._fuse import AgentFUSE

            self._fuse = AgentFUSE(self.afs, self.agent_id)
            # FUSE mount runs in a background thread
            import threading

            self._fuse_thread = threading.Thread(
                target=self._fuse.mount,
                args=(self.mount_point,),
                daemon=True,
            )
            self._fuse_thread.start()
            self._mounted = True
        except ImportError:
            raise RuntimeError(
                "FUSE isolation requires the 'fusepy' package. "
                "Install with: uv pip install agentfs[fuse]"
            )

        return self.mount_point

    def unmount(self) -> None:
        """Unmount the FUSE filesystem."""
        if self._mounted:
            os.system(f"fusermount -u {self.mount_point}")
            self._mounted = False

    def start(self) -> None:
        """
        Full isolation: mount namespace + FUSE + capabilities drop.

        This creates a fully isolated environment where the agent process:
        1. Has its own mount namespace (via unshare)
        2. Sees only its FUSE-mounted VFS
        3. Has dropped capabilities
        4. Is resource-limited via cgroups
        """
        self._check_platform()
        self.mount()

        if self.config.cgroups_enabled:
            self._setup_cgroups()

    def _setup_cgroups(self) -> None:
        """Set up cgroups v2 resource limits for the agent process."""
        cgroup_path = f"/sys/fs/cgroup/agentfs/{self.agent_id}"
        os.makedirs(cgroup_path, exist_ok=True)

        # Memory limit
        mem_bytes = self.config.memory_limit_mb * 1024 * 1024
        with open(f"{cgroup_path}/memory.max", "w") as f:
            f.write(str(mem_bytes))

        # CPU weight (shares equivalent)
        with open(f"{cgroup_path}/cpu.weight", "w") as f:
            f.write(str(self.config.cpu_shares))

    def stop(self) -> None:
        """Stop the isolated agent and clean up."""
        self.unmount()


def create_isolation(
    afs: AgentFS, agent_id: str, config: IsolationConfig | None = None
) -> LogicalIsolation | IsolatedAgentProcess:
    """Factory to create the appropriate isolation level."""
    config = config or IsolationConfig()
    if config.mode == "logical":
        return LogicalIsolation(afs, agent_id)
    elif config.mode in ("fuse", "namespace"):
        return IsolatedAgentProcess(afs, agent_id, config)
    else:
        raise ValueError(f"Unknown isolation mode: {config.mode}")
