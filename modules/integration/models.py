"""Model adapters: external and local language models behind one interface (ADR-0006).

``analysis`` reaches a model only through this file. The adapter transports a request and returns the
model's turn; it holds no prompt and makes no decision about tools or evidence.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

from core.config import get_settings
from core.errors import ProviderError
from modules.logging import Severity, log

ANTHROPIC_HOST = "api.anthropic.com"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_OUTPUT_TOKENS = 16000  # non-streaming requests stay within the SDK's HTTP timeout at this size


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ModelTurn:
    stop_reason: str
    content: list[Any]  # provider blocks, passed back unchanged on the next request
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    refusal: dict[str, Any] | None = None


class ModelAdapter(Protocol):
    name: str
    model_id: str
    external: bool  # True when data leaves the deployment

    def complete(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], schema: dict[str, Any]
    ) -> ModelTurn: ...


class AnthropicModel:
    """Claude through the Anthropic API. Thinking is adaptive (the model default); depth is set by effort."""

    name = "anthropic"
    external = True

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise ProviderError("No model provider is configured", code="model_not_configured")
        if ANTHROPIC_HOST not in settings.outbound_allow_hosts:
            log("integration", "outbound.refused", Severity.SECURITY, host=ANTHROPIC_HOST)
            raise ProviderError("The model provider is not on the outbound allow-list", code="destination_refused")
        self.model_id = settings.ai_model
        self._effort = settings.ai_effort
        # The base URL is pinned so an environment variable cannot redirect prompts to another host.
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key, base_url=f"https://{ANTHROPIC_HOST}", max_retries=2, timeout=300.0
        )

    def complete(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], schema: dict[str, Any]
    ) -> ModelTurn:
        try:
            response = self._client.beta.messages.create(
                model=self.model_id,
                max_tokens=MAX_OUTPUT_TOKENS,
                # The system prompt and tool list are stable across a run, so they are cached.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=tools,
                messages=messages,
                output_config={"effort": self._effort, "format": {"type": "json_schema", "schema": schema}},
                # A policy decline is re-run on the provider's default fallback model inside the same call.
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as exc:
            raise ProviderError("The model provider rejected the API key", code="model_auth_failed") from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderError("The API key may not use this model", code="model_not_permitted") from exc
        except anthropic.NotFoundError as exc:
            raise ProviderError(
                "The configured model does not exist", code="model_not_found", details={"model": self.model_id}
            ) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError("The model provider is rate limiting requests", code="model_rate_limited") from exc
        except anthropic.BadRequestError as exc:
            log("integration", "model.bad_request", Severity.ERROR, model=self.model_id, status=exc.status_code)
            raise ProviderError("The model provider rejected the request", code="model_bad_request") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(
                "The model provider failed", code="model_unavailable", details={"status": exc.status_code}
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("The model provider could not be reached", code="model_unavailable") from exc

        calls = [
            ToolCall(id=b.id, name=b.name, input=dict(b.input or {})) for b in response.content if b.type == "tool_use"
        ]
        text = "".join(b.text for b in response.content if b.type == "text")
        usage = response.usage
        refusal = None
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            refusal = {"category": getattr(details, "category", None)}
        return ModelTurn(
            stop_reason=response.stop_reason or "",
            content=list(response.content),
            text=text,
            tool_calls=calls,
            model=response.model,  # the model that served the turn, which differs after a fallback
            usage={
                "input_tokens": usage.input_tokens or 0,
                "output_tokens": usage.output_tokens or 0,
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
            },
            refusal=refusal,
        )


def default_model() -> ModelAdapter | None:
    """The configured external model, or ``None`` when the deployment runs without one."""
    return AnthropicModel() if get_settings().anthropic_api_key else None
