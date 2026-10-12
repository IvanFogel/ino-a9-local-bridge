# Home Assistant App base pinned to the official current example baseline.
ARG BUILD_FROM=ghcr.io/home-assistant/base:3.23@sha256:1c7a8c7321c15cdc327c264232a76e6fbfdaf7f2b1734a8d8da6fcc994f66015

# The upstream image is multi-architecture; the exact validated go2rtc release is copied in.
FROM alexxit/go2rtc:1.9.14@sha256:675c318b23c06fd862a61d262240c9a63436b4050d177ffc68a32710d9e05bae AS go2rtc

FROM ${BUILD_FROM}

ARG BUILD_VERSION=0.4.3
ARG BUILD_ARCH

ENV PIP_BREAK_SYSTEM_PACKAGES=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/ino-a9/src

COPY requirements.txt /tmp/requirements.txt

RUN apk add --no-cache \
      ffmpeg \
      py3-pip \
      python3 \
    && pip3 install --no-cache-dir -r /tmp/requirements.txt

COPY --from=go2rtc /usr/local/bin/go2rtc /usr/local/bin/go2rtc
COPY src /opt/ino-a9/src
COPY rootfs /

RUN chmod a+x \
      /etc/cont-init.d/10-runtime-config \
      /etc/services.d/bridge/run \
      /etc/services.d/go2rtc/run

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.title="INO-A9 Local Bridge" \
    org.opencontainers.image.source="https://github.com/IvanFogel/ino-a9-local-bridge"
