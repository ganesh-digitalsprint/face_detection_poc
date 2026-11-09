import logging

from app.core.logging import _ConsoleLevelFilter


def test_console_filter_allows_grill_gate_debug_without_lowering_vault_level():
    level_filter = _ConsoleLevelFilter(logging.INFO, logging.DEBUG)

    assert level_filter.filter(logging.LogRecord(
        "grill_gate_monitoring.services.gate_state_detector", logging.DEBUG,
        __file__, 1, "frame detail", (), None))
    assert not level_filter.filter(logging.LogRecord(
        "app.services.vault_room_manager", logging.DEBUG,
        __file__, 1, "vault detail", (), None))
    assert level_filter.filter(logging.LogRecord(
        "app.services.vault_room_manager", logging.INFO,
        __file__, 1, "vault status", (), None))
