from libs.forwarder import _normalize_sift_grpc_url


def test_normalize_strips_443_port_without_scheme():
    assert _normalize_sift_grpc_url("grpc-api.siftstack.com:443") == "grpc-api.siftstack.com"


def test_normalize_passes_through_https_urls():
    assert _normalize_sift_grpc_url("https://grpc-api.siftstack.com") == "grpc-api.siftstack.com"

