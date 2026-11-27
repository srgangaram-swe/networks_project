FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    XDG_CACHE_HOME=/tmp/cache \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    GIT_OPTIONAL_LOCKS=0 \
    GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0=safe.directory \
    GIT_CONFIG_VALUE_0=/workspace

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git libstdc++6 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/bootstrap
COPY requirements-dev.txt requirements-analysis.txt requirements-plots.txt ./
COPY src/ ./src/
COPY scripts/setup_environment.py scripts/setup_environment.sh ./scripts/
RUN sh scripts/setup_environment.sh --venv /opt/venv --profile analysis

WORKDIR /workspace
USER 10001:10001
ENTRYPOINT ["/opt/venv/bin/python", "-m", "analysis.policy_comparison"]
CMD ["--help"]
