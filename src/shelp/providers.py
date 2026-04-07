from __future__ import annotations

import json
import urllib.error
import urllib.request

from pydantic import ValidationError

from .errors import ShelpError
from .models import ProviderSettings
from .utils import env_value, excerpt, json_excerpt


TIMEOUT_SECONDS = float(env_value("SHELP_TIMEOUT_SECONDS", "AI_HELP_TIMEOUT_SECONDS", default="90"))
ANTHROPIC_API_URL = env_value("ANTHROPIC_API_URL", default="https://api.anthropic.com/v1/messages")
OPENAI_API_URL = env_value("OPENAI_API_URL", default="https://api.openai.com/v1/chat/completions")
GEMINI_API_URL_BASE = env_value(
    "GEMINI_API_URL_BASE",
    default="https://generativelanguage.googleapis.com/v1beta/models",
)


def anthropic_messages(history: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{"role": entry["role"], "content": entry["content"]} for entry in history]


def openai_messages(system_prompt: str, history: list[dict[str, str]]) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend({"role": entry["role"], "content": entry["content"]} for entry in history)
    return messages


def gemini_contents(history: list[dict[str, str]]) -> list[dict[str, object]]:
    contents = []
    for entry in history:
        role = "model" if entry["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": entry["content"]}]})
    return contents


def extract_anthropic_text(response_payload: dict) -> str:
    content = response_payload.get("content")
    if not isinstance(content, list):
        raise ShelpError("Anthropic response did not include message content.", stage="reading the model response")

    parts = [
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    text = "\n".join(part for part in parts if part).strip()
    if not text:
        raise ShelpError("Anthropic returned an empty response.", stage="reading the model response")
    return text


def extract_openai_text(response_payload: dict) -> str:
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ShelpError("OpenAI response did not include choices.", stage="reading the model response")

    message = choices[0].get("message", {})
    refusal = message.get("refusal")
    if refusal:
        raise ShelpError(f"OpenAI refusal: {refusal}", stage="reading the model response")

    content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
        if text:
            return text
    elif isinstance(content, list):
        text_parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") in {"text", "output_text"}:
                text_value = item.get("text", "")
                if text_value:
                    text_parts.append(text_value)
        text = "\n".join(text_parts).strip()
        if text:
            return text

    raise ShelpError("OpenAI returned an empty response.", stage="reading the model response")


def extract_gemini_text(response_payload: dict) -> str:
    prompt_feedback = response_payload.get("promptFeedback", {})
    block_reason = prompt_feedback.get("blockReason")
    if block_reason:
        details = [f"Gemini blocked the prompt: {block_reason}"]
        safety_ratings = prompt_feedback.get("safetyRatings")
        if safety_ratings:
            details.append(f"safety_ratings={json_excerpt(safety_ratings, 600)}")
        details.append(f"raw_response={json_excerpt(response_payload, 1200)}")
        raise ShelpError(" | ".join(details), stage="reading the model response")

    candidates = response_payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ShelpError(
            f"Gemini response did not include candidates. raw_response={json_excerpt(response_payload, 1200)}",
            stage="reading the model response",
        )

    candidate = candidates[0]
    finish_reason = candidate.get("finishReason")
    if finish_reason == "SAFETY":
        details = [f"Gemini blocked the response for safety reasons. finish_reason={finish_reason}"]
        safety_ratings = candidate.get("safetyRatings")
        if safety_ratings:
            details.append(f"safety_ratings={json_excerpt(safety_ratings, 600)}")
        details.append(f"candidate={json_excerpt(candidate, 1200)}")
        raise ShelpError(" | ".join(details), stage="reading the model response")

    content = candidate.get("content", {})
    parts = content.get("parts", [])
    if not isinstance(parts, list):
        raise ShelpError(
            f"Gemini response did not include content parts. candidate={json_excerpt(candidate, 1200)}",
            stage="reading the model response",
        )

    text = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict) and part.get("text")).strip()
    if not text:
        response_id = response_payload.get("responseId")
        model_version = response_payload.get("modelVersion")
        usage = response_payload.get("usageMetadata")
        details = ["Gemini returned an empty text payload."]
        if finish_reason is not None:
            details.append(f"finish_reason={finish_reason}")
        if response_id:
            details.append(f"response_id={response_id}")
        if model_version:
            details.append(f"model_version={model_version}")
        if usage:
            details.append(f"usage={json_excerpt(usage, 600)}")
        if parts:
            details.append(f"parts={json_excerpt(parts, 1200)}")
        else:
            details.append("parts=[]")
        safety_ratings = candidate.get("safetyRatings")
        if safety_ratings:
            details.append(f"safety_ratings={json_excerpt(safety_ratings, 600)}")
        details.append(f"candidate={json_excerpt(candidate, 1200)}")
        raise ShelpError(" | ".join(details), stage="reading the model response")
    return text


