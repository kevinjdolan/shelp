from __future__ import annotations

import os
import re
import textwrap
from pathlib import Path

from .config import resolve_hotkey_bindings
from .errors import ShelpError
from .hotkeys import HotkeyBindings, bash_hotkey_sequence, fish_hotkey_sequence, zsh_hotkey_sequence


SUPPORTED_SHELLS = ("fish", "zsh", "bash")
MANAGED_START = "# >>> shelp >>>"
MANAGED_END = "# <<< shelp <<<"


def normalize_shell_name(shell_name: str) -> str:
    normalized = shell_name.strip().lower()
    if normalized not in SUPPORTED_SHELLS:
        supported = ", ".join(SUPPORTED_SHELLS)
        raise ShelpError(f"Unsupported shell '{shell_name}'. Supported shells: {supported}.")
    return normalized


def current_shell_name() -> str | None:
    shell = Path(os.environ.get("SHELL", "")).name.lower()
    if shell in SUPPORTED_SHELLS:
        return shell
    return None


def default_shells_to_install() -> list[str]:
    shell = current_shell_name()
    return [shell] if shell else ["fish"]


def shell_init(shell_name: str) -> str:
    shell_name = normalize_shell_name(shell_name)
    hotkeys = resolve_hotkey_bindings()
    if shell_name == "fish":
        return _fish_init(hotkeys)
    if shell_name == "zsh":
        return _zsh_init(hotkeys)
    if shell_name == "bash":
        return _bash_init(hotkeys)
    raise ShelpError(f"Unsupported shell '{shell_name}'.")


def install_shell_loader(shell_name: str, *, force: bool = False) -> list[Path]:
    shell_name = normalize_shell_name(shell_name)
    if shell_name == "fish":
        path = Path.home() / ".config" / "fish" / "conf.d" / "shelp.fish"
        content = textwrap.dedent(
            """\
            # Managed by shelp.
            if status is-interactive; and type -q shelp
                shelp init fish | source
            end
            """
        )
        return [path] if _write_text_if_changed(path, content, force=force) else []

    if shell_name == "zsh":
        path = Path.home() / ".zshrc"
        content = _replace_or_append_managed_block(_read_text(path), _loader_block("zsh"))
        return [path] if _write_text_if_changed(path, content, force=force) else []

    if shell_name == "bash":
        changed_paths: list[Path] = []
        bashrc_path = Path.home() / ".bashrc"
        bashrc_content = _replace_or_append_managed_block(_read_text(bashrc_path), _loader_block("bash"))
        if _write_text_if_changed(bashrc_path, bashrc_content, force=force):
            changed_paths.append(bashrc_path)

        bash_profile_path = Path.home() / ".bash_profile"
        existing_profile = _read_text(bash_profile_path)
        if ".bashrc" not in existing_profile:
            bash_profile_content = _replace_or_append_managed_block(existing_profile, _bash_profile_block())
            if _write_text_if_changed(bash_profile_path, bash_profile_content, force=force):
                changed_paths.append(bash_profile_path)
        return changed_paths

    raise ShelpError(f"Unsupported shell '{shell_name}'.")


def _loader_block(shell_name: str) -> str:
    return textwrap.dedent(
        f"""\
        {MANAGED_START}
        if command -v shelp >/dev/null 2>&1; then
          eval "$(shelp init {shell_name})"
        fi
        {MANAGED_END}
        """
    )


def _bash_profile_block() -> str:
    return textwrap.dedent(
        f"""\
        {MANAGED_START}
        if [ -f "$HOME/.bashrc" ]; then
          . "$HOME/.bashrc"
        fi
        {MANAGED_END}
        """
    )


