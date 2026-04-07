from __future__ import annotations

import sys

from .config import (
    MODEL_SUGGESTIONS,
    ensure_provider_api_key,
    load_config,
    resolve_model_name,
    resolve_provider_name,
    resolve_provider_settings,
    save_config,
)
from .errors import ShelpError
from .models import ChoiceOption, ConversationalReplyOutput, DecisionOutput, ProviderSettings
from .prompts import (
    FRESH_DECISION_SYSTEM_TEMPLATE,
    MESSAGE_SYSTEM_TEMPLATE,
    PREFILLED_DECISION_SYSTEM_TEMPLATE,
    REPAIR_DECISION_SYSTEM_TEMPLATE,
)
from .providers import build_provider_payload, call_provider, parse_structured_output, stream_provider
from .repair import infer_repair_target, repair_context_lines, repair_intro_message
from .ui import TerminalUI
from .utils import (
    build_shared_prompt_context,
    json_schema_for,
    list_filenames_in_cwd,
    normalize_command,
    parse_recent_commands,
    render_exception_report,
)


ACTION_PREFIX = "__SHELP_ACTION__:"


def render_recoverable_session_error(ui: TerminalUI, exc: BaseException, *, default_stage: str | None = None) -> None:
    ui.agent_line("Woops. That did not work. What should we do?", "error")
    for line in render_exception_report(exc, default_stage=default_stage):
        ui.agent_line(line, "error")


def show_slash_help(ui: TerminalUI) -> None:
    ui.agent_line("Available slash commands:", "normal")
    ui.agent_line("/help shows this slash-command list.", "normal")
    ui.agent_line("/conf opens an interactive configuration menu for provider, model, and API key.", "normal")


def configure_provider(ui: TerminalUI, current_settings: ProviderSettings) -> ProviderSettings | None:
    config = load_config()
    current_provider = resolve_provider_name(config)
    provider_options = [
        ChoiceOption("Gemini", "gemini", "Google Gemini provider"),
        ChoiceOption("OpenAI", "openai", "OpenAI provider"),
        ChoiceOption("Anthropic", "anthropic", "Anthropic Claude provider"),
    ]
    provider_default_index = next(
        (index for index, option in enumerate(provider_options) if option.value == current_provider),
        0,
    )
    provider_choice = ui.choose_option(
        "SHelp Configuration",
        provider_options,
        intro="Select the model provider I should use for this helper session.",
        default_index=provider_default_index,
    )
    selected_provider = provider_choice.value

    configured_model = resolve_model_name(config, selected_provider)
    model_options: list[ChoiceOption] = []
    seen_models: set[str] = set()
    for model_name in [configured_model, *MODEL_SUGGESTIONS[selected_provider]]:
        if not model_name or model_name in seen_models:
            continue
        seen_models.add(model_name)
        description = "Current saved model" if model_name == configured_model else "Suggested model"
        model_options.append(ChoiceOption(model_name, model_name, description))
    model_options.append(ChoiceOption("Enter a custom model name", "__custom__", "Type the model name yourself"))
    model_choice = ui.choose_option(
        f"{selected_provider.title()} Model",
        model_options,
        intro="Select which model I should call for this provider.",
        default_index=0,
    )

    if model_choice.value == "__custom__":
        ui.agent_line("Type the exact model name you want me to use.", "normal")
        try:
            custom_model = ui.prompt_user().strip()
        except EOFError:
            ui.agent_line("I did not receive a custom model name, so I kept your existing configuration.", "warning")
            return current_settings
        except KeyboardInterrupt:
            ui.agent_line("I stopped before saving a custom model name, so I kept your existing configuration.", "warning")
            return current_settings

        if not custom_model:
            ui.agent_line("I need a non-empty model name if you want to enter a custom one.", "error")
            return current_settings
        selected_model = custom_model
    else:
        selected_model = model_choice.value

    config["provider"] = selected_provider
    config[f"{selected_provider}_model"] = selected_model
    api_key = ensure_provider_api_key(ui, config, selected_provider)
    if not api_key:
        return current_settings

    save_config(config)
    updated_settings = ProviderSettings(provider=selected_provider, model=selected_model, api_key=api_key)
    ui.set_provider_badge(updated_settings)
    ui.agent_line(
        f"I updated the helper to use {selected_provider} with model {selected_model}.",
        "success",
    )
    return updated_settings


def handle_slash_command(
    ui: TerminalUI,
    user_message: str,
    provider_settings: ProviderSettings,
) -> tuple[bool, ProviderSettings]:
    if user_message == "/help":
        show_slash_help(ui)
        return True, provider_settings

    if user_message == "/conf":
        updated_settings = configure_provider(ui, provider_settings)
        return True, updated_settings or provider_settings

    return False, provider_settings


