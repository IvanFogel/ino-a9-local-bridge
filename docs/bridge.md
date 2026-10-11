# Local MJPEG bridge

The bridge connects directly to each camera over PPRPC, performs LAN
authentication, answers the initial time-sync exchange, starts MJPEG video,
reassembles the network fragments, and decrypts only the encrypted head of each
frame. Linklemo and the setup laptop are not needed while the bridge is running.

## Home Assistant app deployment

The supported Home Assistant deployment is the `INO-A9 Local Bridge` app under
[`ino_a9_bridge/`](../ino_a9_bridge/), paired with the HACS-ready integration
under [`custom_components/ino_a9/`](../custom_components/ino_a9/).

Install the app from this repository's Home Assistant app repository and add
one camera object per physical camera. The app keeps camera credentials in its
Supervisor-managed options, generates the private bridge/go2rtc configuration,
and publishes its internal HTTP/RTSP endpoints through Supervisor discovery.
After the integration is installed, discovery creates one config entry and one
device per camera. The native entities are:

- camera with JPEG snapshots and an audio-capable RTSP source;
- status-LED and intrusion-detection switches;
- selects for night vision, image orientation, video quality, and motion
  sensitivity;
- a camera reboot button.

The `ino_a9.set_intrusion_schedule` service accepts a device target, enabled
state, sorted weekdays (Monday `0` through Sunday `6`), and a non-crossing
minute-precision time interval. Keep the camera Internet block in place; the
app needs only local TCP access to camera port `20190`.

To install the app, add this repository URL under **Settings → Add-ons
→ Add-on store → ⋮ → Repositories**, install `INO-A9 Local Bridge`, and configure
the app there. The app currently builds from source during installation, until
the first upstream app image is published and enabled in the app manifest. The
app release channel uses tags named `app-v<version>`; the workflow publishes the
matching `amd64` and `aarch64` images to the repository owner's GHCR namespace.

Install the `INO-A9 Local Bridge` integration from HACS by adding this repository
as a custom integration repository, or copy `custom_components/ino_a9/` into the
Home Assistant `custom_components` directory. The integration release channel
uses published GitHub Releases named `v<version>`, which are the releases HACS
tracks. Do not publish an `app-v*` tag as a GitHub Release, because HACS would
interpret it as a new integration version.
For local app development, add the repository as a local app source and rebuild
the app from that source:

```bash
ha apps rebuild local_ino_a9_bridge
```

## Private configuration

Copy `config.example.json` outside the repository and fill in the values
recovered during an authorized pairing capture. Never commit the completed
file. Restrict it to the service account:

```bash
install -m 600 config.example.json /private/path/camera.json
```

The three private fields are:

- `bootstrap_prefix`: control-plane prefix from the matching SDK build;
- `user`: LAN-authorized user identifier stored by the camera;
- `lan_password`: stable local-salt credential sent in `LanAuth.Req`.

Add another object to `cameras` for each additional camera. Each camera needs a
unique `name` and address. Do not put Wi-Fi credentials in this file; the bridge
does not need them.

