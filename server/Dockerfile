FROM node:22-alpine AS build-frontend
COPY frontend .
RUN npm install
RUN npm run build


FROM python:3.11-slim-bookworm AS run

RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    libavdevice-dev \
    libavfilter-dev \
    libopus-dev \
    libvpx-dev \
    pkg-config \
    libsrtp2-dev \
    ffmpeg \
	pipewire-audio  \
    dbus \
    alsa-utils \
    bluez \
    udev \
    xvfb \
    systemd \
    --no-install-recommends \
    && apt-get clean

RUN mkdir -p /etc/pipewire /run/pipewire /run/dbus /run/user/1000
ENV HOME=/home/app
RUN useradd --create-home --home-dir $HOME app \
	&& usermod -aG audio,adm,plugdev,video,dialout app \
	&& chown -R app:app $HOME && chown -R app:app /run/pipewire /run/dbus /run/user/1000

WORKDIR $HOME
USER app

ENV DISABLE_RTKIT=y
ENV XDG_RUNTIME_DIR=/run/user/1000
ENV PIPEWIRE_RUNTIME_DIR=/run/user/1000
ENV PULSE_RUNTIME_DIR=/run/user/1000
ENV DISPLAY=:0.0

COPY backend/src ./backend/src
COPY backend/required-debs.txt backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY --from=build-frontend ./dist ./frontend/dist

CMD dbus-daemon --session --address=unix:path=$XDG_RUNTIME_DIR/bus --fork && \
    Xvfb -screen $DISPLAY 1920x1080x24 & \
    pipewire & \
    wireplumber & \
    pipewire-pulse & \
    python ./backend/src/main.py