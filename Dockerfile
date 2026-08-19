# Two stages. The build stage carries the toolchain and is discarded; the runtime
# stage is distroless, which has no shell, no package manager, and no perl. Every
# critical and high finding in the previous single-stage image came from the base
# image's perl packages, and perl-base is Debian-essential so it could not be removed
# from a Debian runtime. Removing the whole runtime distribution is what cleared them.
FROM python:3.11-slim-bookworm AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev


FROM gcr.io/distroless/python3-debian12 AS runtime

# The distroless interpreter is used directly, so the locked environment is put on
# the path rather than activated. `uv run` is deliberately absent: it re-resolved
# dependencies at container start and pulled the dev group.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/.venv/lib/python3.11/site-packages:/app/src

WORKDIR /app
COPY --from=build /app/.venv/lib/python3.11/site-packages /app/.venv/lib/python3.11/site-packages
# CatBoost links against OpenMP, which the distroless base does not ship.
COPY --from=build /usr/lib/*-linux-gnu/libgomp.so.1 /usr/lib/
COPY src ./src
COPY db ./db
COPY scripts ./scripts

USER 10001

ENTRYPOINT ["python3", "-m", "fraud_strategy.cli"]
CMD ["--help"]
