"""FastAPI control-plane API."""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any, cast

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse

from evidenceroll.config import Policy
from evidenceroll.registry import ModelRegistry, RegistryError, create_acceptance_registry
from evidenceroll.schemas import (
    AuditEventResponse,
    AuditIntegrityResponse,
    CreateReleaseRequest,
    EvidenceResponse,
    FeedbackRequest,
    FeedbackResponse,
    PredictionRequest,
    PredictionResponse,
    ReleaseResponse,
)
from evidenceroll.service import EvidenceRollService, PredictionContractError
from evidenceroll.store import (
    FeedbackConflictError,
    IdempotencyConflictError,
    NotFoundError,
    SQLiteStore,
    StoreError,
    TransitionConflictError,
)
from evidenceroll.telemetry import Telemetry


class AppSettings:
    def __init__(self) -> None:
        self.home = Path(os.getenv("EVIDENCEROLL_HOME", ".evidenceroll")).resolve()
        self.database_path = Path(
            os.getenv("EVIDENCEROLL_DATABASE", str(self.home / "evidenceroll.db"))
        )
        self.registry_path = Path(os.getenv("EVIDENCEROLL_REGISTRY", str(self.home / "registry")))
        self.policy_path = Path(os.getenv("EVIDENCEROLL_POLICY", "config/policy.yaml"))
        self.bootstrap_fixtures = os.getenv("EVIDENCEROLL_BOOTSTRAP_FIXTURES", "true").lower() in {
            "1",
            "true",
            "yes",
        }
        self.shadow_scoring = os.getenv("EVIDENCEROLL_SHADOW_SCORING", "background").lower()
        self.shadow_workers = int(os.getenv("EVIDENCEROLL_SHADOW_WORKERS", "2"))
        self.api_key = os.getenv("EVIDENCEROLL_API_KEY")
        self.audit_hmac_key = os.getenv("EVIDENCEROLL_AUDIT_HMAC_KEY")
        self.reconcile_interval_seconds = float(
            os.getenv("EVIDENCEROLL_RECONCILE_INTERVAL_SECONDS", "0")
        )
        if 0 < self.reconcile_interval_seconds < 5:
            raise ValueError("automatic reconcile interval must be zero or at least five seconds")


def build_service(settings: AppSettings) -> EvidenceRollService:
    settings.home.mkdir(parents=True, exist_ok=True)
    if settings.bootstrap_fixtures:
        create_acceptance_registry(settings.registry_path)
    return EvidenceRollService(
        store=SQLiteStore(settings.database_path, audit_hmac_key=settings.audit_hmac_key),
        registry=ModelRegistry(settings.registry_path),
        policy=Policy.from_yaml(settings.policy_path),
        telemetry=Telemetry(),
        shadow_scoring=settings.shadow_scoring,
        shadow_workers=settings.shadow_workers,
    )


