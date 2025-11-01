# device.py
from netmiko import ConnectHandler
from models import BGPSession
from sqlalchemy.orm import Session
import re
from typing import Dict, Tuple
from logging_config import get_logger

logger = get_logger(__name__)


def detect_device_type(ip: str, username: str, password: str) -> str:
    logger.info(f"Detecting device type for {ip}")
    for device_type in ["cisco_xr", "nokia_sros"]:
        try:
            conn = ConnectHandler(
                device_type=device_type,
                host=ip,
                username=username,
                password=password,
                timeout=10,
                session_timeout=15,
                global_delay_factor=2,
            )
            prompt = conn.find_prompt()
            conn.disconnect()
            logger.debug(f"Prompt: {prompt} → detected {device_type}")
            if device_type == "nokia_sros" and "A:" in prompt:
                return "nokia_sros"
            if device_type == "cisco_xr" and "RP/" in prompt:
                return "cisco_xr"
        except Exception as e:
            logger.debug(f"Failed {device_type} detection on {ip}: {e}")
    raise ValueError("Could not detect device type")


def _update_db_neighbors(
    device_ip: str,
    device_type: str,
    neighbors: Dict[
        str, Tuple[int, str, int, str]
    ],  # (remote_as, state, local_as, local_ip)
    db: Session,
):
    logger.info(f"Updating {len(neighbors)} neighbors from {device_ip} ({device_type})")
    for ip, (remote_as, state, local_as, local_ip) in neighbors.items():
        session = db.query(BGPSession).filter_by(neighbor_ip=ip).first()
        if session:
            session.remote_as = remote_as
            session.local_as = local_as
            session.local_ip = local_ip
            session.device_ip = device_ip
            session.device_type = device_type
            session.status = "Up"
            session.session_state = state
            logger.debug(f"Updated existing session {ip}")
        else:
            new_session = BGPSession(
                neighbor_ip=ip,
                remote_as=remote_as,
                local_as=local_as,
                local_ip=local_ip,
                device_ip=device_ip,
                device_type=device_type,
                status="Up",
                session_state=state,
            )
            db.add(new_session)
            logger.debug(f"Added new session {ip}")
    db.commit()
    logger.info(f"Committed {len(neighbors)} sessions to DB.")


# ──────────────────────────────────────────────────────────────
# Cisco IOS-XR
# ──────────────────────────────────────────────────────────────
def sync_cisco_xr(device_ip: str, username: str, password: str, db_session_factory):
    logger.info(f"Syncing Cisco IOS-XR device: {device_ip}")
    device = {
        "device_type": "cisco_xr",
        "host": device_ip,
        "username": username,
        "password": password,
    }
    try:
        conn = ConnectHandler(**device)
        output = conn.send_command("show bgp summary vrf all | include ^[0-9]")
        conn.disconnect()
    except Exception as e:
        logger.error(f"Netmiko failed on {device_ip}: {e}", exc_info=True)
        raise

    neighbors: Dict[str, Tuple[int, str, int, str]] = {}
    for line in output.splitlines():
        # Example line:
        # 10.1.1.1          4 65001      123  45  67  89  12  34  Established
        parts = line.split()
        if len(parts) >= 10 and re.match(r"\d+\.\d+\.\d+\.\d+", parts[0]):
            neighbor_ip = parts[0]
            remote_as = int(parts[2])
            state = parts[-1]

            # Local AS & Local IP are not in the summary – grab from detailed view
            # We'll run a second command for each neighbor (lightweight)
            try:
                conn = ConnectHandler(**device)
                detail = conn.send_command(f"show bgp neighbor {neighbor_ip}")
                conn.disconnect()

                local_as_match = re.search(r"Local AS\s+:\s+(\d+)", detail)
                local_ip_match = re.search(r"Local host:\s+([\d.]+)", detail)

                local_as = int(local_as_match.group(1)) if local_as_match else 0
                local_ip = local_ip_match.group(1) if local_ip_match else ""

                neighbors[neighbor_ip] = (remote_as, state, local_as, local_ip)
            except Exception as e:
                logger.warning(f"Could not get detail for {neighbor_ip}: {e}")
                neighbors[neighbor_ip] = (remote_as, state, 0, "")

    with db_session_factory() as db:
        _update_db_neighbors(device_ip, "cisco_xr", neighbors, db)


# ──────────────────────────────────────────────────────────────
# Nokia SR OS
# ──────────────────────────────────────────────────────────────
def sync_nokia_sros(device_ip: str, username: str, password: str, db_session_factory):
    logger.info(f"Syncing Nokia SR OS device: {device_ip}")
    device = {
        "device_type": "nokia_sros",
        "host": device_ip,
        "username": username,
        "password": password,
    }
    try:
        conn = ConnectHandler(**device)
        output = conn.send_command("show router bgp neighbor | match Expression")
        conn.disconnect()
    except Exception as e:
        logger.error(f"Netmiko failed on {device_ip}: {e}", exc_info=True)
        raise

    neighbors: Dict[str, Tuple[int, str, int, str]] = {}
    current_ip = None
    for line in output.splitlines():
        ip_match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", line)
        if ip_match:
            current_ip = ip_match.group(1)

        remote_as_match = re.search(r"Remote AS\s+:\s+(\d+)", line)
        state_match = re.search(r"State\s+:\s+([A-Za-z]+)", line)
        local_as_match = re.search(r"Local AS\s+:\s+(\d+)", line)
        local_ip_match = re.search(r"Local Address\s+:\s+([\d.]+)", line)

        if current_ip and remote_as_match:
            state = state_match.group(1) if state_match else "Unknown"
            local_as = int(local_as_match.group(1)) if local_as_match else 0
            local_ip = local_ip_match.group(1) if local_ip_match else ""
            neighbors[current_ip] = (
                int(remote_as_match.group(1)),
                state,
                local_as,
                local_ip,
            )
            current_ip = None

    with db_session_factory() as db:
        _update_db_neighbors(device_ip, "nokia_sros", neighbors, db)