def _replace_or_append_managed_block(existing_text: str, block: str) -> str:
    pattern = re.compile(
        rf"{re.escape(MANAGED_START)}.*?{re.escape(MANAGED_END)}\n?",
        re.DOTALL,
    )
    if pattern.search(existing_text):
        updated = pattern.sub(block, existing_text, count=1)
    else:
        separator = "" if not existing_text or existing_text.endswith("\n") else "\n"
        updated = f"{existing_text}{separator}{block}"
    if not updated.endswith("\n"):
        updated += "\n"
    return updated


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_text_if_changed(path: Path, content: str, *, force: bool = False) -> bool:
    if path.exists() and not force and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _fish_init(hotkeys: HotkeyBindings) -> str:
    script = textwrap.dedent(
        r"""
        if status is-interactive
            if not set -q __shelp_fish_initialized
                set -g __shelp_fish_initialized 1

                function __shelp_capture_preexec --on-event fish_preexec
                    set -g __shelp_pending_command (string replace -a \n ' ' -- "$argv[1]")
                end

                function __shelp_capture_postexec --on-event fish_postexec
                    if not set -q __shelp_pending_command[1]
                        return
                    end

                    set -l command_text (string trim -- "$__shelp_pending_command[1]")
                    set -e __shelp_pending_command

                    if test -z "$command_text"
                        return
                    end

                    set -l exit_code $status
                    set -l normalized_command (string replace -a \t '    ' -- "$command_text")
                    set -l entry "$exit_code\t$normalized_command"
                    set -ga __shelp_recent_commands $entry

                    set -l entry_count (count $__shelp_recent_commands)
                    if test $entry_count -gt 10
                        set -l start_index (math "$entry_count - 9")
                        set -g __shelp_recent_commands $__shelp_recent_commands[$start_index..$entry_count]
                    end
                end

                function __shelp_run_worker --argument-names worker_mode
                    set -l instruction (commandline -b)
                    set -l stdout_file (mktemp -t shelp_stdout)

                    commandline -f repaint
                    printf "\n" 1>&2

                    set -l recent_commands_payload (string join \x1e -- $__shelp_recent_commands)
                    if test "$worker_mode" = repair
                        env SHELP_RECENT_COMMANDS="$recent_commands_payload" shelp repair --initial-buffer "$instruction" >"$stdout_file"
                    else
                        env SHELP_RECENT_COMMANDS="$recent_commands_payload" shelp session --initial-buffer "$instruction" >"$stdout_file"
                    end
                    set -l worker_status $status
                    set -l action_line (head -n 1 "$stdout_file")
                    set -l next_buffer (tail -n +2 "$stdout_file")
                    command rm -f -- "$stdout_file"
                    set -l next_action edit

                    if string match -qr '^__SHELP_ACTION__:' -- "$action_line"
                        set next_action (string replace '__SHELP_ACTION__:' '' -- "$action_line")
                    else if test -n "$action_line"
                        set next_buffer (string join \n -- $action_line $next_buffer)
                    end

                    if test $worker_status -ne 0
                        printf "shelp exited with status %s\n" "$worker_status" 1>&2
                        set next_buffer "$instruction"
                        set next_action edit
                    end

                    commandline -r -- "$next_buffer"
                    commandline -f repaint
                    if test "$next_action" = run
                        commandline -f execute
                    end
                    return $worker_status
                end

                function __shelp_translate_buffer
                    __shelp_run_worker translate
                end

                function __shelp_repair_command
                    __shelp_run_worker repair
                end

                function __shelp_bind_keys
                    bind -M default __TRANSLATE_BINDING__ __shelp_translate_buffer
                    bind -M insert __TRANSLATE_BINDING__ __shelp_translate_buffer
                    bind -M visual __TRANSLATE_BINDING__ __shelp_translate_buffer
                    bind -M default __REPAIR_BINDING__ __shelp_repair_command
                    bind -M insert __REPAIR_BINDING__ __shelp_repair_command
                    bind -M visual __REPAIR_BINDING__ __shelp_repair_command
                end

                if functions -q fish_user_key_bindings; and not functions -q __shelp_original_fish_user_key_bindings
                    functions -c fish_user_key_bindings __shelp_original_fish_user_key_bindings
                end

                function fish_user_key_bindings
                    if functions -q __shelp_original_fish_user_key_bindings
                        __shelp_original_fish_user_key_bindings
                    end

                    __shelp_bind_keys
                end

                __shelp_bind_keys
            end
        end
        """
    ).lstrip("\n")
    return script.replace("__TRANSLATE_BINDING__", fish_hotkey_sequence(hotkeys.translate)).replace(
        "__REPAIR_BINDING__",
        fish_hotkey_sequence(hotkeys.repair),
    )


