# BGP Session Manager TUI

A terminal user interface for managing and monitoring BGP sessions across Cisco IOS-XR and Nokia SR OS devices.

## Features

- Track BGP sessions across multiple network devices
- Auto-detect device type (Cisco IOS-XR or Nokia SR OS)
- Sync session state directly from devices via SSH
- Color-coded status display (green=Up, red=Down, yellow=Unknown)
- SQLite database for persistent session storage
- Rotating log files for troubleshooting

## Installation

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# (Optional) Install pre-commit hooks
pre-commit install
```

## Configuration

### Environment Variables

Set these before running the application:

| Variable | Description | Default |
|----------|-------------|---------|
| `BGP_USERNAME` | SSH username for device connections | `admin` |
| `BGP_PASSWORD` | SSH password for device connections | (prompts if not set) |

Example:
```bash
export BGP_USERNAME="netadmin"
export BGP_PASSWORD="$YOUR_CREDENTIAL"
```

## Usage

```bash
python main.py
```

### TUI Controls

| Key | Action |
|-----|--------|
| `Tab` | Navigate between elements |
| `Enter` | Select/activate button |
| `a` | Add new BGP session |
| `s` | Sync all sessions from devices |
| `r` | Refresh table from database |
| `d` | Delete selected session |
| `Ctrl+q` | Quit application |

### Adding a Session

1. Press `a` or click "Add Session"
2. Fill in the required fields:
   - **Neighbor IP**: BGP peer IP address (e.g., `10.1.1.1`)
   - **Remote AS**: Peer's AS number (e.g., `65001`)
   - **Device FQDN**: Hostname of the router where this session exists (e.g., `r1.core.example.com`)
3. Optional fields:
   - **Local AS**: Your AS number
   - **Local IP**: Your router's IP for this peering
   - **Description**: Friendly name for this session
4. Click "Save"

### Syncing Sessions

The "Sync All" function (`s` key) connects to each unique device in your session list and:

1. Auto-detects whether it's Cisco IOS-XR or Nokia SR OS
2. Retrieves current BGP neighbor information via SSH
3. Updates session state (Established, Active, Idle, etc.)
4. Updates local AS and local IP from device output

Sessions are grouped by device FQDN to minimize connections.

## Supported Devices

| Platform | Device Type | Detection Method |
|----------|-------------|------------------|
| Cisco IOS-XR | `cisco_xr` | Prompt contains `RP/` |
| Nokia SR OS | `nokia_sros` | Prompt contains `A:` |

## Data Storage

- **Database**: `bgp_sessions.db` (SQLite, created automatically)
- **Log file**: `bgp_manager.log` (rotating, 5MB max, 3 backups)

### Session Fields

| Field | Description |
|-------|-------------|
| Neighbor IP | BGP peer IP (unique identifier) |
| Remote AS | Peer's autonomous system number |
| Local AS | Your autonomous system number |
| Local IP | Your router's IP for this session |
| Description | User-provided description |
| Device FQDN | Router hostname where session exists |
| Type | `cisco_xr` or `nokia_sros` |
| Status | Up, Down, or Unknown |
| State | BGP state (Established, Active, Idle, etc.) |
| Last Updated | Timestamp of last sync |

## Troubleshooting

Check `bgp_manager.log` for detailed connection and parsing information. Common issues:

- **Connection timeouts**: Verify device is reachable and credentials are correct
- **Detection failures**: Ensure device prompt matches expected patterns
- **Parse errors**: Device output format may differ from expected; check log for raw output
