# Redacted lab notebook

This document records the investigation of one user-owned `INO-A9-V2.8`
camera. Secrets and transient authentication material are deliberately omitted.
Dates use Europe/Stockholm local time.

## 2026-08-19 — identification and containment

1. Compared the PCB marking and layout with the ongoing Elektroda discussion
   about Pinmei/Linklemo A9 variants.
2. Identified the factory Wi-Fi name as an `LLM_...` network rather than the
   `Nax_...` network used by the older V720/Naxclow implementation.
3. Prepared a disposable Arch Linux laptop as the setup workstation. A first
   sudoers command contained a stray space in `chmod 440 /etc/sudoers.d/ codex`.
   This produced an error for a nonexistent `codex` path but did not damage the
   sudoers file; `/etc/sudoers.d/codex` had already been created and `visudo`
   reported the configuration as valid. Permissions and account state were
   subsequently verified.
4. Joined the camera's isolated setup network and captured only the traffic
   necessary to understand provisioning.
5. Ran Linklemo in a temporary Waydroid environment because installing it on a
   personal phone was explicitly out of scope. The environment was restricted
   from Internet access.
6. Provisioned the camera onto the IoT Wi-Fi. Credentials are not retained in
   this repository.

## Stable network state

The first camera is reserved at `192.168.1.10` by MAC address. Addresses
`.11` through `.15` were checked and kept available for subsequent cameras.

OPNsense contains:

- a `WIFI_CAMERAS` alias covering `192.168.1.10` through `.15`;
- a logged block rule placed before the general LAN allow rule;
- a DHCP reservation for the first camera.

The block rule was verified empirically. The camera remained pingable and TCP
port `20190` remained reachable from the LAN while OPNsense logged denied cloud
attempts. Observed destinations/ports are recorded for evidence, not as an
allowlist: `47.240.1.244` on TCP/UDP `8000`, TCP `465`, and UDP `80`.

## App and protocol analysis

The split APK was copied from the temporary Android environment and decompiled
locally. The following behavior was found:

- package name `com.xcthings.fchan`;
- native communications in `libgojni.so`;
- a PPRPC SDK layer under `user.*` and `com.xc.august.ipc.*`;
- LAN connection via `FTConn.lanDailByDid()`;
- live start via `FTConn.videoPlay(channel, quality, speed)`;
- ordinary single-camera call sites use `(0, 0, 0)`;
- decoded frames arrive as `CallAVPacket` objects containing format, key-frame
  flag, channel, sequence, timestamp, and payload;
- recognized video formats include H.264, H.265, MJPEG, and format value 10;
- the SDK can be initialized with its cloud push transport disabled.

The native library's Go build metadata identifies newer internal PPRPC modules,
while an older public version remains archived by the Go module proxy. That
archive provides the packet framing documented in `protocol.md`.

## 2026-08-20 — independent bridge and Home Assistant

1. Implemented a clean-room Python client for the documented PPRPC framing,
   LAN authentication, time synchronization, fragmented AV reassembly, and the
   camera's partial-frame AES-CBC encryption.
2. Validated the independent client against the physical camera. The
   independently decrypted network frame matched the decoded frame delivered
   by the vendor SDK.
3. Wrapped the client in a multi-camera HTTP service with a shared connection
   per camera, snapshot endpoint, multipart MJPEG endpoint, and JSON health
   endpoint.
4. Added a 15-second complete-frame watchdog after the test unit occasionally
   stopped producing complete images while leaving its TCP session open. The
   worker closes the stale session and retries three seconds later.
5. Added a capability-restricted, read-only Docker deployment and installed it
   on an always-on local host. A live soak test confirmed automatic recovery
   from a camera pause.
6. Ran 27 tests using synthetic protocol packets, audio chunks, and JPEG frames
   only. No
   captured traffic, proprietary application files, camera credentials, or
   imagery are test fixtures.
7. Integrated the bridge with Home Assistant. Generic Camera was initially
   tested, but current stream/go2rtc handling converted the HTTP MJPEG source
   into an internal RTSP URL and returned `DESCRIBE 404 Not Found` to WebRTC.
   Replacing only that config entry with **MJPEG IP Camera** preserved
   `camera.ino_a9_camera_1` and made both the snapshot and native multipart
   stream proxies pass.
8. Created a Home Assistant dashboard titled **Cameras** with a live Picture
   Entity card for that camera. Neither the setup laptop nor Linklemo is
   required for normal viewing.
9. Migrated the bridge from an unmanaged Compose container to a TrueNAS Custom
   App named `ino-a9-local-bridge`. Its health endpoint and live camera worker
   remained healthy after migration.
10. Recovered Linklemo's `FTConn.audioPlay(0)` command ID (`2614`) from the
    native SDK and tested it directly. The camera returned success and emitted
    unencrypted G.711 A-law audio at 8 kHz, reported as 16-bit mono. A 30-second
    header-only probe counted 302 packets and 242,204 payload bytes; it did not
    save or decode microphone content.