def extract_text(provider: str, response_payload: dict) -> str:
    if provider == "anthropic":
        return extract_anthropic_text(response_payload)
    if provider == "openai":
        return extract_openai_text(response_payload)
    if provider == "gemini":
        return extract_gemini_text(response_payload)
    raise ShelpError(f"Unsupported provider '{provider}' while reading the model response.", stage="reading the model response")


def parse_structured_output(response_payload: dict, model_cls, *, stage: str, provider: str):
    if provider == "anthropic":
        stop_reason = response_payload.get("stop_reason")
        if stop_reason == "refusal":
            refusal_text = extract_text(provider, response_payload)
            raise ShelpError(f"Model refusal: {refusal_text}", stage=stage)
        if stop_reason == "max_tokens":
            partial_text = extract_text(provider, response_payload)
            raise ShelpError(f"Structured output was truncated by max_tokens. Partial response: {excerpt(partial_text, 1000)}", stage=stage)
    elif provider == "openai":
        choices = response_payload.get("choices", [])
        finish_reason = choices[0].get("finish_reason") if isinstance(choices, list) and choices else None
        if finish_reason == "length":
            partial_text = extract_text(provider, response_payload)
            raise ShelpError(f"Structured output was truncated by max_tokens. Partial response: {excerpt(partial_text, 1000)}", stage=stage)
    elif provider == "gemini":
        candidates = response_payload.get("candidates", [])
        finish_reason = candidates[0].get("finishReason") if isinstance(candidates, list) and candidates else None
        if finish_reason == "MAX_TOKENS":
            partial_text = extract_text(provider, response_payload)
            raise ShelpError(f"Structured output was truncated by max_tokens. Partial response: {excerpt(partial_text, 1000)}", stage=stage)

    response_text = extract_text(provider, response_payload)
    try:
        parsed_json = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise ShelpError(f"Unable to parse structured JSON: {exc}. Raw model reply: {excerpt(response_text, 1000)}", stage=stage) from exc

    try:
        return model_cls.model_validate(parsed_json)
    except ValidationError as exc:
        raise ShelpError(f"Structured output validation failed: {exc}", stage=stage) from exc


def build_provider_payload(
    provider_settings: ProviderSettings,
    *,
    system_prompt: str,
    history: list[dict[str, str]],
    schema: dict,
    schema_name: str,
    max_tokens: int,
    temperature: float,
    stream: bool,
) -> tuple[str, dict[str, str], dict]:
    provider = provider_settings.provider

    if provider == "anthropic":
        payload = {
            "model": provider_settings.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": anthropic_messages(history),
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": schema,
                }
            },
        }
        if stream:
            payload["stream"] = True
        headers = {
            "content-type": "application/json",
            "x-api-key": provider_settings.api_key,
            "anthropic-version": "2023-06-01",
        }
        if stream:
            headers["accept"] = "text/event-stream"
        return ANTHROPIC_API_URL, headers, payload

    if provider == "openai":
        payload = {
            "model": provider_settings.model,
            "messages": openai_messages(system_prompt, history),
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                },
            },
        }
        if stream:
            payload["stream"] = True
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {provider_settings.api_key}",
        }
        return OPENAI_API_URL, headers, payload

    if provider == "gemini":
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": gemini_contents(history),
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
            },
        }
        suffix = ":streamGenerateContent?alt=sse" if stream else ":generateContent"
        url = f"{GEMINI_API_URL_BASE.rstrip('/')}/{provider_settings.model}{suffix}"
        headers = {
            "content-type": "application/json",
            "x-goog-api-key": provider_settings.api_key,
        }
        if stream:
            headers["accept"] = "text/event-stream"
        return url, headers, payload

    raise ShelpError(f"Unsupported provider '{provider}' while building the request payload.", stage="building the model request")


