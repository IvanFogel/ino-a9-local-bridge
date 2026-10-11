"""Tests for the authenticated INO-A9 app API client."""

from __future__ import annotations

import pytest
import pytest_asyncio
from aiohttp import web

from custom_components.ino_a9.api import InoA9Api, InoA9ApiError

pytestmark = pytest.mark.enable_socket


@pytest_asyncio.fixture
async def app_server(aiohttp_server, socket_enabled):
    calls: list[tuple[str, str, dict[str, str], object | None]] = []

    async def list_cameras(request: web.Request) -> web.Response:
        calls.append((request.method, request.path, dict(request.headers), None))
        return web.json_response({"cameras": [{"id": "front", "connected": True}]})

    async def camera_detail(request: web.Request) -> web.Response:
        calls.append((request.method, request.path, dict(request.headers), None))
        return web.json_response(
            {
                "id": "front",
                "connected": True,
                "media": {"has_frame": True, "has_audio": True},
                "controls": {
                    "led": {"value": False, "known": True, "source": "persisted"}
                },
            }
        )

    async def control(request: web.Request) -> web.Response:
        payload = await request.json()
        calls.append((request.method, request.path, dict(request.headers), payload))
        return web.json_response({"id": "front", "controls": {"led": {"value": True}}})

    async def reboot(request: web.Request) -> web.Response:
        calls.append((request.method, request.path, dict(request.headers), None))
        return web.json_response({"id": "front", "rebooting": True})

    async def snapshot(request: web.Request) -> web.Response:
        calls.append((request.method, request.path, dict(request.headers), None))
        return web.Response(body=b"jpeg", content_type="image/jpeg")

    async def fail(_request: web.Request) -> web.Response:
        return web.json_response({"secret": "must-not-leak"}, status=503)

    app = web.Application()
    app.router.add_get("/api/v1/cameras", list_cameras)
    app.router.add_get("/api/v1/cameras/front", camera_detail)
    app.router.add_put("/api/v1/cameras/front/controls/led", control)
    app.router.add_post("/api/v1/cameras/front/reboot", reboot)
    app.router.add_get("/front/snapshot.jpg", snapshot)
    app.router.add_get("/api/v1/cameras/missing", fail)
    server = await aiohttp_server(app)
    server.calls = calls
    return server


@pytest_asyncio.fixture
async def api(app_server):
    import aiohttp

    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with aiohttp.ClientSession(connector=connector) as session:
        yield InoA9Api(
            host="127.0.0.1",
            http_port=app_server.port,
            rtsp_port=8554,
            token="test-token",
            session=session,
        )


@pytest.mark.asyncio
async def test_client_sends_bearer_token_and_parses_camera_details(
    api, app_server
) -> None:
    cameras = await api.async_list_cameras()
    detail = await api.async_get_camera("front")

    assert cameras == [{"id": "front", "connected": True}]
    assert detail["controls"]["led"]["known"] is True
    assert app_server.calls[0][2]["Authorization"] == "Bearer test-token"


@pytest.mark.asyncio
async def test_client_sends_control_payload_and_reboot(api, app_server) -> None:
    await api.async_set_control("front", "led", {"value": True})
    await api.async_reboot("front")

    assert app_server.calls[0][3] == {"value": True}
    assert app_server.calls[1][1] == "/api/v1/cameras/front/reboot"


@pytest.mark.asyncio
async def test_client_fetches_authenticated_snapshot(api, app_server) -> None:
    assert await api.async_get_snapshot("front") == b"jpeg"
    assert app_server.calls[0][1] == "/front/snapshot.jpg"


@pytest.mark.asyncio
async def test_client_maps_http_error_without_exposing_response_body(api) -> None:
    with pytest.raises(InoA9ApiError) as error:
        await api.async_get_camera("missing")

    assert error.value.status == 503
    assert "must-not-leak" not in str(error.value)
