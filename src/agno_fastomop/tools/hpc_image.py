"""
HPC Image Fetch Tool

Fetches images from a remote HPC node via SSH (paramiko) and returns them
as Agno Image objects for use with vision-capable agents.

Configuration:
    config.toml [hpc] section with env var overrides:
    - HPC_HOST: hostname of the HPC node
    - HPC_USER: SSH username
    - HPC_SSH_KEY_PATH: path to SSH private key
    - HPC_PORT: SSH port (default: 22)
"""

import os
from io import BytesIO
from pathlib import PurePosixPath
from typing import Optional

import paramiko
from agno.media import Image

from agno_fastomop.config import config


# Mime type mapping from file extensions
MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".bmp": "image/bmp",
    ".dcm": "application/dicom",
    ".nii": "application/gzip",
    ".nii.gz": "application/gzip",
}


def _get_hpc_config() -> dict:
    """
    Load HPC connection config with priority: env vars > config.toml [hpc] section.

    Returns:
        dict with keys: host, username, ssh_key_path, port
    """
    hpc_config = config.get("hpc", {})

    return {
        "host": os.getenv("HPC_HOST", hpc_config.get("host", "")),
        "username": os.getenv("HPC_USER", hpc_config.get("username", "")),
        "ssh_key_path": os.getenv("HPC_SSH_KEY_PATH", hpc_config.get("ssh_key_path", "")),
        "port": int(os.getenv("HPC_PORT", hpc_config.get("port", 22))),
    }


def _infer_mime_type(remote_path: str) -> str:
    """Infer MIME type from file extension."""
    path = PurePosixPath(remote_path)

    # Handle double extensions like .nii.gz
    if remote_path.endswith(".nii.gz"):
        return MIME_TYPES[".nii.gz"]

    suffix = path.suffix.lower()
    return MIME_TYPES.get(suffix, "application/octet-stream")


def fetch_hpc_image(
    remote_path: str,
    host: Optional[str] = None,
    username: Optional[str] = None,
    ssh_key_path: Optional[str] = None,
    port: Optional[int] = None,
) -> Image:
    """
    Fetch an image file from a remote HPC node via SSH/SFTP.

    Opens a fresh SSH connection, downloads the file into memory, and returns
    an Agno Image object. Connection is stateless (opened and closed per call)
    to avoid stale sessions on HPC schedulers.

    Args:
        remote_path: Absolute path to the image file on the HPC node.
        host: Override HPC hostname (default: from config/env).
        username: Override SSH username (default: from config/env).
        ssh_key_path: Override SSH key path (default: from config/env).
        port: Override SSH port (default: from config/env).

    Returns:
        Image: Agno Image object with content bytes and mime_type set.

    Raises:
        ValueError: If required connection parameters are missing.
        FileNotFoundError: If the remote file does not exist.
        paramiko.SSHException: If SSH connection fails.
    """
    # Merge explicit args with config defaults
    cfg = _get_hpc_config()
    _host = host or cfg["host"]
    _username = username or cfg["username"]
    _key_path = ssh_key_path or cfg["ssh_key_path"]
    _port = port or cfg["port"]

    if not _host:
        raise ValueError("HPC host not configured. Set HPC_HOST env var or [hpc] host in config.toml")
    if not _username:
        raise ValueError("HPC username not configured. Set HPC_USER env var or [hpc] username in config.toml")

    # Build SSH client
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    ssh_timeout = int(os.getenv("HPC_SSH_TIMEOUT", "30"))

    connect_kwargs = {
        "hostname": _host,
        "port": _port,
        "username": _username,
        "timeout": ssh_timeout,
        "banner_timeout": ssh_timeout,
        "auth_timeout": ssh_timeout,
        "allow_agent": True,    # Use SSH agent (ssh-add) if available
        "look_for_keys": True,  # Also try ~/.ssh/ keys as fallback
    }

    # Try SSH agent first (handles passphrase-protected keys loaded via ssh-add).
    # Only fall back to explicit key_filename if agent fails.
    if _key_path:
        key_path_expanded = os.path.expanduser(_key_path)
        # First attempt: connect via agent (ignoring key file)
        try:
            client.connect(**connect_kwargs)
        except (paramiko.SSHException, paramiko.AuthenticationException):
            # Agent didn't work -- try key file directly
            client.close()
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connect_kwargs["key_filename"] = key_path_expanded
            connect_kwargs["allow_agent"] = False
            client.connect(**connect_kwargs)
    else:
        client.connect(**connect_kwargs)

    try:
        sftp = client.open_sftp()

        # Verify file exists
        try:
            sftp.stat(remote_path)
        except FileNotFoundError:
            raise FileNotFoundError(f"Remote file not found: {remote_path} on {_host}")

        # Download into memory
        buffer = BytesIO()
        sftp.getfo(remote_path, buffer)
        buffer.seek(0)
        image_bytes = buffer.read()

        sftp.close()
    finally:
        client.close()

    mime_type = _infer_mime_type(remote_path)
    filename = PurePosixPath(remote_path).name

    return Image(
        content=image_bytes,
        mime_type=mime_type,
        id=remote_path,
        format=PurePosixPath(remote_path).suffix.lstrip(".").lower(),
    )