def call_provider(provider_settings: ProviderSettings, payload_spec: tuple[str, dict[str, str], dict]) -> dict:
    url, headers, payload = payload_spec
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ShelpError(render_http_error(exc), stage=f"calling the {provider_settings.provider.title()} API") from exc
    except urllib.error.URLError as exc:
        raise ShelpError(f"Network error: {exc.reason}", stage=f"calling the {provider_settings.provider.title()} API") from exc


def stream_provider(provider_settings: ProviderSettings, payload_spec: tuple[str, dict[str, str], dict]):
    url, headers, payload = payload_spec
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            if provider_settings.provider == "anthropic":
                yield from parse_anthropic_sse_stream(response)
            elif provider_settings.provider == "openai":
                yield from parse_openai_sse_stream(response)
            elif provider_settings.provider == "gemini":
                yield from parse_gemini_sse_stream(response)
            else:
                raise ShelpError(
                    f"Unsupported provider '{provider_settings.provider}' while streaming the response.",
                    stage="streaming the conversational reply",
                )
    except urllib.error.HTTPError as exc:
        raise ShelpError(render_http_error(exc), stage=f"starting the streaming {provider_settings.provider.title()} response") from exc
    except urllib.error.URLError as exc:
        raise ShelpError(f"Network error: {exc.reason}", stage=f"starting the streaming {provider_settings.provider.title()} response") from exc


def parse_anthropic_sse_stream(response):
    event_name = None
    data_lines = []

    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
        if line.endswith("\r"):
            line = line[:-1]

        if not line:
            yield from process_anthropic_sse_event(event_name, data_lines)
            event_name = None
            data_lines = []
            continue

        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    if data_lines:
        yield from process_anthropic_sse_event(event_name, data_lines)


def process_anthropic_sse_event(event_name: str | None, data_lines: list[str]):
    data = "\n".join(data_lines).strip()
    if not data or data == "[DONE]":
        return

    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ShelpError(f"Unable to decode streamed response: {exc}", stage="decoding the streamed reply") from exc

    event_type = payload.get("type") or event_name
    if event_type == "error":
        error = payload.get("error", {})
        message = error.get("message") or data
        raise ShelpError(f"Anthropic streaming error: {message}", stage="streaming the conversational reply")

    if event_type != "content_block_delta":
        return

    delta = payload.get("delta", {})
    if delta.get("type") == "text_delta":
        yield delta.get("text", "")


def parse_openai_sse_stream(response):
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
        if line.endswith("\r"):
            line = line[:-1]
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ShelpError(f"Unable to decode streamed OpenAI response: {exc}", stage="decoding the streamed reply") from exc

        choices = payload.get("choices", [])
        if not isinstance(choices, list) or not choices:
            continue

        delta = choices[0].get("delta", {})
        content = delta.get("content")
        if isinstance(content, str):
            yield content
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                    text_value = item.get("text", "")
                    if text_value:
                        yield text_value


def parse_gemini_sse_stream(response):
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
        if line.endswith("\r"):
            line = line[:-1]
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ShelpError(f"Unable to decode streamed Gemini response: {exc}", stage="decoding the streamed reply") from exc

        candidates = payload.get("candidates", [])
        if not isinstance(candidates, list) or not candidates:
            continue

        candidate = candidates[0]
        if candidate.get("finishReason") == "SAFETY":
            raise ShelpError("Gemini blocked the streamed response for safety reasons.", stage="streaming the conversational reply")

        content = candidate.get("content", {})
        parts = content.get("parts", [])
        if not isinstance(parts, list):
            continue
        for part in parts:
            if isinstance(part, dict):
                text_value = part.get("text", "")
                if text_value:
                    yield text_value


def render_http_error(exc: urllib.error.HTTPError) -> str:
    body = exc.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = None

    parts = [f"API error ({exc.code} {exc.reason})", f"url={exc.url}"]

    request_id = exc.headers.get("request-id") or exc.headers.get("anthropic-request-id")
    if request_id:
        parts.append(f"request_id={request_id}")

    if isinstance(payload, dict):
        error = payload.get("error", {})
        if isinstance(error, dict):
            message = error.get("message")
            if message:
                parts.append(f"message={message}")
                return " | ".join(parts)

    if body:
        parts.append(f"body={excerpt(body, 1200)}")
        return " | ".join(parts)

    return " | ".join(parts)
