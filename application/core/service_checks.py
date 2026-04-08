import logging
import os
from dataclasses import dataclass
from typing import Dict, Tuple
from urllib.parse import urlparse

import redis
from pymongo import MongoClient
try:
    from qdrant_client import QdrantClient
except ModuleNotFoundError:  # optional dependency
    QdrantClient = None

from application.core.settings import settings


@dataclass
class CheckResult:
    ok: bool
    detail: str


def _check_redis(url: str) -> CheckResult:
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        if client.ping():
            return CheckResult(ok=True, detail="redis ping successful")
        return CheckResult(ok=False, detail="redis ping failed")
    except Exception as exc:
        return CheckResult(ok=False, detail=f"redis connection failed: {exc}")


def _check_mongo(uri: str) -> CheckResult:
    client = None
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=2000)
        client.admin.command("ping")
        return CheckResult(ok=True, detail="mongo ping successful")
    except Exception as exc:
        return CheckResult(ok=False, detail=f"mongo connection failed: {exc}")
    finally:
        if client is not None:
            client.close()


def _check_qdrant(url: str) -> CheckResult:
    if QdrantClient is None:
        return CheckResult(ok=False, detail="qdrant_client not installed")
    try:
        client = QdrantClient(url=url, api_key=settings.QDRANT_API_KEY, timeout=2.0)
        client.get_collections()
        return CheckResult(ok=True, detail="qdrant API reachable")
    except Exception as exc:
        return CheckResult(ok=False, detail=f"qdrant connection failed: {exc}")


def _is_qdrant_enabled() -> bool:
    return settings.VECTOR_STORE.lower() == "qdrant"


def _normalize_host(value: str) -> str:
    parsed = urlparse(value)
    return parsed.hostname or value


def required_service_checks() -> Dict[str, CheckResult]:
    checks: Dict[str, CheckResult] = {
        "redis": _check_redis(settings.CELERY_BROKER_URL),
        "mongo": _check_mongo(settings.MONGO_URI),
    }
    if _is_qdrant_enabled():
        qdrant_url = settings.QDRANT_URL or "http://qdrant:6333"
        checks["qdrant"] = _check_qdrant(qdrant_url)
    return checks


def summarize_checks(checks: Dict[str, CheckResult]) -> Tuple[bool, Dict[str, dict]]:
    all_ok = all(result.ok for result in checks.values())
    payload = {name: {"ok": result.ok, "detail": result.detail} for name, result in checks.items()}
    return all_ok, payload


def log_startup_diagnostics(logger: logging.Logger) -> None:
    vector_store = settings.VECTOR_STORE.lower()
    diagnostics = {
        "auth_type": settings.AUTH_TYPE or "none",
        "vector_store": vector_store,
        "llm_provider": settings.LLM_PROVIDER,
        "mongo_host": _normalize_host(settings.MONGO_URI),
        "broker_host": _normalize_host(settings.CELERY_BROKER_URL),
        "cache_host": _normalize_host(settings.CACHE_REDIS_URL),
        "startup_dependency_checks": settings.STARTUP_DEPENDENCY_CHECKS,
        "startup_check_strict": settings.STARTUP_CHECK_STRICT,
        "service_name": os.getenv("DOCSGPT_SERVICE_NAME", "docsgpt-backend"),
    }
    if vector_store == "qdrant":
        diagnostics["qdrant_host"] = _normalize_host(settings.QDRANT_URL or "http://qdrant:6333")
    logger.info("startup diagnostics: %s", diagnostics)


def run_startup_dependency_checks(logger: logging.Logger) -> None:
    if not settings.STARTUP_DEPENDENCY_CHECKS:
        logger.info("startup dependency checks disabled")
        return

    checks = required_service_checks()
    all_ok, payload = summarize_checks(checks)
    if all_ok:
        logger.info("startup dependency checks passed: %s", payload)
        return

    logger.error("startup dependency checks failed: %s", payload)
    if settings.STARTUP_CHECK_STRICT:
        raise RuntimeError("startup dependency checks failed")
