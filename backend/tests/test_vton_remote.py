import httpx
import pytest

from services import vton_service as vs

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-image-data"
BASELINE = b"baseline-bytes"
GARMENT = b"garment-bytes"


@pytest.fixture
def remote(monkeypatch):
    monkeypatch.setenv("VTON_PROVIDER", "remote")
    monkeypatch.setenv("VTON_REMOTE_URL", "https://gpu.example.com/")
    monkeypatch.setenv("VTON_REMOTE_KEY", "secret-key")
    sleeps = []
    monkeypatch.setattr(vs.time, "sleep", lambda s: sleeps.append(s))

    def install(handler):
        monkeypatch.setattr(
            vs, "_make_client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
        )

    return install, sleeps


def test_success_sends_expected_request(remote):
    install, _ = remote
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers["x-api-key"]
        seen["body"] = request.content
        return httpx.Response(200, content=PNG_BYTES)

    install(handler)
    out = vs.render_garment(BASELINE, GARMENT, "top")
    assert out == PNG_BYTES
    assert seen["url"] == "https://gpu.example.com/tryon"
    assert seen["key"] == "secret-key"
    assert b"upperbody" in seen["body"]
    assert BASELINE in seen["body"] and GARMENT in seen["body"]


@pytest.mark.parametrize(
    "category,expected",
    [("bottom", b"lowerbody"), ("dress", b"dress"), ("outerwear", b"upperbody")],
)
def test_category_mapping(remote, category, expected):
    install, _ = remote
    install(lambda r: httpx.Response(200, content=PNG_BYTES) if expected in r.content
            else httpx.Response(400, text="wrong category"))
    assert vs.render_garment(BASELINE, GARMENT, category) == PNG_BYTES


def test_unsupported_category_is_skipped_without_a_call(remote):
    install, _ = remote

    def handler(request):
        raise AssertionError("should not call the GPU server")

    install(handler)
    assert vs.render_garment(BASELINE, GARMENT, "footwear") == BASELINE


def test_retries_503_then_succeeds(remote):
    install, sleeps = remote
    responses = [httpx.Response(503), httpx.Response(503), httpx.Response(200, content=PNG_BYTES)]
    install(lambda r: responses.pop(0))
    assert vs.render_garment(BASELINE, GARMENT, "top") == PNG_BYTES
    assert sleeps == [1, 2]


def test_retries_connection_errors_then_gives_up(remote):
    install, sleeps = remote

    def handler(request):
        raise httpx.ConnectError("refused")

    install(handler)
    with pytest.raises(RuntimeError, match="after 3 attempts"):
        vs.render_garment(BASELINE, GARMENT, "top")
    assert sleeps == [1, 2]


def test_bad_api_key_fails_fast(remote):
    install, sleeps = remote
    install(lambda r: httpx.Response(401))
    with pytest.raises(RuntimeError, match="API key"):
        vs.render_garment(BASELINE, GARMENT, "top")
    assert sleeps == []


def test_server_error_message_is_surfaced(remote):
    install, _ = remote
    install(lambda r: httpx.Response(500, text="CUDA out of memory"))
    with pytest.raises(RuntimeError, match="CUDA out of memory"):
        vs.render_garment(BASELINE, GARMENT, "top")


def test_read_timeout_is_not_retried(remote):
    install, sleeps = remote

    def handler(request):
        raise httpx.ReadTimeout("slow")

    install(handler)
    with pytest.raises(RuntimeError, match="too long"):
        vs.render_garment(BASELINE, GARMENT, "top")
    assert sleeps == []


def test_non_png_response_is_rejected(remote):
    install, _ = remote
    install(lambda r: httpx.Response(200, content=b"<html>ngrok warning</html>"))
    with pytest.raises(RuntimeError, match="PNG"):
        vs.render_garment(BASELINE, GARMENT, "top")


def test_missing_url_is_a_clear_error(remote, monkeypatch):
    monkeypatch.setenv("VTON_REMOTE_URL", "")
    with pytest.raises(RuntimeError, match="VTON_REMOTE_URL"):
        vs.render_garment(BASELINE, GARMENT, "top")


def test_pose_maps_for_remote_provider(remote):
    assert vs.extract_pose_maps(b"x") == {"provider": "remote"}


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("VTON_PROVIDER", "banana")
    with pytest.raises(ValueError):
        vs.render_garment(BASELINE, GARMENT, "top")