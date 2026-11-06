from grill_gate_monitoring.services.frame_source import LiveCameraFrameSource


class Subscription:
    closed = False

    def __init__(self):
        self.packet = object()
        self.was_closed = False

    def get(self, timeout=None):
        return self.packet

    def close(self):
        self.was_closed = True
        self.closed = True


def test_live_frame_source_adapts_existing_subscription_lifecycle():
    subscription = Subscription()
    source = LiveCameraFrameSource(subscription)
    assert source.get(timeout=0.1) is subscription.packet
    assert source.closed is False
    source.close()
    assert source.closed is True
    assert subscription.was_closed is True
