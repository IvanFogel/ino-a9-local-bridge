"""Constants for the INO-A9 integration."""

from __future__ import annotations

DOMAIN = "ino_a9"
APP_DISCOVERY_SERVICE = "ino_a9"
API_VERSION = "v1"
CONF_HOST = "host"
CONF_HTTP_PORT = "http_port"
CONF_RTSP_PORT = "rtsp_port"
CONF_TOKEN = "token"
COORDINATOR = "coordinator"
API = "api"

CONTROL_LED = "led"
CONTROL_NIGHT_VISION = "night_vision"
CONTROL_FLIP = "flip"
CONTROL_VIDEO_QUALITY = "video_quality"
CONTROL_MOTION = "motion"
CONTROL_INTRUSION = "intrusion"

NIGHT_VISION_OPTIONS = ("automatic", "enabled", "disabled")
FLIP_OPTIONS = ("upright", "horizontal", "vertical", "rotate_180")
VIDEO_QUALITY_OPTIONS = ("sd", "hd", "uhd")
MOTION_OPTIONS = ("high", "medium", "low", "closed")

SERVICE_SET_INTRUSION_SCHEDULE = "set_intrusion_schedule"
ATTR_ENABLED = "enabled"
ATTR_WEEKDAYS = "weekdays"
ATTR_START_TIME = "start_time"
ATTR_END_TIME = "end_time"
