FROM python:3.12-slim

# `baresip` provides the real SIP UA binary that baresipy wraps via pexpect.
# `ffmpeg` is required by pydub (used for audio conversion/resampling).
# `ca-certificates` is needed for any TLS/HTTPS traffic done by optional
# extras (eg. ovos-* pulling models).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        baresip \
        ffmpeg \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . /app

# Build-time switch to pull in the optional OVOS extra
# (`ovos-plugin-manager`, `phoonnx`, `ovos-simple-listener`), eg:
#   docker build --build-arg INSTALL_EXTRAS=[ovos] -t baresipy .
ARG INSTALL_EXTRAS=""

RUN pip install --no-cache-dir ".${INSTALL_EXTRAS}"

CMD ["python"]
