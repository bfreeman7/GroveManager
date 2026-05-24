from unittest.mock import MagicMock, patch

from sift_client.sift_types.channel import ChannelDataType

from conftest import close_coroutine
from libs.forwarder import SiftSDKForwarder, flow_name_from_channels


def _sift_env(monkeypatch):
    monkeypatch.setenv("SIFT_API_KEY", "test-key")
    monkeypatch.setenv("SIFT_GRPC_URL", "grpc-api.example.com")
    monkeypatch.setenv("SIFT_REST_URL", "https://api.example.com")
    monkeypatch.setenv("SIFT_SDK_PREFER", "client")


def test_sift_client_constructed_once(monkeypatch):
    _sift_env(monkeypatch)

    mock_client = MagicMock()
    mock_client.async_.ingestion.create_ingestion_config_streaming_client.return_value = MagicMock(
        __aenter__=lambda self: self,
        __aexit__=lambda *a: None,
        send=MagicMock(),
        finish=MagicMock(),
    )

    with patch("sift_client.SiftClient", return_value=mock_client) as ctor, patch(
        "libs.forwarder._run_coroutine_sync", side_effect=close_coroutine
    ):
        fwd = SiftSDKForwarder()
        points = [{"ts": "2026-05-15T12:00:00+00:00", "channel": "ecowitt.temp", "value": 1.0}]
        fwd.send(asset="asset", day="2026-05-15", points=points)
        fwd.send(asset="asset", day="2026-05-15", points=points)

    assert ctor.call_count == 1


def test_sift_client_bad_signature_sticks_to_py(monkeypatch):
    _sift_env(monkeypatch)

    fwd = SiftSDKForwarder()
    points = [{"ts": "2026-05-15T12:00:00+00:00", "channel": "ecowitt.temp", "value": 1.0}]
    run_calls = []

    def mock_run(coro):
        run_calls.append(1)
        close_coroutine(coro)
        raise RuntimeError("invalid peer certificate: BadSignature")

    channel_cm = MagicMock()
    channel_cm.__enter__ = lambda self: MagicMock()
    channel_cm.__exit__ = lambda *args: None

    with patch("libs.forwarder._run_coroutine_sync", side_effect=mock_run), patch(
        "sift_py.grpc.transport.use_sift_channel", return_value=channel_cm
    ), patch("sift_py.ingestion.service.IngestionService") as ingestion_cls, patch(
        "libs.forwarder._ensure_sift_py_flow_channels"
    ), patch(
        "libs.forwarder._resolve_sift_flow_name",
        side_effect=lambda _ch, _cfg, channels, **kw: flow_name_from_channels(channels),
    ), patch(
        "libs.forwarder._flow_channels_in_order",
        return_value=[],
    ):
        ingestion_cls.return_value = MagicMock()
        fwd.send(asset="asset", day="2026-05-15", points=points)
        fwd.send(asset="asset", day="2026-05-15", points=points)

    assert len(run_calls) == 1
    assert fwd._use_sift_py_only is True
    assert ingestion_cls.call_count == 2


def test_sift_client_registers_irrigation_as_bool(monkeypatch):
    _sift_env(monkeypatch)

    from sift_client.sift_types.ingestion import FlowConfig as RealFlowConfig

    captured_flows = []

    def capture_flow_config(**kwargs):
        captured_flows.append(RealFlowConfig(**kwargs))
        return RealFlowConfig(**kwargs)

    mock_client = MagicMock()
    mock_client.async_.ingestion.create_ingestion_config_streaming_client.return_value = MagicMock(
        __aenter__=lambda self: self,
        __aexit__=lambda *a: None,
        send=MagicMock(),
        finish=MagicMock(),
    )

    with patch("sift_client.SiftClient", return_value=mock_client), patch(
        "libs.forwarder._run_coroutine_sync", side_effect=close_coroutine
    ), patch("sift_client.sift_types.ingestion.FlowConfig", side_effect=capture_flow_config):
        fwd = SiftSDKForwarder()
        points = [
            {"ts": "2026-05-15T12:00:00+00:00", "channel": "irrigation_state.station01", "value": 1.0},
            {"ts": "2026-05-15T12:00:00+00:00", "channel": "ecowitt.tempf", "value": 70.0},
        ]
        fwd.send(asset="asset", day="2026-05-15", points=points)

    irrigation_flow = flow_name_from_channels(["irrigation_state.station01"])
    ecowitt_flow = flow_name_from_channels(["ecowitt.tempf"])
    by_flow = {flow.name: {ch.name: ch.data_type for ch in flow.channels} for flow in captured_flows}
    assert by_flow[irrigation_flow]["irrigation_state.station01"] == ChannelDataType.BOOL
    assert by_flow[ecowitt_flow]["ecowitt.tempf"] == ChannelDataType.DOUBLE


def test_sift_client_uses_stable_client_key(monkeypatch):
    _sift_env(monkeypatch)
    monkeypatch.setenv("SIFT_INGESTION_CLIENT_KEY", "orchard-edge-v1.ch13")

    from sift_client.sift_types.ingestion import IngestionConfigCreate as RealCreate

    captured = {}

    def capture_create(**kwargs):
        captured["client_key"] = kwargs.get("client_key")
        return RealCreate(**kwargs)

    mock_client = MagicMock()
    mock_client.async_.ingestion.create_ingestion_config_streaming_client.return_value = MagicMock(
        __aenter__=lambda self: self,
        __aexit__=lambda *a: None,
        send=MagicMock(),
        finish=MagicMock(),
    )

    with patch("sift_client.SiftClient", return_value=mock_client), patch(
        "libs.forwarder._run_coroutine_sync", side_effect=close_coroutine
    ), patch("sift_client.sift_types.ingestion.IngestionConfigCreate", side_effect=capture_create):
        fwd = SiftSDKForwarder()
        points = [{"ts": "2026-05-15T12:00:00+00:00", "channel": "irrigation_state.station01", "value": 1.0}]
        fwd.send(asset="asset", day="2026-05-15", points=points)

    assert captured["client_key"] == "orchard-edge-v1.ch13"


def test_sift_py_uses_lazy_flow_creation(monkeypatch):
    monkeypatch.setenv("SIFT_API_KEY", "test-key")
    monkeypatch.setenv("SIFT_GRPC_URL", "grpc-api.example.com")
    monkeypatch.setenv("SIFT_SDK_PREFER", "py")

    channel_cm = MagicMock()
    channel_cm.__enter__ = lambda self: MagicMock()
    channel_cm.__exit__ = lambda *args: None

    mock_ingestion = MagicMock()
    mock_ingestion.ingestion_config.ingestion_config_id = "cfg-1"

    with patch("sift_py.grpc.transport.use_sift_channel", return_value=channel_cm), patch(
        "sift_py.ingestion.service.IngestionService", return_value=mock_ingestion
    ) as ingestion_cls, patch("libs.forwarder._ensure_sift_py_flow_channels") as ensure, patch(
        "libs.forwarder._resolve_sift_flow_name",
        side_effect=lambda _ch, _cfg, channels, **kw: flow_name_from_channels(channels),
    ), patch(
        "libs.forwarder._flow_channels_in_order",
        return_value=[],
    ):
        fwd = SiftSDKForwarder()
        points = [{"ts": "2026-05-15T12:00:00+00:00", "channel": "irrigation_state.station01", "value": 1.0}]
        fwd.send(asset="asset", day="2026-05-15", points=points)

    _, kwargs = ingestion_cls.call_args
    assert kwargs.get("force_lazy_flow_creation") is True
    ensure.assert_called_once()
    mock_ingestion.ingest_flows.assert_called_once()
