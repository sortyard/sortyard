# One image for every Sortyard service; the Deployment's command picks the entry point
# (sortyard-api, sortyard-kernel, sortyard-conductor, ...). It is also the base of a lane's
# worker image: the three containers of a worker Job run `sortyard-worker`, which needs git.
# No agent is in this image. A worker image is this image plus the agent command the
# deployment configures (README, "Worker image"; replica/worker/Dockerfile is an example).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# git: what `sortyard-worker` clones and pushes with (over https, hence the CA certificates).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY pyproject.toml README.md LICENSE.md LICENSE-APACHE NOTICE ./
COPY src ./src
RUN pip install . && rm -rf /src

WORKDIR /
USER 10001
EXPOSE 8080
CMD ["sortyard-api"]
