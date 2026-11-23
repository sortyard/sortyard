# One image for every Sortyard service; the Deployment's command picks the entry point
# (sortyard-api, sortyard-conductor, ...).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /src
COPY pyproject.toml README.md LICENSE.md LICENSE-APACHE NOTICE ./
COPY src ./src
RUN pip install . && rm -rf /src

WORKDIR /
USER 10001
EXPOSE 8080
CMD ["sortyard-api"]
