# Install Vila Velha RTSP App and Repoint Frigate

> Execute inline; the user explicitly requires no agents or subagents.

**Goal:** Install the INO-A9 Local Bridge on Vila Velha HAOS and make Frigate
consume its stable local RTSP stream.

**Architecture:** The app publishes only TCP `8554` from VM 100. Frigate camera
`asd` consumes `rtsp://192.168.1.120:8554/ino_a9_front`; the app's HTTP bridge
and go2rtc API remain private.

## Constraints

- Preserve the existing Frigate configuration and app state with dated backups.
- Reuse the already validated `front` camera options without exposing secrets.
- Change only the Frigate `asd` input URL; do not alter other cameras or
  unrelated Home Assistant services.
- Validate the native Frigate config before restarting only the Frigate app.
- Do not reboot the VM or restart Home Assistant Core.

## Tasks

### 1. Prepare the app

- [x] Add the Supervisor mapping `8554/tcp: 8554` and packaging coverage.
- [x] Run the app test suites.
- [x] Transfer the app source to VM 100 and install version `0.4.1`.
- [x] Restore the single `front` camera option from the preserved test backup.

### 2. Validate the app boundary

- [x] Confirm the app is started and only host port 8554 is published.
- [x] Confirm RTSP `OPTIONS` returns `200 OK` from the Frigate network.
- [x] Decode five video frames from the app stream using Frigate's FFmpeg.

### 3. Repoint Frigate

- [x] Back up the active Frigate `config.yaml`.
- [x] Replace only the obsolete `asd` RTSP URL with the VM 100 URL and path.
- [x] Run Frigate's native `--validate-config` check.
- [x] Restart only the Frigate app.

### 4. Final verification

- [x] Confirm Frigate is healthy and `asd` has non-zero camera/process FPS.
- [x] Confirm a fresh FFmpeg probe still sees H.264 video and Opus audio.
- [x] Run the Home Assistant Core check through its authenticated internal
  Supervisor channel.
- [x] Record the verified placement and URL in the homelab runbook.
