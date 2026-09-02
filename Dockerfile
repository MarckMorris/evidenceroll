FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip wheel --wheel-dir /wheels .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    EVIDENCEROLL_HOME=/var/lib/evidenceroll \
    EVIDENCEROLL_POLICY=/etc/evidenceroll/policy.yaml

RUN groupadd --gid 10001 evidenceroll \
    && useradd --uid 10001 --gid evidenceroll --no-create-home --shell /usr/sbin/nologin evidenceroll \
    && mkdir -p /var/lib/evidenceroll /etc/evidenceroll \
    && chown -R evidenceroll:evidenceroll /var/lib/evidenceroll
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
COPY --chown=root:root config/policy.yaml /etc/evidenceroll/policy.yaml

USER 10001:10001
EXPOSE 8080
VOLUME ["/var/lib/evidenceroll"]
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"]
ENTRYPOINT ["python", "-m", "evidenceroll.cli"]
CMD ["serve", "--home", "/var/lib/evidenceroll", "--policy", "/etc/evidenceroll/policy.yaml"]