def _zsh_init(hotkeys: HotkeyBindings) -> str:
    script = textwrap.dedent(
        r"""
        if [[ -o interactive && -z "${__SHELP_ZSH_INITIALIZED:-}" ]]; then
          typeset -g __SHELP_ZSH_INITIALIZED=1
          typeset -ga __shelp_recent_commands=()

          autoload -Uz add-zsh-hook

          __shelp_preexec() {
            typeset -g __shelp_pending_command="${1//$'\n'/ }"
            typeset -g __shelp_pending_command="${__shelp_pending_command//$'\t'/    }"
          }

          __shelp_precmd() {
            emulate -L zsh
            local exit_code=$?
            local command_text="${__shelp_pending_command:-}"
            unset __shelp_pending_command

            [[ -n "$command_text" ]] || return 0

            __shelp_recent_commands+=("${exit_code}"$'\t'"${command_text}")
            if (( ${#__shelp_recent_commands[@]} > 10 )); then
              __shelp_recent_commands=("${__shelp_recent_commands[@]: -10}")
            fi
            return 0
          }

          __shelp_run_worker() {
            emulate -L zsh
            setopt localoptions no_aliases

            local worker_mode="$1"
            local instruction="$BUFFER"
            local stdout_file action_line next_buffer next_action recent_commands_payload worker_status

            stdout_file="$(mktemp "${TMPDIR:-/tmp}/shelp.XXXXXX")" || return 1
            recent_commands_payload="${(j:\x1e:)__shelp_recent_commands}"

            zle -I
            print -u2

            if [[ "$worker_mode" == repair ]]; then
              SHELP_RECENT_COMMANDS="$recent_commands_payload" shelp repair --initial-buffer "$instruction" >! "$stdout_file"
            else
              SHELP_RECENT_COMMANDS="$recent_commands_payload" shelp session --initial-buffer "$instruction" >! "$stdout_file"
            fi
            worker_status=$?
            action_line="$(head -n 1 "$stdout_file")"
            next_buffer="$(tail -n +2 "$stdout_file")"
            rm -f -- "$stdout_file"
            next_action=edit

            if [[ "$action_line" == __SHELP_ACTION__:* ]]; then
              next_action="${action_line#__SHELP_ACTION__:}"
            elif [[ -n "$action_line" ]]; then
              next_buffer="${action_line}"$'\n'"${next_buffer}"
            fi

            if (( worker_status != 0 )); then
              zle -M "shelp exited with status $worker_status"
              BUFFER="$instruction"
              CURSOR=${#BUFFER}
              zle redisplay
              return $worker_status
            fi

            BUFFER="$next_buffer"
            CURSOR=${#BUFFER}

            if [[ "$next_action" == "run" ]]; then
              zle accept-line
            else
              zle redisplay
            fi
          }

          __shelp_translate_widget() {
            __shelp_run_worker translate
          }

          __shelp_repair_widget() {
            __shelp_run_worker repair
          }

          add-zsh-hook preexec __shelp_preexec
          add-zsh-hook precmd __shelp_precmd
          zle -N __shelp_translate_widget
          zle -N __shelp_repair_widget
          bindkey '__TRANSLATE_BINDING__' __shelp_translate_widget
          bindkey '__REPAIR_BINDING__' __shelp_repair_widget
        fi
        """
    ).lstrip("\n")
    return script.replace("__TRANSLATE_BINDING__", zsh_hotkey_sequence(hotkeys.translate)).replace(
        "__REPAIR_BINDING__",
        zsh_hotkey_sequence(hotkeys.repair),
    )


