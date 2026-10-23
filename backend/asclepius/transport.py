import asyncio
import json
import logging
import ssl
from contextvars import ContextVar

import httpx
from pydantic import TypeAdapter, ValidationError

from asclepius.domain import AppError, Endpoint, RetryAfter

_provider_logging = ContextVar("asclepius_provider_logging", default=False)


class _ProviderLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _provider_logging.get()


_provider_filter = _ProviderLogFilter()


class ProviderHttpError(AppError):
    def __init__(self, status_code: int, retry_after: RetryAfter | None = None) -> None:
        super().__init__(f"provider_http_{status_code}", "Provider rejected the request.")
        self.status_code = status_code
        self.retry_after = retry_after


def _install_log_filters() -> None:
    names = {"httpx", "httpcore", *logging.Logger.manager.loggerDict}
    for name in names:
        if name in {"httpx", "httpcore"} or name.startswith(("httpx.", "httpcore.")):
            logging.getLogger(name).addFilter(_provider_filter)


class JsonTransport:
    def __init__(self, *, verify: ssl.SSLContext | bool = True) -> None:
        if verify is not True and (
            not isinstance(verify, ssl.SSLContext)
            or verify.verify_mode != ssl.CERT_REQUIRED
            or not verify.check_hostname
        ):
            raise AppError("transport_config", "TLS verification cannot be disabled.", 2)
        self._verify = verify

    async def post(
        self,
        endpoint: str,
        payload: dict,
        *,
        secret: str,
        deadline_seconds: float,
        response_bytes: int,
    ) -> dict:
        try:
            TypeAdapter(Endpoint).validate_python(endpoint)
            httpx.URL(endpoint)
        except (ValidationError, httpx.InvalidURL):
            raise AppError("transport_config", "Invalid provider endpoint.", 2) from None
        if not secret or any(ord(char) < 33 or ord(char) > 126 for char in secret):
            raise AppError("secret_invalid", "Provider secret is missing or invalid.", 2)
        if deadline_seconds <= 0 or response_bytes <= 0:
            raise AppError("transport_config", "Transport limits must be positive.", 2)
        _install_log_filters()
        token = _provider_logging.set(True)
        try:
            async with asyncio.timeout(deadline_seconds):
                async with httpx.AsyncClient(
                    trust_env=False,
                    follow_redirects=False,
                    timeout=deadline_seconds,
                    verify=self._verify,
                    transport=httpx.AsyncHTTPTransport(
                        verify=self._verify, retries=0, trust_env=False
                    ),
                ) as client:
                    _install_log_filters()
                    async with client.stream(
                        "POST",
                        endpoint,
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {secret}",
                            "Accept-Encoding": "identity",
                        },
                    ) as response:
                        if not 200 <= response.status_code < 300:
                            retry_after = None
                            values = response.headers.get_list("Retry-After")
                            if len(values) == 1 and secret not in values[0]:
                                try:
                                    retry_after = TypeAdapter(RetryAfter).validate_python(values[0])
                                except ValidationError:
                                    pass
                            raise ProviderHttpError(response.status_code, retry_after)
                        if (
                            response.headers.get("Content-Encoding", "identity").lower()
                            != "identity"
                        ):
                            raise AppError(
                                "provider_encoding",
                                "Compressed provider responses are unsupported.",
                            )
                        content = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            if len(content) + len(chunk) > response_bytes:
                                raise AppError(
                                    "response_too_large",
                                    "Provider response exceeds the byte limit.",
                                )
                            content.extend(chunk)
                result = json.loads(content)
                if not isinstance(result, dict):
                    raise ValueError
                return result
        except (TimeoutError, httpx.TimeoutException):
            raise AppError("provider_timeout", "Provider request deadline exceeded.") from None
        except httpx.HTTPError:
            raise AppError("provider_connection", "Provider connection failed.") from None
        except (ValueError, UnicodeError, RecursionError):
            raise AppError("provider_response", "Invalid provider response.") from None
        finally:
            _provider_logging.reset(token)
