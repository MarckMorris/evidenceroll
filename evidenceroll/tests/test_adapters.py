from __future__ import annotations

import json

import httpx
import numpy as np
import pytest

from evidenceroll.adapters import GenericHTTPAdapter, KServeV2Adapter
from evidenceroll.registry import RegistryError


def response(payload: dict[str, object]) -> httpx.Response:
    request = httpx.Request("POST", "https://model.internal/infer")
    return httpx.Response(200, content=json.dumps(payload).encode(), request=request)


def test_generic_http_adapter_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        seen["url"] = url
        seen["json"] = kwargs["json"]
        return response({"probability": [0.72]})

    monkeypatch.setattr(httpx, "post", fake_post)
    adapter = GenericHTTPAdapter({"endpoint": "https://model.internal/infer"}, ("a", "b"))
    assert adapter.score(np.asarray([[1.0, 2.0]])) == pytest.approx(0.72)
    assert seen["json"] == {"instances": [{"a": 1.0, "b": 2.0}]}


def test_kserve_v2_adapter_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: response(
            {"outputs": [{"name": "probabilities", "data": [[0.2, 0.8]]}]}
        ),
    )
    adapter = KServeV2Adapter(
        {"endpoint": "https://model.internal/v2/models/challenger/infer"}, ("a", "b")
    )
    assert adapter.score(np.asarray([[1.0, 2.0]])) == pytest.approx(0.8)


def test_remote_adapter_rejects_invalid_probability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: response({"probability": 2.0}),
    )
    adapter = GenericHTTPAdapter({"endpoint": "https://model.internal/infer"}, ("a", "b"))
    with pytest.raises(RegistryError, match="between 0 and 1"):
        adapter.score(np.asarray([[1.0, 2.0]]))


def test_remote_auth_is_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL_TOKEN", raising=False)
    with pytest.raises(RegistryError, match="credential is not set"):
        GenericHTTPAdapter(
            {"endpoint": "https://model.internal/infer", "bearer_token_env": "MODEL_TOKEN"},
            ("a",),
        )