def _bash_init(hotkeys: HotkeyBindings) -> str:
    script = textwrap.dedent(
        r"""
        if [[ $- == *i* && -z "${__SHELP_BASH_INITIALIZED:-}" ]]; then
          __SHELP_BASH_INITIALIZED=1
          __shelp_recent_commands=()
          __shelp_last_history_num=""

          __shelp_capture_command() {
            local exit_code=$?
            local hist_line hist_num command_text

            hist_line="$(HISTTIMEFORMAT= history 1)"
            [[ -n "$hist_line" ]] || return "$exit_code"

            hist_line="${hist_line#"${hist_line%%[![:space:]]*}"}"
            hist_num="${hist_line%%[[:space:]]*}"
            command_text="${hist_line#"$hist_num"}"
            command_text="${command_text#"${command_text%%[![:space:]]*}"}"

            [[ -n "$hist_num" ]] || return "$exit_code"
            if [[ "$hist_num" == "${__shelp_last_history_num:-}" ]]; then
              return "$exit_code"
            fi

            __shelp_last_history_num="$hist_num"
            command_text="${command_text//$'\n'/ }"
            command_text="${command_text//$'\t'/    }"
            [[ -n "$command_text" ]] || return "$exit_code"

            __shelp_recent_commands+=("${exit_code}"$'\t'"${command_text}")
            if ((${#__shelp_recent_commands[@]} > 10)); then
              __shelp_recent_commands=("${__shelp_recent_commands[@]:${#__shelp_recent_commands[@]}-10}")
            fi
            return "$exit_code"
          }

          __shelp_append_prompt_command() {
            local prompt_declaration
            prompt_declaration="$(declare -p PROMPT_COMMAND 2>/dev/null || true)"
            if [[ "$prompt_declaration" == "declare -a"* ]]; then
              local existing
              for existing in "${PROMPT_COMMAND[@]}"; do
                [[ "$existing" == "__shelp_capture_command" ]] && return 0
              done
              PROMPT_COMMAND=(__shelp_capture_command "${PROMPT_COMMAND[@]}")
              return 0
            fi

            case ";${PROMPT_COMMAND:-};" in
              *";__shelp_capture_command;"*) ;;
              *)
                if [[ -n "${PROMPT_COMMAND:-}" ]]; then
                  PROMPT_COMMAND="__shelp_capture_command;${PROMPT_COMMAND}"
                else
                  PROMPT_COMMAND="__shelp_capture_command"
                fi
                ;;
            esac
          }

          __shelp_run_worker() {
            local worker_mode="$1"
            local instruction="$READLINE_LINE"
            local stdout_file action_line next_buffer next_action worker_status recent_commands_payload
            local entry separator run_status

            stdout_file="$(mktemp "${TMPDIR:-/tmp}/shelp.XXXXXX")" || return 1
            recent_commands_payload=""
            separator=""
            for entry in "${__shelp_recent_commands[@]}"; do
              recent_commands_payload+="${separator}${entry}"
              separator=$'\x1e'
            done

            printf '\n' 1>&2
            if [[ "$worker_mode" == "repair" ]]; then
              SHELP_RECENT_COMMANDS="$recent_commands_payload" shelp repair --initial-buffer "$instruction" >"$stdout_file"
            else
              SHELP_RECENT_COMMANDS="$recent_commands_payload" shelp session --initial-buffer "$instruction" >"$stdout_file"
            fi
            worker_status=$?
            action_line="$(head -n 1 "$stdout_file")"
            next_buffer="$(tail -n +2 "$stdout_file")"
            rm -f -- "$stdout_file"
            next_action="edit"

            if [[ "$action_line" == __SHELP_ACTION__:* ]]; then
              next_action="${action_line#__SHELP_ACTION__:}"
            elif [[ -n "$action_line" ]]; then
              next_buffer="${action_line}"$'\n'"${next_buffer}"
            fi

            if (( worker_status != 0 )); then
              printf 'shelp exited with status %d\n' "$worker_status" 1>&2
              READLINE_LINE="$instruction"
              READLINE_POINT=${#READLINE_LINE}
              READLINE_MARK=${#READLINE_LINE}
              return "$worker_status"
            fi

            READLINE_LINE="$next_buffer"
            READLINE_POINT=${#READLINE_LINE}
            READLINE_MARK=${#READLINE_LINE}

            if [[ "$next_action" == "run" ]]; then
              printf '\n'
              history -s "$READLINE_LINE"
              builtin eval "$READLINE_LINE"
              run_status=$?
              READLINE_LINE=""
              READLINE_POINT=0
              READLINE_MARK=0
              return "$run_status"
            fi

            return 0
          }

          __shelp_translate_widget() {
            __shelp_run_worker translate
          }

          __shelp_repair_widget() {
            __shelp_run_worker repair
          }

          __shelp_append_prompt_command
          bind -x '"__TRANSLATE_BINDING__":__shelp_translate_widget'
          bind -x '"__REPAIR_BINDING__":__shelp_repair_widget'
        fi
        """
    ).lstrip("\n")
    return script.replace("__TRANSLATE_BINDING__", bash_hotkey_sequence(hotkeys.translate)).replace(
        "__REPAIR_BINDING__",
        bash_hotkey_sequence(hotkeys.repair),
    )