## Run directly

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install .
wificam-bridge --config /private/path/camera.json
```

The sample binds only to loopback. Set `listen_host` to `0.0.0.0` when a
trusted LAN client or Home Assistant must reach it.

## Run with Docker Compose

Place the application in an `app` directory and the private file at
`../config/camera.json`, then run:

```bash
docker compose -f compose.example.yaml up -d --build
```

The example container runs without Linux capabilities, has a read-only root
filesystem, and mounts the private configuration read-only.

## Run as a TrueNAS Custom App

Build the image on the TrueNAS host, then create a **Custom App** named
`ino-a9-local-bridge` with the equivalent Compose configuration. The tested
managed app uses:

```yaml
services:
  bridge:
    image: local/ino-a9-local-bridge:0.3.1
    pull_policy: never
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - /mnt/pool/wificam/config/camera.json:/run/wificam/camera.json:ro
    read_only: true
    tmpfs:
      - /tmp:size=16m,mode=1777
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL

  go2rtc:
    image: alexxit/go2rtc:1.9.14
    pull_policy: never
    restart: unless-stopped
    depends_on:
      - bridge
    ports:
      - "192.168.1.38:8554:8554"
    volumes:
      - /mnt/pool/wificam/config/go2rtc.yaml:/config/go2rtc.yaml:ro
    read_only: true
    tmpfs:
      - /tmp:size=32m,mode=1777
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
```

Copy `go2rtc.example.yaml` to the second private configuration path. Replace
`pool` and the example host address with local values. The RTSP port is bound
only to the bridge host's trusted-LAN address, and the go2rtc API port is not
published. This makes both services visible and manageable under **Apps →
Installed Applications** while preserving the same read-only and
capability-restricted container configuration.

## HTTP endpoints

For a camera named `camera1`:

- `/health` — connection/frame status as JSON;
- `/camera1/snapshot.jpg` — latest complete JPEG;
- `/camera1/stream.mjpeg` — full-rate multipart MJPEG stream;
- `/camera1/preview.mjpeg` — the same shared stream sampled at one frame per
  second for low-bandwidth dashboards;
- `/camera1/audio.alaw` — headerless 8 kHz, mono G.711 A-law microphone
  samples.

Example:

```text
http://bridge-host:8080/camera1/snapshot.jpg
http://bridge-host:8080/camera1/stream.mjpeg
http://bridge-host:8080/camera1/preview.mjpeg
http://bridge-host:8080/camera1/audio.alaw
```

The bridge has no built-in HTTP authentication. Keep it on a trusted local
network, bind it to loopback, or place it behind an authenticated reverse proxy.

## Home Assistant dashboard video

In Home Assistant, open **Settings → Devices & services → Add Integration** and
select **MJPEG IP Camera**. Create the full-rate entity with:

- MJPEG URL: `http://bridge-host:8080/camera1/stream.mjpeg`
- Still Image URL: `http://bridge-host:8080/camera1/snapshot.jpg`

Leave username and password empty unless an authenticating reverse proxy was
added. Put the full-rate entity on a **Picture Entity** card and set **Camera
view** to `live`:

```yaml
type: picture-entity
entity: camera.ino_a9_camera_1
name: Camera 1
camera_view: live
show_name: true
show_state: false
tap_action:
  action: more-info
  entity: camera.camera_1_with_audio
```

The example tap target is the separate audio-capable entity created below. If
audio is not configured, point it back at the MJPEG entity.

Repeat for each camera. For an optional lower-bandwidth overview, create a
second MJPEG IP Camera named `INO A9 Camera 1 Preview` using:

- MJPEG URL: `http://bridge-host:8080/camera1/preview.mjpeg`
- Still Image URL: `http://bridge-host:8080/camera1/snapshot.jpg`

Point the card's `entity` at `camera.ino_a9_camera_1_preview` while leaving its
tap action pointed at the audio-capable entity. The preview is a continuous
MJPEG response capped at 1 FPS and uses about one tenth of the
bridge-to-dashboard bandwidth of the tested 10 FPS stream. It does not prevent
pauses caused by a downstream viewer or change the camera-to-bridge protocol
pacing; all viewers share the same acknowledged PPRPC session.

Use the dedicated MJPEG integration rather than putting the multipart URL in
Generic Camera's Stream Source field. Current Home Assistant releases can route
Generic Camera streams through the stream/go2rtc stack and construct an
internal RTSP source. With this HTTP-only bridge that can fail as a WebRTC
`DESCRIBE 404 Not Found`. The MJPEG integration proxies the multipart stream
natively.

## Audio-capable opened view

The raw A-law endpoint is intentionally simple, but browsers and Home Assistant
need a stream containing both compatible video and audio. The included
`go2rtc.example.yaml` defines one on-demand RTSP stream per camera:

