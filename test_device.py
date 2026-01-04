# test_device.py
import pytest
from unittest.mock import MagicMock, patch, call
from contextlib import contextmanager

from device import detect_device_type, sync_cisco_xr, sync_nokia_sros, _update_db_neighbors, connect_with_retry


class TestConnectWithRetry:
    """Tests for connect_with_retry function."""

    @patch("device.ConnectHandler")
    def test_successful_first_attempt(self, mock_connect_handler):
        """Should return connection on first successful attempt."""
        mock_conn = MagicMock()
        mock_connect_handler.return_value = mock_conn

        result = connect_with_retry({"host": "10.0.0.1", "device_type": "cisco_xr"})

        assert result == mock_conn
        assert mock_connect_handler.call_count == 1

    @patch("device.time.sleep")
    @patch("device.ConnectHandler")
    def test_retry_on_failure(self, mock_connect_handler, mock_sleep):
        """Should retry on connection failure."""
        mock_conn = MagicMock()
        mock_connect_handler.side_effect = [
            Exception("Connection refused"),
            Exception("Timeout"),
            mock_conn,
        ]

        result = connect_with_retry({"host": "10.0.0.1", "device_type": "cisco_xr"}, retries=3, delay=1)

        assert result == mock_conn
        assert mock_connect_handler.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("device.time.sleep")
    @patch("device.ConnectHandler")
    def test_raises_after_all_retries_exhausted(self, mock_connect_handler, mock_sleep):
        """Should raise exception after all retries fail."""
        mock_connect_handler.side_effect = Exception("Connection failed")

        with pytest.raises(Exception, match="Connection failed"):
            connect_with_retry({"host": "10.0.0.1", "device_type": "cisco_xr"}, retries=3, delay=1)

        assert mock_connect_handler.call_count == 3


class TestDetectDeviceType:
    """Tests for detect_device_type function."""

    @patch("device.connect_with_retry")
    def test_detect_cisco_xr(self, mock_connect):
        """Should detect Cisco IOS-XR when prompt contains RP/."""
        mock_conn = MagicMock()
        mock_conn.find_prompt.return_value = "RP/0/RSP0/CPU0:router#"
        mock_connect.return_value = mock_conn

        result = detect_device_type("10.0.0.1", "admin", "password")

        assert result == "cisco_xr"
        mock_conn.disconnect.assert_called_once()

    @patch("device.connect_with_retry")
    def test_detect_nokia_sros(self, mock_connect):
        """Should detect Nokia SR OS when prompt contains A:."""
        mock_conn = MagicMock()
        # First call (cisco_xr) returns prompt without RP/
        # Second call (nokia_sros) returns prompt with A:
        mock_conn.find_prompt.side_effect = ["router#", "A:router#"]
        mock_connect.return_value = mock_conn

        result = detect_device_type("10.0.0.1", "admin", "password")

        assert result == "nokia_sros"

    @patch("device.connect_with_retry")
    def test_detect_unknown_device_raises(self, mock_connect):
        """Should raise ValueError when device type cannot be detected."""
        mock_conn = MagicMock()
        mock_conn.find_prompt.return_value = "unknown_prompt>"
        mock_connect.return_value = mock_conn

        with pytest.raises(ValueError, match="Could not detect device type"):
            detect_device_type("10.0.0.1", "admin", "password")

    @patch("device.connect_with_retry")
    def test_detect_connection_failure(self, mock_connect):
        """Should raise ValueError when all connection attempts fail."""
        mock_connect.side_effect = Exception("Connection failed")

        with pytest.raises(ValueError, match="Could not detect device type"):
            detect_device_type("10.0.0.1", "admin", "password")


