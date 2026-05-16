from unittest.mock import MagicMock, patch

from libs.forwarder import SiftSDKForwarder


def test_sift_client_constructed_once(monkeypatch):
    monkeypatch.setenv("SIFT_API_KEY", "test-key")
    monkeypatch.setenv("SIFT_GRPC_URL", "grpc-api.example.com")
    monkeypatch.setenv("SIFT_REST_URL", "https://api.example.com")
    monkeypatch.setenv("SIFT_SDK_PREFER", "client")

    mock_client = MagicMock()
    mock_client.async_.ingestion.create_ingestion_config_streaming_client.return_value = MagicMock(
        __aenter__=lambda self: self,
        __aexit__=lambda *a: None,
        send=MagicMock(),
        finish=MagicMock(),
    )

    with patch("sift_client.SiftClient", return_value=mock_client) as ctor, patch(
        "libs.forwarder._run_coroutine_sync", side_effect=lambda coro: None
    ):
        fwd = SiftSDKForwarder()
        points = [{"ts": "2026-05-15T12:00:00+00:00", "channel": "ecowitt.temp", "value": 1.0}]
        fwd.send(asset="asset", day="2026-05-15", points=points)
        fwd.send(asset="asset", day="2026-05-15", points=points)

    assert ctor.call_count == 1


def test_sift_client_bad_signature_sticks_to_py(monkeypatch):
    monkeypatch.setenv("SIFT_API_KEY", "test-key")
    monkeypatch.setenv("SIFT_GRPC_URL", "grpc-api.example.com")
    monkeypatch.setenv("SIFT_REST_URL", "https://api.example.com")
    monkeypatch.setenv("SIFT_SDK_PREFER", "client")

    fwd = SiftSDKForwarder()
    points = [{"ts": "2026-05-15T12:00:00+00:00", "channel": "ecowitt.temp", "value": 1.0}]
    run_calls = []

    def mock_run(_coro):
        run_calls.append(1)
        raise RuntimeError("invalid peer certificate: BadSignature")

    channel_cm = MagicMock()
    channel_cm.__enter__ = lambda self: MagicMock()
    channel_cm.__exit__ = lambda *args: None

    with patch("libs.forwarder._run_coroutine_sync", side_effect=mock_run), patch(
        "sift_py.grpc.transport.use_sift_channel", return_value=channel_cm
    ), patch("sift_py.ingestion.service.IngestionService") as ingestion_cls:
        ingestion_cls.return_value = MagicMock()
        fwd.send(asset="asset", day="2026-05-15", points=points)
        fwd.send(asset="asset", day="2026-05-15", points=points)

    assert len(run_calls) == 1
    assert fwd._use_sift_py_only is True
    assert ingestion_cls.call_count == 2