- MJPEG is transcoded to H.264;
- G.711 A-law is resampled and transcoded to mono Opus;
- both producers start only while the RTSP stream has a consumer;
- `-re` paces the headerless audio source, whose bytes carry no timestamps;
- the FFmpeg producer timeout is 30 seconds so a temporary media gap does not
  make go2rtc discard the source before the bridge recovers it.

The syntax follows go2rtc's
[FFmpeg source](https://github.com/AlexxIT/go2rtc/blob/master/internal/ffmpeg/README.md)
and [RTSP server](https://github.com/AlexxIT/go2rtc/blob/master/internal/rtsp/README.md)
documentation. Start the Compose stack or add the sidecar to the same TrueNAS
Custom App, then create a
[Generic Camera](https://www.home-assistant.io/integrations/generic/) in Home
Assistant with:

- Stream Source URL:
  `rtsp://192.168.1.38:8554/ino_a9_camera1_audio`
- Still Image URL: `http://192.168.1.38:8080/camera1/snapshot.jpg`

Name it `Camera 1 with audio`, then point the dashboard card's `tap_action`
at its entity as in the example above. Repeat with the numbered stream and
snapshot paths for each camera. The overview remains a native MJPEG card; only
opening the card starts H.264/Opus transcoding. Browsers may initially mute
playback under their autoplay policy, in which case use the player's speaker
control.

Neither the bridge HTTP service nor the example go2rtc RTSP service has
authentication. Publish them only on a trusted LAN, or add authentication and
an appropriate reverse-proxy/firewall policy.

The tested deployment has three full-rate MJPEG cards on a dashboard titled
**Cameras**. Each card opens its matching Generic Camera entity. Direct probing
of every RTSP source found H.264 video and Opus audio, and all three Home
Assistant config flows passed stream validation.

## Operational notes

- One camera connection feeds any number of local HTTP viewers; opening more
  dashboard views does not create more PPRPC sessions.
- The worker reconnects after camera power or Wi-Fi interruptions. It also
  refreshes the session after two seconds without a complete video frame, then
  retries after one second. Audio and other PPRPC packets keep the socket's
  activity watchdog alive during a video pause, while the frame watchdog still
  refreshes a stalled video channel. During a short reconnect, the API keeps
  recent media available for 15 seconds so Home Assistant entities do not
  flap; a connection with no recent activity is eventually reported as
  unavailable.
- The reader sends an encrypted command-107 keepalive every 500 ms and includes
  the latest AV sequence in protobuf field 4. That acknowledgement is required
  to keep the camera's media send window advancing; the two-second complete-frame
  watchdog remains the fallback if a session genuinely stalls.
- On 2026-09-04, the HAOS test app delivered 219 complete JPEGs in 45.7 seconds
  through one unchanged HTTP connection. The largest inter-frame gap was 0.593
  seconds, with no gap above two seconds and no probe errors.
- A video-only 30-second observation measured about 0.64 Mbit/s of MJPEG
  payload. Allow roughly 0.8–1.0 Mbit/s per active camera for video plus local
  protocol/TCP/Wi-Fi overhead; MJPEG varies with scene complexity.
- A preview viewer receives about one tenth of the tested camera's video
  payload because the bridge sends 1 of roughly 10 frames each second. This
  reduces bridge-to-viewer traffic; it does not change the camera-to-bridge
  Wi-Fi traffic because the shared camera connection remains full-rate.
- The microphone separately produces about 64.6 kbit/s of G.711 A-law payload,
  adding roughly 0.08 Mbit/s after local transport overhead. The bridge exposes
  it as raw A-law, and the optional sidecar converts it to Opus only while an
  audio-capable view is open.
- H.264/Opus transcoding uses CPU only in the tested deployment. At 640×480 and
  10 FPS it does not justify dedicating a GPU; hardware acceleration would add
  setup complexity without improving the camera's source quality.
- Keep the camera's Internet block in place. The bridge needs only TCP access
  to camera port `20190`; Home Assistant needs TCP access to bridge HTTP port
  `8080` and, for audio-capable views, RTSP port `8554`.
