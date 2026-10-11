# INO A9 local video bridge research

Local-only research and bridge tooling for the inexpensive Wi-Fi camera marked
`INO-A9-V2.8` and sold for use with the Linklemo Android app.

The immediate goal is to expose the camera to Home Assistant without allowing
the camera to reach the Internet. This model speaks XC Things' proprietary
PPRPC protocol on TCP port `20190`; it is **not** the older Naxclow/V720 model
that speaks its unrelated protocol on port `6123`.

> [!NOTE]
> The direct LAN client, HTTP MJPEG/G.711 bridge, and audio-capable RTSP path are
> live-tested on the physical cameras. Three units have been provisioned locally
> without a Linklemo account; each still requires a one-time, isolated setup
> process.

## AI-assisted development

This project was created largely with OpenAI Codex using **GPT-5.6-Sol**.
Codex performed most of the research synthesis, protocol implementation,
testing, deployment automation, and documentation. **IvanFogel** supplied and
owned the hardware, authorized the testing, performed the required physical
actions, selected the operational and security constraints, and made the final
publication decisions.

## Confirmed on the test unit

- PCB marking: `INO-A9-V2.8`
- Factory access-point prefix: `LLM_`
- Linklemo package: `com.xcthings.fchan`
- LAN service: PPRPC over TCP `20190`
- Camera remains locally reachable while an OPNsense rule blocks all routed
  traffic from it to any destination
- Observed blocked cloud attempts included TCP/UDP port `8000`, TCP `465`, and
  UDP `80`
- Linklemo's native SDK has an explicit LAN-only connection path and requests
  live video with `videoPlay(0, 0, 0)`
- The independent client authenticates, answers time sync, starts video, and
  receives standard 640×480 MJPEG
- The bridge requests the SDK's highest QoS on every connection. The tested
  camera clamps all higher modes to its actual maximum: QoS 5, 640×480 MJPEG
  at 10 FPS
- The microphone is live-validated: command `2614` starts an unencrypted local
  G.711 A-law stream at 8 kHz, reported as 16-bit mono by the camera
- The bridge maintains the bidirectional command-107 keepalive every 500 ms and
  acknowledges the latest received AV sequence, which keeps the camera's media
  send window advancing; a separate two-second complete-frame watchdog remains
  as a recovery fallback
- The HTTP bridge exposes snapshots, full-rate and one-frame-per-second MJPEG,
  and raw G.711 A-law microphone audio; the setup laptop and Linklemo are not
  needed at runtime
- An on-demand go2rtc sidecar combines H.264 video and Opus audio for Home
  Assistant while keeping overview cards on the native MJPEG path
- Three cameras, Home Assistant's native MJPEG integration, audio-capable
  opened views, and a Cameras dashboard were validated end to end
- On two additional units, the Wi-Fi station MAC was the setup AP BSSID with
  the low bit of the final octet toggled; the DHCP lease must still be verified

## Repository map

- [`docs/provisioning.md`](docs/provisioning.md) — repeatable isolated setup
  procedure for additional cameras
- [`docs/lab-notebook.md`](docs/lab-notebook.md) — redacted record of the work
- [`docs/network-isolation.md`](docs/network-isolation.md) — DHCP and firewall
  design for a camera subnet
- [`docs/bridge.md`](docs/bridge.md) — deployment and Home Assistant setup
- [`docs/protocol.md`](docs/protocol.md) — PPRPC framing and SDK findings
- [`go2rtc.example.yaml`](go2rtc.example.yaml) — audio-capable RTSP restreams
- [`ino_a9_bridge/`](ino_a9_bridge/) — Home Assistant app build context and the
  single clean-room parser, camera client, and HTTP bridge implementation
- [`custom_components/ino_a9/`](custom_components/ino_a9/) — HACS-ready Home
  Assistant integration discovered from the app
- [`hacs.json`](hacs.json) — HACS repository metadata
- `scripts/probe_media.py` — header-only live media-format diagnostic
- `ino_a9_bridge/tests/` — tests using synthetic packets and frames only

No APKs, firmware dumps, packet captures, Wi-Fi keys, account passwords, app
secrets, cookies, or camera video are stored here.

## Home Assistant app and integration

The repository contains both sides of the local deployment:

1. Install the `INO-A9 Local Bridge` app from this repository's app catalog and
   configure one `cameras` item per physical camera. Credentials stay in the
   app's Supervisor-managed options and its private `/data` files.
2. Install the `INO-A9 Local Bridge` integration through HACS, or copy
   `custom_components/ino_a9` into the Home Assistant configuration directory.
3. The app publishes Supervisor discovery. Home Assistant creates one config
   entry and one device per configured camera, with a native camera entity,
   audio-capable RTSP stream, LED and intrusion switches, control selects, and
   a reboot button.

The integration also exposes `ino_a9.set_intrusion_schedule` for a targeted
camera device. Keep the camera's Internet-deny rule in place; the app only
needs local access to TCP port 20190 on each camera.

The app currently builds from source during installation. The app and integration
use independent release channels. App images are
published from `app-v<version>` tags, while HACS tracks only published GitHub
Releases named `v<version>` for the integration.

## Development

Requires Python 3.11 or newer.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
pytest
```

Inspect a PPRPC packet supplied as hexadecimal:

```bash
wificam-pprpc decode 680881020003000100
```

Run the bridge with a private configuration copied from `config.example.json`:

```bash
wificam-bridge --config /private/path/camera.json
```

For a configured camera named `camera1`, the default endpoints are:

```text
http://bridge-host:8080/camera1/snapshot.jpg
http://bridge-host:8080/camera1/stream.mjpeg
http://bridge-host:8080/camera1/preview.mjpeg
http://bridge-host:8080/camera1/audio.alaw
```

## Similar-looking cameras

The [`intx82/a9-v720`](https://github.com/intx82/a9-v720) project is useful for
Naxclow V720 units. Its documented camera uses `192.168.169.1:6123` and streams
MJPEG. The present `LLM_`/Linklemo camera instead exposes PPRPC at port `20190`,
so the V720 script is not wire-compatible despite similar housings and PCBs.

## Sources and attribution

Protocol behavior was compared against the archived Apache-2.0 PPRPC Go module
(`github.com/pprpc/core`, revision `5592f694d0e7`) and FuseTim's MIT-licensed
[`insecurity-camera-tools`](https://github.com/fusetim/insecurity-camera-tools).
See [`NOTICE`](NOTICE) and [`docs/protocol.md`](docs/protocol.md).

## License

This project is released under the [Zero-Clause BSD license](LICENSE): use,
copy, modify, or distribute it for any purpose, with or without fee. Attribution
is appreciated but not required.

Only analyze devices and networks you own or are authorized to test.