def create_app(
    service: EvidenceRollService | None = None,
    settings: AppSettings | None = None,
) -> FastAPI:
    active_settings = settings or AppSettings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not hasattr(app.state, "service"):
            app.state.service = build_service(active_settings)
        task: asyncio.Task[None] | None = None
        if active_settings.reconcile_interval_seconds > 0:
            task = asyncio.create_task(
                _reconcile_loop(app.state.service, active_settings.reconcile_interval_seconds)
            )
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            service = getattr(app.state, "service", None)
            if service is not None:
                service.flush_shadow(timeout=10.0)
                service.close()

    app = FastAPI(
        title="EvidenceRoll",
        version="0.1.0",
        summary="Evidence-aware progressive delivery for ML models with delayed labels.",
        description=(
            "A fail-closed ML release control plane. Missing, stale, or insufficient evidence "
            "can hold a rollout but can never promote one."
        ),
        lifespan=lifespan,
    )
    if service is not None:
        app.state.service = service

    def get_service(request: Request) -> EvidenceRollService:
        return cast(EvidenceRollService, request.app.state.service)

    def require_api_key(
        x_evidenceroll_key: Annotated[str | None, Header()] = None,
    ) -> None:
        expected = active_settings.api_key
        if expected is None:
            return
        if x_evidenceroll_key is None or not hmac.compare_digest(
            x_evidenceroll_key.encode(), expected.encode()
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")

    mutation_auth = Depends(require_api_key)
    service_dependency = Depends(get_service)

    @app.exception_handler(NotFoundError)
    async def not_found_handler(_request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(FeedbackConflictError)
    async def feedback_conflict_handler(
        _request: Request, exc: FeedbackConflictError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(TransitionConflictError)
    async def transition_conflict_handler(
        _request: Request, exc: TransitionConflictError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict_handler(
        _request: Request, exc: IdempotencyConflictError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    async def service_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    app.add_exception_handler(StoreError, service_error_handler)
    app.add_exception_handler(RegistryError, service_error_handler)
    app.add_exception_handler(PredictionContractError, service_error_handler)

    @app.get("/healthz", tags=["operations"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["operations"])
    def readyz(
        response: Response, current: EvidenceRollService = service_dependency
    ) -> dict[str, Any]:
        if not current.registry.ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ready" if current.registry.ready else "not_ready",
            "registry_ready": current.registry.ready,
            "registry_versions": list(current.registry.versions()),
            "policy_schema_version": current.policy.schema_version,
        }

    @app.get("/metrics", include_in_schema=False)
    def metrics(current: EvidenceRollService = service_dependency) -> Response:
        return Response(current.telemetry.render(), media_type="text/plain; version=0.0.4")

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        candidate = files("evidenceroll").joinpath("static/dashboard.html")
        return FileResponse(str(candidate))

    @app.post(
        "/v1/releases",
        response_model=ReleaseResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[mutation_auth],
        tags=["releases"],
    )
    def create_release(
        payload: CreateReleaseRequest,
        current: EvidenceRollService = service_dependency,
    ) -> dict[str, Any]:
        return current.create_release(
            champion_version=payload.champion_version,
            challenger_version=payload.challenger_version,
            release_id=payload.release_id,
        ).to_dict()

    @app.get("/v1/releases/{release_id}", response_model=ReleaseResponse, tags=["releases"])
    def get_release(
        release_id: str, current: EvidenceRollService = service_dependency
    ) -> dict[str, Any]:
        return current.store.get_release(release_id).to_dict()

    @app.post(
        "/v1/predictions",
        response_model=PredictionResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[mutation_auth],
        tags=["inference"],
    )
    def predict(
        payload: PredictionRequest,
        current: EvidenceRollService = service_dependency,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> PredictionResponse:
        prediction_id = _prediction_id(idempotency_key) if idempotency_key else None
        return current.predict(
            release_id=payload.release_id,
            entity_id=payload.entity_id,
            features=payload.features,
            prediction_id=prediction_id,
        )

    @app.post(
        "/v1/feedback",
        response_model=FeedbackResponse,
        dependencies=[mutation_auth],
        tags=["evidence"],
    )
    def feedback(
        payload: FeedbackRequest,
        current: EvidenceRollService = service_dependency,
    ) -> FeedbackResponse:
        idempotent = current.add_feedback(payload.prediction_id, payload.label)
        return FeedbackResponse(
            prediction_id=payload.prediction_id,
            accepted=True,
            idempotent=idempotent,
        )

    @app.get(
        "/v1/releases/{release_id}/evidence",
        response_model=EvidenceResponse,
        tags=["evidence"],
    )
    def evidence(
        release_id: str, current: EvidenceRollService = service_dependency
    ) -> dict[str, Any]:
        return current.evaluate(release_id).to_dict()

    @app.post(
        "/v1/releases/{release_id}/reconcile",
        dependencies=[mutation_auth],
        tags=["releases"],
    )
    def reconcile(
        release_id: str, current: EvidenceRollService = service_dependency
    ) -> dict[str, Any]:
        report, release = current.reconcile(release_id)
        return {"evidence": report.to_dict(), "release": release.to_dict()}

    @app.get(
        "/v1/releases/{release_id}/audit",
        response_model=list[AuditEventResponse],
        tags=["governance"],
    )
    def audit(
        release_id: str, current: EvidenceRollService = service_dependency
    ) -> list[dict[str, Any]]:
        current.store.get_release(release_id)
        return current.store.audit_events(release_id)

    @app.get(
        "/v1/releases/{release_id}/audit-integrity",
        response_model=AuditIntegrityResponse,
        tags=["governance"],
    )
    def audit_integrity(
        release_id: str, current: EvidenceRollService = service_dependency
    ) -> dict[str, Any]:
        current.store.get_release(release_id)
        return current.store.verify_audit_chain(release_id)

    @app.get("/v1/argo/releases/{release_id}/analysis", tags=["integrations"])
    def argo_analysis(
        release_id: str, current: EvidenceRollService = service_dependency
    ) -> dict[str, Any]:
        report = current.evaluate(release_id)
        mapping = {
            "hold": "Inconclusive",
            "start_canary": "Successful",
            "promote": "Successful",
            "rollback": "Failed",
        }
        return {
            "status": mapping[report.action.value],
            "action": report.action.value,
            "evidence_digest": report.evidence_digest,
            "reason_codes": list(report.reason_codes),
        }

    return app


def _prediction_id(idempotency_key: str) -> str:
    import hashlib

    return f"pred-{hashlib.sha256(idempotency_key.encode()).hexdigest()}"


async def _reconcile_loop(service: EvidenceRollService, interval: float) -> None:
    logger = logging.getLogger("evidenceroll.reconciler")
    while True:
        await asyncio.sleep(interval)
        for release_id in service.store.active_release_ids():
            try:
                await asyncio.to_thread(service.reconcile, release_id)
            except Exception:
                logger.exception(
                    "automatic reconciliation failed", extra={"release_id": release_id}
                )


app = create_app()
