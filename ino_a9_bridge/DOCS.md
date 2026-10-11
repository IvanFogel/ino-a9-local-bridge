# INO-A9 Local Bridge

This Home Assistant app runs the project's existing local Python bridge and
go2rtc in one supervised image. It is for INO-A9-V2.8 / Linklemo cameras using
the local PPRPC service on TCP 20190; it does not give cameras Internet access.

## Configuration

Add one item to `cameras` for every camera. `name` is a stable ID used in URLs
and must be unique and match `A-Z`, `a-z`, `0-9`, `_`, or `-`. The app refuses
an empty list, duplicate IDs, invalid ports, and empty required values even if
the Supervisor schema is bypassed.

```yaml
log_level: info
cameras:
  - name: front_door
    host: 192.0.2.10
    port: 20190
    bootstrap_prefix: LLM_
    user: local-user
    lan_password: replace-this-private-value
```

The Supervisor UI treats the three credential fields as passwords. Do not put
this configuration, generated files, or app logs in source control.

## Runtime and streams

The app generates private files below `/data` at startup:

- `bridge.json` contains the bridge's credentials and is mode `0600`.
- `go2rtc.yaml` contains deterministic `ino_a9_<name>` stream definitions.
- `control_token` is generated once and retained mode `0600` for the control
  API.
- `control_state.json` retains non-secret, per-camera last-command state.

The Python bridge listens on internal port 8080. go2rtc's API is loopback-only
on 1984. RTSP listens on internal port 8554 and is published as host port 8554;
this is the only host port published by the app. The custom integration
discovers the app through Supervisor and consumes the private discovery token
when it calls this API.

The PPRPC reader sends an encrypted command-107 keepalive every 500 ms. Once an
AV packet has arrived, the request includes protobuf field 4 with the latest AV
sequence, acknowledging media consumed by the bridge and allowing the camera to
advance its send window. The two-second complete-frame watchdog remains a
fallback for a genuinely stalled session.

## Control API

`GET /health` is an unauthenticated health check. Every `/api/v1/...` request
requires `Authorization: Bearer <control_token>` and returns JSON only. The
The integration uses `GET /api/v1/cameras`, `GET /api/v1/cameras/<id>`,
`PUT /api/v1/cameras/<id>/controls/<control>`, and
`POST /api/v1/cameras/<id>/reboot`.

Controls are `led` (`{"value": true}`), `night_vision`, `flip`,
`video_quality`, and `motion` (each `{"value": "..."}`), and `intrusion`
(`{"enabled": true, "schedule": {"days": [0], "start": "08:00", "end": "18:00"}}`).
Days use Home Assistant's weekday numbering, Monday `0` through Sunday `6`;
schedules have minute precision and cannot cross midnight. Camera detail responses
label values as `readback`,
`persisted`, or `unknown`; night vision and flip use camera readback whenever
the session is connected. API errors are JSON and use 400, 401, 404, 502, 503,
or 504 without returning credentials or camera protocol data.

For a configured `front_door`, the stable audio-capable RTSP stream is:

```text
rtsp://<discovered-app-host>:8554/ino_a9_front_door
```

For a different Home Assistant instance on the same LAN, use the Home
Assistant OS host address instead of the internal app hostname, for example:

```text
rtsp://192.168.1.82:8554/ino_a9_front_door
```

Keep port 8554 restricted to the trusted LAN because the RTSP endpoint has no
authentication.

## Reproducible image choices

The Home Assistant base is pinned to `ghcr.io/home-assistant/base:3.23` and
digest `sha256:1c7a8c7321c15cdc327c264232a76e6fbfdaf7f2b1734a8d8da6fcc994f66015`,
the same pinned base line used by the current official app example. The image
copies the multi-architecture upstream `alexxit/go2rtc:1.9.14` at digest
`sha256:675c318b23c06fd862a61d262240c9a63436b4050d177ffc68a32710d9e05bae`, the
release already validated by this project, and installs `cryptography==50.0.1`
from `requirements.txt`. The selected base and go2rtc image both support `amd64`
and `aarch64`; FFmpeg is installed in the final Alpine image for go2rtc's
generated MJPEG/G.711 transcoding commands.

## Local development

Install this repository as a local app repository, or copy `ino_a9_bridge/` to
`/addons/ino_a9_bridge` on Home Assistant OS. The Supervisor builds the app
directory itself; no second copy of the Python bridge exists in this repository.
For a host-architecture smoke build:

```bash
docker build -t local/ino-a9-bridge ino_a9_bridge
```