11. Recovered the SDK's video QoS command (`2612`) and tested both runtime QoS
    changes and QoS values supplied in fresh `VideoPlay` (`2610`) requests.
    Values 5, 10, 15, 20, 25, and 30 were accepted, but the camera reported QoS
    5/10 FPS/MJPEG and produced the same 640×480 dimensions, JPEG quantization
    tables, and approximate frame sizes for every value. The bridge now always
    requests maximum SDK QoS 30; this firmware clamps it to its real maximum.
12. Provisioned two additional cameras by invoking Linklemo's local `IpcAp`
    SDK against the explicit setup address. No Linklemo account or Internet
    access was used. Each unit's private discovery values were independently
    validated by authenticating and receiving a complete JPEG frame.
13. Found that both additional cameras used a station MAC equal to the setup
    AP BSSID with the low bit of its final octet toggled. One case incremented
    and the other decremented the value. DHCP/ARP verification remains
    mandatory because this is an observed device-family behavior, not a
    guaranteed specification.
14. Added all three workers to the TrueNAS Custom App and all three full-rate
    MJPEG entities to Home Assistant.
15. Added and measured a one-frame-per-second MJPEG preview endpoint as an
    optional low-bandwidth dashboard mode. Direct stream measurements showed
    that longer freezes originate in the camera output rather than Home
    Assistant's card refresh mode.
16. Added a raw G.711 A-law HTTP endpoint backed by the same shared camera
    session. An on-demand go2rtc sidecar transcodes MJPEG to H.264 and A-law to
    Opus, then presents both tracks over RTSP. Cold-start probing received both
    tracks and packet data, and three Home Assistant Generic Camera entries
    passed stream validation. The dashboard cards keep their native MJPEG
    entities and open the matching audio-capable entity when selected.
17. Traced the recurring still image at the bridge health boundary. On all
    three units the camera stopped sending complete video while G.711 audio
    remained less than half a second old on the same TCP session. Video-only
    operation also stopped, but later, proving audio was not the root cause.
    Empty PPRPC heartbeat packets did not alter the behavior, and replaying
    VideoPlay was rejected or ineffective. The bridge watchdog was reduced to
    two seconds with a one-second retry so existing HTTP viewers recover
    without waiting through the previous 15-second detection interval.
    A one-second trial caused new sessions to be declared stale before their
    first complete JPEG, so two seconds is the tested lower bound. A 90-second
    viewer test then received 498 frames on one unchanged HTTP connection with
    a maximum 5.61-second inter-frame gap.
18. On 2026-08-31, the HAOS test deployment reproduced repeated temporary
    `unavailable` entities: the two-second watchdog restarted the otherwise
    healthy PPRPC session whenever one of those measured video gaps occurred.
    A ten-second trial reduced those availability transitions but made the
    viewer freeze for too long. The current bridge keeps the two-second video
    refresh, while any PPRPC packet resets the socket-activity watchdog. Its
    API retains recent media availability for 15 seconds during the expected
    reconnect window, avoiding unnecessary Home Assistant availability
    transitions without hiding a prolonged outage.
19. On 2026-09-04, comparison with the working standalone PPRPC client showed
    that the bridge was missing the client-originated command-107 keepalive's
    AV acknowledgement. The bridge now sends that request every 500 ms and
    includes protobuf field 4 with the latest AV sequence. In the HAOS test,
    the updated app delivered 219 complete JPEGs in 45.7 seconds; the maximum
    inter-frame gap was 0.593 seconds, with no gap above two seconds and no
    errors.

## Temporary components and cleanup

The quarantine access point and its bridge were removed after provisioning.
Temporary `hostapd` and `sshpass` packages installed on the setup laptop were
removed. The original provisioning capture and hostapd configuration were
deleted. After the first bridge validation, the original Waydroid container,
Linklemo data, Frida components, captures, decrypted buffers, cookies, and
camera-specific laptop firewall rules were removed.

An isolated Waydroid/Linklemo/Frida setup was later recreated to provision the
additional user-owned cameras. It remains isolated and is being retained
temporarily because more cameras may still be added. The authorized APK and
decompiler output are private local research artifacts and are not in this
repository. They, the disposable environment, temporary firewall state, and
private provisioning scripts are scheduled for removal when provisioning is
declared complete. Packages installed only for the first phase and their
same-time unused dependencies were uninstalled. Broadcast-forwarding and
user-linger settings were restored to their recorded pre-test values. The SSH
maintenance account was retained as requested.

The Home Assistant migration used a short-lived in-memory access token derived
locally on the Home Assistant host. The helper and bytecode were deleted
immediately after verification; no token or authentication database was copied
off the host. Temporary deployment sources on the bridge host and the final
verification image were also removed.

## Publication hygiene

The public repository excludes:

- Wi-Fi SSIDs and passphrases;
- SSH, firewall, and application credentials;
- CSRF tokens, cookies, and API client secrets;
- APK files and decompiled proprietary source;
- packet captures, firmware dumps, and camera imagery;
- the full camera identifier and full MAC address.

The hardware model, local addressing plan, protocol port, and observed cloud
destinations are retained because they are needed to reproduce the containment
and protocol work.
