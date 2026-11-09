import logging

from grill_gate_monitoring.services.diagnostics import log_diagnostic


def test_diagnostic_prefix_and_frame_context_are_structured(caplog):
    logger = logging.getLogger("grill_gate_monitoring.services.gate_state_detector")
    with caplog.at_level(logging.DEBUG, logger=logger.name):
        log_diagnostic(logger, "gate_measurement", level=logging.DEBUG, category="MEASUREMENT",
                       video_job_id="job-1", frame_index=12, video_source_timestamp=1.2,
                       left_endpoint_px=84.0, right_endpoint_px=None, confidence=0.5)

    assert "[GRILL_GATE][MEASUREMENT]" in caplog.text
    assert '"video_job_id":"job-1"' in caplog.text
    assert '"frame_index":12' in caplog.text
    assert '"video_source_timestamp":1.2' in caplog.text
