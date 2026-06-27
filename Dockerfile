# =============================================================================
# Dockerfile - EAWeather BI Pipeline
# =============================================================================
#
# WHAT IS A DOCKERFILE?
# A Dockerfile is a text recipe that tells Docker how to build a "container
# image". Think of an image like a snapshot of a fully configured computer:
# it includes the OS, Python, all libraries, and your code, all frozen together.
# When you run the image, Docker creates a "container" - a lightweight, isolated
# process that behaves the same on every machine regardless of what the host has.
#
# HOW TO BUILD AND RUN (manual):
#   docker build -t eaweather .           # build the image, tag it "eaweather"
#   docker run --env-file .env eaweather  # run a container from that image
#
# In practice, use docker-compose instead (see docker-compose.yml).
# =============================================================================


# --- Base image --------------------------------------------------------------
#
# FROM tells Docker which starting image to use as the foundation.
# We use the official Python image, version 3.11, "slim" variant.
#
# Why "slim"?
#   Full Python image = ~900MB (includes compilers, docs, etc. we don't need).
#   Slim variant     = ~130MB  (bare minimum to run Python).
#   Smaller image = faster builds, faster deploys, less storage cost.
#
FROM python:3.11-slim


# --- System-level dependencies -----------------------------------------------
#
# RUN executes a shell command inside the image during the build step.
#
# We need:
#   libpq-dev  - C headers that psycopg2 (PostgreSQL driver) needs to compile
#   gcc        - C compiler, also required by psycopg2's build process
#   curl       - handy for health checks and debugging inside the container
#
# Why one long RUN instead of separate RUN lines?
#   Each RUN instruction creates a new "layer" in the image.
#   apt-get update leaves a package cache that bloats the layer if not cleaned.
#   By chaining everything in ONE RUN with && and ending with the cache cleanup,
#   we keep the resulting layer lean with no leftover cruft.
#
RUN apt-get update && apt-get install -y \
        libpq-dev \
        gcc \
        curl \
    && rm -rf /var/lib/apt/lists/*


# --- Working directory --------------------------------------------------------
#
# WORKDIR sets the active directory for all instructions that follow.
# If it doesn't exist, Docker creates it automatically.
# /app is the conventional name for the application directory in containers.
#
WORKDIR /app


# --- Install Python dependencies BEFORE copying code -------------------------
#
# Docker caches each layer. If a layer hasn't changed, Docker reuses it,
# making subsequent rebuilds very fast.
#
# Strategy:
#   1. Copy ONLY requirements.txt first.
#   2. Install dependencies.
#   3. THEN copy the rest of the code.
#
# Result: if you change a .py file but not requirements.txt, Docker skips
# the pip install step entirely on the next build (uses cache).
# This saves minutes when iterating during development.
#
COPY requirements.txt .

# --no-cache-dir tells pip not to store downloaded packages.
# There is no benefit to a pip cache inside a container - it just wastes space.
RUN pip install --no-cache-dir -r requirements.txt


# --- Copy project code -------------------------------------------------------
#
# COPY <host-path> <container-path>
# Copies everything from the project root into /app inside the container.
#
# Files in .dockerignore are excluded - similar to .gitignore.
# We exclude venv/, data/, .env, __pycache__ etc. to keep the image clean
# and to avoid accidentally baking secrets into the image.
#
COPY . .


# --- Create data directories -------------------------------------------------
#
# The pipeline writes raw JSON and processed CSVs to data/raw/ and data/processed/.
# We create them here so the pipeline never errors on a missing directory.
# For persistent storage across container restarts, these are mounted as
# volumes in docker-compose.yml (so data survives even if the container stops).
#
RUN mkdir -p data/raw data/processed


# --- Environment variable defaults -------------------------------------------
#
# ENV sets variables available inside the container at runtime.
# Only non-secret defaults go here.
# Secrets (API keys, DB passwords) are injected via --env-file at runtime.
#
# NEVER hardcode real secrets in a Dockerfile. The image can be pushed to
# a registry (like Docker Hub) and pulled by anyone who has access.
#
# PYTHONUNBUFFERED=1
#   Without this, Python buffers stdout/stderr output. In a container, buffered
#   output means log lines don't appear in `docker logs` until the buffer fills.
#   Setting this to 1 forces immediate log output - critical for debugging.
#
# PYTHONDONTWRITEBYTECODE=1
#   Stops Python from writing .pyc compiled bytecode cache files.
#   Useless inside a container and just creates unnecessary file clutter.
#
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1


# --- Default command ---------------------------------------------------------
#
# CMD defines what runs when someone does `docker run eaweather` with no
# extra arguments. It can be overridden at runtime, e.g.:
#   docker run eaweather python -m ml.aqi_model --predict
#
# We default to a full ETL pipeline run.
#
CMD ["python", "-m", "pipeline.run_pipeline"]
