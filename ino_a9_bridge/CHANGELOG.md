# 0.4.3

- Close video, preview and audio HTTP responses after 15 seconds without media,
  releasing request threads left behind by disconnected/retrying readers.
- Bound HTTP socket reads and writes so stalled clients cannot retain handlers
  indefinitely.
- Add an internal HTTP health URL for Home Assistant's enabled Watchdog to
  detect an unresponsive bridge even while go2rtc and the container still run.
