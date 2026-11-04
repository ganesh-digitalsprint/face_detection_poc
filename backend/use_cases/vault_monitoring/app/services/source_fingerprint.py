"""Credential-free, stable fingerprints for configured camera source URLs."""
from __future__ import annotations

import ipaddress
import os
import re
import socket
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SECRET_PARAMETER = re.compile(r"(?:pass(?:word)?|pwd|token|api[_-]?key|secret|signature|auth(?:orization)?|credential|session|access[_-]?key)", re.I)
METADATA_HOSTS = {"metadata.google.internal", "metadata.goog", "instance-data.ec2.internal"}
DEFAULT_PORTS = {"rtsp": 554, "rtsps": 322, "http": 80, "https": 443}
SOURCE_TYPES = {"rtsp", "nvr_channel", "server_webcam", "browser_webcam", "video_file", "http_stream"}


def resolve_connection_ref(source_type: str, connection_ref: str) -> str:
    if source_type not in SOURCE_TYPES:
        raise ValueError("Unsupported camera source type")
    if source_type in {"server_webcam", "browser_webcam"}:
        return connection_ref.strip()
    if not connection_ref.startswith("env:"):
        raise ValueError("Camera source connection_ref must name a server environment variable")
    name = connection_ref[4:].strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name):
        raise ValueError("Invalid camera source environment-variable reference")
    value = os.environ.get(name)
    if not value:
        raise ValueError("Camera source environment-variable reference is not configured")
    return value


def _resolve_and_validate_host(host: str) -> None:
    normalized = host.rstrip(".").lower()
    if normalized in METADATA_HOSTS or normalized == "metadata":
        raise ValueError("Camera source host is not allowed")
    try:
        addresses = [ipaddress.ip_address(normalized)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(row[4][0]) for row in socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)]
        except (OSError, ValueError) as exc:
            raise ValueError("Camera source host could not be resolved") from exc
    for address in addresses:
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if (address.is_loopback or address.is_link_local or address.is_unspecified
                or address.is_multicast or address.is_reserved or address == ipaddress.ip_address("169.254.169.254")):
            raise ValueError("Camera source host is not allowed")


def canonical_source_fingerprint(source_type: str, value: str) -> str:
    """Validate a URL and return canonical identity without credentials or secret query values."""
    if source_type == "browser_webcam":
        parts = value.split(":", 2)
        if len(parts) != 3 or not parts[1] or not parts[2]:
            raise ValueError("browser_webcam references must be browser:<terminal_id>:<camera_code>")
        return f"browser:{parts[1].strip().lower()}:{parts[2].strip().lower()}"
    if source_type == "server_webcam":
        if not re.fullmatch(r"device:[0-9]{1,4}", value.strip()):
            raise ValueError("server_webcam references must use device:<index>")
        return f"server-webcam:{int(value.split(':', 1)[1])}"
    if source_type == "video_file":
        raw_path = value.strip()
        if not raw_path or any(ch in raw_path for ch in "\r\n\0"):
            raise ValueError("Invalid video file reference")
        return f"video-file:{os.path.normcase(str(Path(raw_path).expanduser().resolve(strict=False)))}"
    try:
        parsed = urlsplit(value.strip())
        scheme = parsed.scheme.lower()
        expected = {"rtsp", "rtsps"} if source_type in {"rtsp", "nvr_channel"} else {"http", "https"}
        if (scheme not in expected or not parsed.hostname or not parsed.path
                or any(ch.isspace() for ch in value) or parsed.fragment):
            raise ValueError
        port = parsed.port
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid camera source URL") from exc
    host = parsed.hostname.rstrip(".").lower()
    _resolve_and_validate_host(host)
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid camera source port")
    if port == DEFAULT_PORTS[scheme]:
        port = None
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host + (f":{port}" if port is not None else "")
    safe_query = sorted((key.lower(), val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
                        if not SECRET_PARAMETER.search(key))
    return urlunsplit((scheme, netloc, parsed.path, urlencode(safe_query, doseq=True), ""))


def masked_source(source_type: str, value: str) -> str:
    if source_type == "browser_webcam":
        return "Browser webcam"
    if source_type == "server_webcam":
        return f"Server webcam {value.strip()}"
    if source_type == "video_file":
        return "Server video file"
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").rstrip(".").lower()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = parsed.port
        if port is not None and port != DEFAULT_PORTS.get(parsed.scheme.lower()):
            host = f"{host}:{port}"
        return urlunsplit((parsed.scheme.lower(), host, parsed.path, "", ""))
    except (ValueError, UnicodeError):
        return "Configured camera source"