def build_decision_payload(
    provider_settings: ProviderSettings,
    history: list[dict[str, str]],
    *,
    shared_prompt_context: str,
    prefilled: bool,
    repair_mode: bool,
) -> tuple[str, dict[str, str], dict]:
    if repair_mode:
        system_prompt = REPAIR_DECISION_SYSTEM_TEMPLATE.format(shared_prompt_context=shared_prompt_context)
    else:
        system_prompt = (PREFILLED_DECISION_SYSTEM_TEMPLATE if prefilled else FRESH_DECISION_SYSTEM_TEMPLATE).format(
            shared_prompt_context=shared_prompt_context,
        )
    return build_provider_payload(
        provider_settings,
        system_prompt=system_prompt,
        history=history,
        schema=json_schema_for(DecisionOutput),
        schema_name="decision_output",
        max_tokens=320,
        temperature=0,
        stream=False,
    )


def build_message_payload(
    provider_settings: ProviderSettings,
    history: list[dict[str, str]],
    message_instruction: str,
    shared_prompt_context: str,
) -> tuple[str, dict[str, str], dict]:
    system_prompt = MESSAGE_SYSTEM_TEMPLATE.format(
        shared_prompt_context=shared_prompt_context,
        instruction=message_instruction,
    )
    return build_provider_payload(
        provider_settings,
        system_prompt=system_prompt,
        history=history,
        schema=json_schema_for(ConversationalReplyOutput),
        schema_name="conversational_reply_output",
        max_tokens=512,
        temperature=0.2,
        stream=True,
    )


def decide_next_action(
    provider_settings: ProviderSettings,
    history: list[dict[str, str]],
    *,
    shared_prompt_context: str,
    prefilled: bool,
    repair_mode: bool,
    ui: TerminalUI,
) -> dict[str, str]:
    payload = build_decision_payload(
        provider_settings,
        history,
        shared_prompt_context=shared_prompt_context,
        prefilled=prefilled,
        repair_mode=repair_mode,
    )
    with ui.start_processing_indicator("Thinking..."):
        response_payload = call_provider(provider_settings, payload)
    decision = parse_structured_output(
        response_payload,
        DecisionOutput,
        stage="parsing the command-or-message decision",
        provider=provider_settings.provider,
    )

    if decision.mode == "command":
        command = normalize_command(decision.command)
        if not command:
            raise ShelpError("The model chose command mode but returned no command.", stage="extracting the proposed command")
        return {
            "mode": "command",
            "command": command,
            "message_instruction": "",
            "rationale": decision.rationale.strip(),
        }

    instruction = decision.message_instruction.strip()
    if not instruction:
        instruction = "Answer briefly or ask one pointed clarifying question."
    return {"mode": "message", "command": "", "message_instruction": instruction, "rationale": ""}


def stream_conversational_reply(
    provider_settings: ProviderSettings,
    history: list[dict[str, str]],
    message_instruction: str,
    shared_prompt_context: str,
    ui: TerminalUI,
) -> str:
    payload = build_message_payload(provider_settings, history, message_instruction, shared_prompt_context)
    raw_response = ui.stream_structured_message(stream_provider(provider_settings, payload))
    try:
        reply = ConversationalReplyOutput.model_validate_json(raw_response)
    except Exception as exc:
        raise ShelpError(f"Structured output validation failed for the conversational reply: {exc}", stage="reading the conversational reply") from exc
    return reply.message.strip()


def output_result(action: str, buffer_text: str) -> None:
    sys.stdout.write(f"{ACTION_PREFIX}{action}\n")
    sys.stdout.write(buffer_text)


