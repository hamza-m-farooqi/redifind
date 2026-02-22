from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from redis import Redis
from rich.console import Console
from rich.prompt import Confirm


console = Console()


@dataclass(frozen=True)
class PreflightStatus:
    is_linux: bool
    redis_reachable: bool
    installer: Optional[str]


def _is_linux() -> bool:
    return platform.system().lower() == "linux"


def _can_ping(redis_url: str) -> bool:
    try:
        client = Redis.from_url(redis_url, decode_responses=True)
        return bool(client.ping())
    except Exception:
        return False


def _detect_installer() -> Optional[tuple[str, list[str]]]:
    if shutil.which("apt-get"):
        return "apt", []

    if shutil.which("dnf"):
        return "dnf", ["sudo", "dnf", "install", "-y", "redis"]

    if shutil.which("yum"):
        return "yum", ["sudo", "yum", "install", "-y", "redis"]

    if shutil.which("pacman"):
        return "pacman", ["sudo", "pacman", "-S", "--noconfirm", "redis"]

    if shutil.which("zypper"):
        return "zypper", ["sudo", "zypper", "install", "-y", "redis"]

    if shutil.which("apk"):
        return "apk", ["sudo", "apk", "add", "redis"]

    return None


def _start_service() -> None:
    if shutil.which("systemctl"):
        subprocess.run(["sudo", "systemctl", "enable", "--now", "redis-server"], check=False)
        subprocess.run(["sudo", "systemctl", "enable", "--now", "redis"], check=False)


def get_preflight_status(redis_url: str) -> PreflightStatus:
    is_linux = _is_linux()
    redis_reachable = _can_ping(redis_url) if is_linux else False
    installer = _detect_installer()
    return PreflightStatus(is_linux=is_linux, redis_reachable=redis_reachable, installer=installer[0] if installer else None)


def ensure_redis_ready(redis_url: str) -> None:
    if not _is_linux():
        console.print("redifind currently supports Linux only.")
        raise SystemExit(1)

    if _can_ping(redis_url):
        return

    console.print("Redis is not reachable at the configured URL.")
    install = Confirm.ask("Install Redis now?", default=False)
    if not install:
        console.print("Please install Redis and re-run redifind.")
        raise SystemExit(1)

    installer = _detect_installer()
    if installer is None:
        console.print("Could not detect a supported package manager. Please install Redis manually.")
        raise SystemExit(1)

    name, cmd = installer
    console.print(f"Installing Redis via {name}...")
    if name == "apt":
        subprocess.run(["sudo", "apt-get", "update"], check=False)
        subprocess.run(["sudo", "apt-get", "install", "-y", "redis-server"], check=False)
    else:
        subprocess.run(cmd, check=False)

    _start_service()

    if not _can_ping(redis_url):
        console.print("Redis still not reachable. Please start Redis and re-run redifind.")
        raise SystemExit(1)
