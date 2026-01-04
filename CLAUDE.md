# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BGP Session Manager TUI - A terminal user interface for managing BGP sessions across Cisco IOS-XR and Nokia SR OS devices. Uses Textual for the TUI, SQLAlchemy with SQLite for persistence, and Netmiko for device communication.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py

# Run tests
pytest test_device.py -v

# Setup pre-commit hooks
pre-commit install

# Run pre-commit on all files
pre-commit run --all-files
```

## Environment Variables

- `BGP_USERNAME` - Device SSH username (default: "admin")
- `BGP_PASSWORD` - Device SSH password (prompts if not set)

## Architecture

**main.py** - Textual TUI application with `BGPTUI` as the main app class and `AddSessionModal` for adding sessions. Keybindings: a=Add, s=Sync All, r=Refresh, d=Delete, q=Quit.

**device.py** - Network device interaction via Netmiko:
- `detect_device_type()` - Auto-detects Cisco XR vs Nokia SR OS by connecting and checking prompts
- `sync_cisco_xr()` / `sync_nokia_sros()` - Parse BGP neighbor output and update database
- Uses regex to extract neighbor IP, remote/local AS, state from CLI output

**models.py** - SQLAlchemy model `BGPSession` with fields: neighbor_ip (unique), remote_as, local_as, local_ip, description, device_fqdn, device_type, status, session_state, last_updated.

**db.py** - Database layer with `init_db()` for schema creation and `get_db()` context manager. Includes migration logic in `_ensure_new_columns()` that adds missing columns via ALTER TABLE.

**logging_config.py** - Rotating file logger (`bgp_manager.log`, 5MB, 3 backups) plus console output. Use `get_logger(__name__)` in modules.

## Data Flow

1. User adds session via modal → saved to SQLite with device_fqdn
2. Sync All → groups by device_fqdn → connects via Netmiko → parses CLI output → updates DB
3. Table refreshes from DB after any modification