def run_session(
    initial_buffer: str,
    provider_settings: ProviderSettings,
    ui: TerminalUI,
    *,
    session_mode: str = "default",
) -> tuple[str, str]:
    original_buffer = initial_buffer
    history: list[dict[str, str]] = []
    recent_commands = parse_recent_commands()
    repair_target = infer_repair_target(recent_commands, explicit_command=initial_buffer) if session_mode == "repair" else None
    cwd_filenames = list_filenames_in_cwd()
    shared_prompt_context = build_shared_prompt_context(
        recent_commands,
        cwd_filenames,
        extra_lines=repair_context_lines(repair_target) if session_mode == "repair" else None,
    )
    prefilled_flow = bool(initial_buffer.strip())

    if session_mode == "repair":
        if repair_target is not None:
            ui.prefilled_line(repair_target.command)
            ui.agent_line(repair_intro_message(repair_target))
            pending_user_message = repair_target.command
        else:
            ui.agent_line("I could not find a recent command to repair. Paste the command or say what you were trying to do.")
            pending_user_message = None
    elif prefilled_flow:
        ui.prefilled_line(initial_buffer)
        ui.agent_line("Let me think about that...")
        pending_user_message = initial_buffer
    else:
        ui.agent_line("What would you like to do?")
        pending_user_message = None

    while True:
        if pending_user_message is None:
            try:
                pending_user_message = ui.prompt_user()
            except EOFError:
                ui.agent_line("I did not get another request, so I am leaving your prompt unchanged.", "warning")
                return "edit", original_buffer
            except KeyboardInterrupt:
                ui.agent_line("I stopped the conversation and left your prompt unchanged.", "warning")
                return "edit", original_buffer

        user_message = pending_user_message.strip()
        pending_user_message = None

        if not user_message:
            ui.agent_line("I did not get another request, so I am leaving your prompt unchanged.", "warning")
            return "edit", original_buffer

        if user_message.startswith("/"):
            try:
                handled, provider_settings = handle_slash_command(ui, user_message, provider_settings)
            except ShelpError as exc:
                render_recoverable_session_error(ui, exc)
                pending_user_message = None
                continue
            except Exception as exc:
                render_recoverable_session_error(ui, exc, default_stage="handling a slash command")
                pending_user_message = None
                continue

            if handled:
                pending_user_message = None
                continue

        history.append({"role": "user", "content": user_message})
        try:
            decision = decide_next_action(
                provider_settings,
                history,
                shared_prompt_context=shared_prompt_context,
                prefilled=session_mode != "repair" and prefilled_flow and len(history) == 1,
                repair_mode=session_mode == "repair",
                ui=ui,
            )
        except ShelpError as exc:
            render_recoverable_session_error(
                ui,
                exc if exc.stage is not None else ShelpError(str(exc), stage="deciding whether to generate a command"),
            )
            pending_user_message = None
            continue
        except Exception as exc:
            render_recoverable_session_error(ui, exc, default_stage="deciding whether to generate a command")
            pending_user_message = None
            continue

        if decision["mode"] == "command":
            proposed_command = decision["command"]
            rationale = decision["rationale"].strip()
            if rationale:
                ui.agent_line(rationale)

            assistant_lines = [f"Proposed command: {proposed_command}"]
            if rationale:
                assistant_lines.append(f"Rationale: {rationale}")
            history.append({"role": "assistant", "content": "\n".join(assistant_lines)})
            try:
                review_action = ui.review_proposed_command(proposed_command)
            except ShelpError as exc:
                render_recoverable_session_error(
                    ui,
                    exc if exc.stage is not None else ShelpError(str(exc), stage="showing the proposed command review"),
                )
                pending_user_message = None
                continue
            except Exception as exc:
                render_recoverable_session_error(ui, exc, default_stage="showing the proposed command review")
                pending_user_message = None
                continue
            if review_action == "run":
                return "run", proposed_command

            pending_user_message = None
            continue

        try:
            assistant_message = stream_conversational_reply(
                provider_settings=provider_settings,
                history=history,
                message_instruction=decision["message_instruction"],
                shared_prompt_context=shared_prompt_context,
                ui=ui,
            )
        except ShelpError as exc:
            render_recoverable_session_error(
                ui,
                exc if exc.stage is not None else ShelpError(str(exc), stage="streaming a conversational reply"),
            )
            pending_user_message = None
            continue
        except Exception as exc:
            render_recoverable_session_error(ui, exc, default_stage="streaming a conversational reply")
            pending_user_message = None
            continue
        if assistant_message:
            history.append({"role": "assistant", "content": assistant_message})


def run_cli_session(initial_buffer: str, *, session_mode: str = "default") -> int:
    ui = TerminalUI()
    provider_settings = resolve_provider_settings(ui)
    if not provider_settings:
        output_result("edit", initial_buffer)
        return 0
    ui.set_provider_badge(provider_settings)

    try:
        action, next_buffer = run_session(initial_buffer, provider_settings, ui, session_mode=session_mode)
    except ShelpError as exc:
        for line in render_exception_report(exc):
            ui.agent_line(line, "error")
        output_result("edit", initial_buffer)
        return 0
    except KeyboardInterrupt:
        ui.agent_line("I stopped the conversation and left your prompt unchanged.", "warning")
        output_result("edit", initial_buffer)
        return 0
    except Exception as exc:
        for line in render_exception_report(exc, default_stage="running the helper session"):
            ui.agent_line(line, "error")
        output_result("edit", initial_buffer)
        return 0

    output_result(action, next_buffer)
    return 0