class TestSyncCiscoXR:
    """Tests for sync_cisco_xr function."""

    @patch("device.connect_with_retry")
    def test_sync_parses_bgp_summary(self, mock_connect):
        """Should parse BGP summary output and update database."""
        # Mock the summary output
        summary_output = """
10.1.1.1          4 65001      123  45  67  89  12  34  Established
10.1.1.2          4 65002      456  78  90  12  34  56  Active
"""
        # Mock the detail output for each neighbor
        detail_output_1 = """
BGP neighbor is 10.1.1.1
  Local AS:  65000
  Local host: 192.168.1.1
"""
        detail_output_2 = """
BGP neighbor is 10.1.1.2
  Local AS:  65000
  Local host: 192.168.1.2
"""
        mock_conn = MagicMock()
        mock_conn.send_command.side_effect = [
            summary_output,
            detail_output_1,
            detail_output_2,
        ]
        mock_connect.return_value = mock_conn

        # Mock database
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        @contextmanager
        def mock_db_factory():
            yield mock_db

        sync_cisco_xr("router1.example.com", "admin", "password", mock_db_factory)

        # Verify sessions were added
        assert mock_db.add.call_count == 2
        mock_db.commit.assert_called_once()

    @patch("device.connect_with_retry")
    def test_sync_updates_existing_session(self, mock_connect):
        """Should update existing session if neighbor_ip matches."""
        summary_output = "10.1.1.1          4 65001      123  45  67  89  12  34  Established"
        detail_output = "Local AS:  65000\nLocal host: 192.168.1.1"

        mock_conn = MagicMock()
        mock_conn.send_command.side_effect = [summary_output, detail_output]
        mock_connect.return_value = mock_conn

        # Mock existing session
        existing_session = MagicMock()
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = existing_session

        @contextmanager
        def mock_db_factory():
            yield mock_db

        sync_cisco_xr("router1.example.com", "admin", "password", mock_db_factory)

        # Should update existing session, not add new
        assert existing_session.remote_as == 65001
        assert existing_session.status == "Up"
        assert existing_session.session_state == "Established"
        mock_db.add.assert_not_called()

    @patch("device.connect_with_retry")
    def test_sync_handles_connection_error(self, mock_connect):
        """Should raise exception on connection failure."""
        mock_connect.side_effect = Exception("Connection refused")

        @contextmanager
        def mock_db_factory():
            yield MagicMock()

        with pytest.raises(Exception, match="Connection refused"):
            sync_cisco_xr("router1.example.com", "admin", "password", mock_db_factory)


class TestSyncNokiaSROS:
    """Tests for sync_nokia_sros function."""

    @patch("device.connect_with_retry")
    def test_sync_parses_bgp_neighbor_output(self, mock_connect):
        """Should parse Nokia SR OS BGP neighbor output."""
        nokia_output = """
Peer: 10.2.2.1
  Remote AS     : 65100
  State         : Established
  Local AS      : 65000
  Local Address : 192.168.2.1
Peer: 10.2.2.2
  Remote AS     : 65200
  State         : Active
  Local AS      : 65000
  Local Address : 192.168.2.2
"""
        mock_conn = MagicMock()
        mock_conn.send_command.return_value = nokia_output
        mock_connect.return_value = mock_conn

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        @contextmanager
        def mock_db_factory():
            yield mock_db

        sync_nokia_sros("router2.example.com", "admin", "password", mock_db_factory)

        assert mock_db.add.call_count == 2
        mock_db.commit.assert_called_once()

    @patch("device.connect_with_retry")
    def test_sync_handles_empty_output(self, mock_connect):
        """Should handle empty output gracefully."""
        mock_conn = MagicMock()
        mock_conn.send_command.return_value = ""
        mock_connect.return_value = mock_conn

        mock_db = MagicMock()

        @contextmanager
        def mock_db_factory():
            yield mock_db

        sync_nokia_sros("router2.example.com", "admin", "password", mock_db_factory)

        mock_db.add.assert_not_called()
        mock_db.commit.assert_called_once()


class TestUpdateDbNeighbors:
    """Tests for _update_db_neighbors helper function."""

    def test_updates_existing_session(self):
        """Should update fields on existing session."""
        existing_session = MagicMock()
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = existing_session

        neighbors = {
            "10.1.1.1": (65001, "Established", 65000, "192.168.1.1"),
        }

        _update_db_neighbors("router.example.com", "cisco_xr", neighbors, mock_db)

        assert existing_session.remote_as == 65001
        assert existing_session.local_as == 65000
        assert existing_session.local_ip == "192.168.1.1"
        assert existing_session.device_fqdn == "router.example.com"
        assert existing_session.status == "Up"
        assert existing_session.session_state == "Established"
        mock_db.commit.assert_called_once()

    def test_creates_new_session_if_not_exists(self):
        """Should create new session when neighbor_ip not found."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        neighbors = {
            "10.1.1.1": (65001, "Established", 65000, "192.168.1.1"),
        }

        _update_db_neighbors("router.example.com", "nokia_sros", neighbors, mock_db)

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_handles_multiple_neighbors(self):
        """Should process multiple neighbors correctly."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        neighbors = {
            "10.1.1.1": (65001, "Established", 65000, "192.168.1.1"),
            "10.1.1.2": (65002, "Active", 65000, "192.168.1.2"),
            "10.1.1.3": (65003, "Idle", 65000, "192.168.1.3"),
        }

        _update_db_neighbors("router.example.com", "cisco_xr", neighbors, mock_db)

        assert mock_db.add.call_count == 3
        mock_db.commit.assert_called_once()
