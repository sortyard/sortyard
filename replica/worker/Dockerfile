# The replica's worker image: the Sortyard image plus an agent command, which is how any lane's
# worker image is made (README, "Worker image"). Here the agent is a script that plays one
# (agent.py); a real lane installs its agent CLI in this layer instead.
#
#   docker build --build-arg BASE=ghcr.io/sortyard/sortyard:<tag> -t <worker image> replica/worker
ARG BASE
FROM ${BASE}
COPY agent.py /opt/sortyard-replica/agent.py
