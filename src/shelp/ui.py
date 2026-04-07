from __future__ import annotations

import math
import os
import re
import sys
import termios
import threading
import time

from rich.cells import cell_len
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .errors import ShelpError
from .models import ChoiceOption, ProviderSettings
from .utils import abbreviate_label, scale_hex_color


TEXT_FG = "FFF9F7"
LEGEND_FG = "857C80"
AGENT_BG = "005059"
ERROR_BG = "3F0B00"
USER_BG = "4B2B73"
PROPOSAL_BG = "262643"
PREFILLED_BG = "595000"
THINKING_BG = "C87400"
RESET = "\033[0m"
CLEAR_TO_EOL = "\033[K"


class ProcessingIndicator:
    def __init__(self, ui: "TerminalUI", message: str = "Thinking...") -> None:
        self.ui = ui
        self.message = message
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if not self._stop_event.is_set():
            self._stop_event.set()
            if self._thread is not None:
                self._thread.join(timeout=0.5)
                self._thread = None

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    def _run(self) -> None:
        start_time = time.monotonic()
        while not self._stop_event.is_set():
            elapsed = time.monotonic() - start_time
            phase = (elapsed % 1.0) / 1.0
            pulse = 0.85 + 0.15 * math.sin(phase * 2 * math.pi)
            with self.ui._indicator_lock:
                self.ui._write(self.ui._render_indicator_frame(self.message, pulse))
            if self._stop_event.wait(0.05):
                break

        with self.ui._indicator_lock:
            self.ui._write(f"\r{CLEAR_TO_EOL}{RESET}")


class TerminalUI:
    def __init__(self) -> None:
        self.out = sys.stderr
        self._tty_fd = None
        self._provider_badge = ""
        self.console = Console(
            file=self.out,
            force_terminal=True,
            color_system="truecolor",
            soft_wrap=True,
            highlight=False,
        )
        self._indicator_lock = threading.Lock()

    def _style(self, fg: str, bg: str) -> str:
        return f"\033[38;2;{self._hex_rgb(fg)}m\033[48;2;{self._hex_rgb(bg)}m"

    @staticmethod
    def _hex_rgb(value: str) -> str:
        return ";".join(str(int(value[index:index + 2], 16)) for index in (0, 2, 4))

    def _write(self, text: str) -> None:
        self.out.write(text)
        self.out.flush()

    def set_provider_badge(self, provider_settings: ProviderSettings) -> None:
        provider_names = {
            "anthropic": "Claude",
            "openai": "OpenAI",
            "gemini": "Gemini",
        }
        provider_label = provider_names.get(provider_settings.provider, provider_settings.provider.title())
        model_label = abbreviate_label(provider_settings.model, 28)
        self._provider_badge = f"{provider_label} / {model_label} (/help for help)"

    def _render_full_width_text(
        self,
        prefix: str,
        message: str,
        fg: str,
        bg: str,
        *,
        right_legend: str = "",
        legend_fg: str = LEGEND_FG,
    ) -> Text:
        style = f"#{fg} on #{bg}"
        content = Text(f" {prefix} {message} ", style=style)
        if right_legend:
            legend_style = f"#{legend_fg} on #{bg}"
            width = max(1, self.console.size.width)
            legend_width = cell_len(right_legend) + 1
            fill = max(1, width - cell_len(content.plain) - legend_width)
            content.append(" " * fill, style=style)
            content.append(right_legend, style=legend_style)
            trailing_padding = max(0, width - cell_len(content.plain))
            if trailing_padding:
                content.append(" " * trailing_padding, style=style)
            return content

        width = max(1, self.console.size.width)
        padding = max(0, width - cell_len(content.plain))
        if padding:
            content.append(" " * padding, style=style)
        return content

    def _print_full_width_line(self, prefix: str, message: str, fg: str, bg: str) -> None:
        content = self._render_full_width_text(prefix, message, fg, bg)
        self.console.print(content, overflow="crop", no_wrap=True)

    def choice_panel(
        self,
        title: str,
        options: list[ChoiceOption],
        *,
        intro: str | None = None,
        default_index: int = 0,
    ) -> None:
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(style=f"bold #{TEXT_FG}")
        table.add_column(style=f"#{TEXT_FG}")
        table.add_column(style=f"#{LEGEND_FG}")

        if intro:
            table.add_row("", intro, "")
            table.add_row("", "", "")

        for index, option in enumerate(options, start=1):
            suffix = "default" if index - 1 == default_index else ""
            description = option.description
            if description and suffix:
                description = f"{description} | {suffix}"
            elif suffix:
                description = suffix
            table.add_row(str(index), option.label, description)

        footer = Text(" Type a number and press Enter. Press Enter on a blank line to accept the default. ", style=f"#{LEGEND_FG}")
        panel = Panel(
            table,
            title=title,
            border_style=f"#{AGENT_BG}",
            padding=(0, 1),
            subtitle=footer,
            subtitle_align="left",
        )
        self.console.print(panel)

    def choose_option(
        self,
        title: str,
        options: list[ChoiceOption],
        *,
        intro: str | None = None,
        default_index: int = 0,
    ) -> ChoiceOption:
        if not options:
            raise ShelpError("I could not offer any choices because the option list was empty.", stage="showing an interactive choice")

        self.choice_panel(title, options, intro=intro, default_index=default_index)

        while True:
            try:
                response = self.prompt_user().strip()
            except EOFError as exc:
                raise ShelpError("I lost terminal input while waiting for a menu choice.", stage="reading an interactive choice") from exc
            except KeyboardInterrupt as exc:
                raise ShelpError("I stopped while waiting for a menu choice.", stage="reading an interactive choice") from exc

            if not response:
                return options[default_index]

            if response.isdigit():
                selected = int(response)
                if 1 <= selected <= len(options):
                    return options[selected - 1]

            self.agent_line(f"I need a number between 1 and {len(options)}.", "error")

    def _render_indicator_frame(self, message: str, pulse: float) -> str:
        bg = scale_hex_color(THINKING_BG, pulse)
        style = self._style(TEXT_FG, bg)
        plain = self._render_full_width_text(
            "🤔",
            message,
            TEXT_FG,
            bg,
            right_legend=self._provider_badge,
        ).plain
        return f"\r{style}{plain}{RESET}"

    def start_processing_indicator(self, message: str = "Thinking..."):
        return ProcessingIndicator(self, message)

    def agent_line(self, message: str, kind: str = "normal") -> None:
        bg = AGENT_BG
        if kind == "error":
            bg = ERROR_BG

        for line in (message.splitlines() or [""]):
            content = self._render_full_width_text(
                "🤖",
                line,
                TEXT_FG,
                bg,
                right_legend=self._provider_badge,
            )
            self.console.print(content, overflow="crop", no_wrap=True)

    def prefilled_line(self, message: str) -> None:
        for line in (message.splitlines() or [""]):
            self._print_full_width_line("🤦", line, TEXT_FG, PREFILLED_BG)

    def proposal_line(self, command: str) -> None:
        bg = PROPOSAL_BG
        style = f"#{TEXT_FG} on #{bg}"
        legend_style = f"#{LEGEND_FG} on #{bg}"
        legend = "Enter to Accept, Esc to Revise"
        left = Text(f" 💻 {command} ", style=style)
        width = max(1, self.console.size.width)
        legend_width = cell_len(legend) + 1
        fill = max(1, width - cell_len(left.plain) - legend_width)
        left.append(" " * fill, style=style)
        left.append(legend, style=legend_style)
        self.console.print(left, overflow="crop", no_wrap=True)

    def stream_structured_message(self, chunks) -> str:
        raw_text = []
        display_started = False
        message_started = False
        message_finished = False
        line_open = False
        style = self._style(TEXT_FG, AGENT_BG)
        search_buffer = ""
        unicode_buffer = ""
        escape_mode = False
        indicator = self.start_processing_indicator("Thinking...")
        indicator.__enter__()

        def open_line() -> None:
            nonlocal line_open
            if not line_open:
                self._write(f"{style} 🤖 ")
                line_open = True

        def write_visible(text: str) -> None:
            nonlocal line_open
            for char in text:
                if char == "\n":
                    if line_open:
                        self._write(f" {CLEAR_TO_EOL}{RESET}\n")
                        line_open = False
                    else:
                        self._write("\n")
                else:
                    open_line()
                    self._write(char)

        def decode_escape(char: str) -> str | None:
            mapping = {
                '"': '"',
                "\\": "\\",
                "/": "/",
                "b": "\b",
                "f": "\f",
                "n": "\n",
                "r": "\r",
                "t": "\t",
            }
            return mapping.get(char)

        try:
            for chunk in chunks:
                if not chunk:
                    continue

                raw_text.append(chunk)
                indicator.stop()

                if message_finished:
                    continue

                if not message_started:
                    search_buffer += chunk
                    match = re.search(r'"message"\s*:\s*"', search_buffer)
                    if not match:
                        search_buffer = search_buffer[-128:]
                        continue

                    message_started = True
                    search_buffer = search_buffer[match.end():]
                    chunk = search_buffer
                    search_buffer = ""
                elif not display_started:
                    display_started = True

                if message_started and not display_started:
                    display_started = True

                for char in chunk:
                    if message_finished:
                        break

                    if unicode_buffer:
                        unicode_buffer += char
                        if len(unicode_buffer) == 5:
                            try:
                                write_visible(chr(int(unicode_buffer[1:], 16)))
                            except ValueError as exc:
                                raise ShelpError(
                                    f"Unable to decode unicode escape in structured reply: \\{unicode_buffer}",
                                    stage="streaming the conversational reply",
                                ) from exc
                            unicode_buffer = ""
                            escape_mode = False
                        continue

                    if escape_mode:
                        if char == "u":
                            unicode_buffer = "u"
                            continue

                        decoded = decode_escape(char)
                        if decoded is None:
                            raise ShelpError(
                                f"Unable to decode escaped character in structured reply: \\{char}",
                                stage="streaming the conversational reply",
                            )
                        write_visible(decoded)
                        escape_mode = False
                        continue

                    if char == "\\":
                        escape_mode = True
                        continue

                    if char == '"':
                        message_finished = True
                        continue

                    write_visible(char)
        finally:
            indicator.__exit__(None, None, None)

        if line_open:
            self._write(f" {CLEAR_TO_EOL}{RESET}\n")

        return "".join(raw_text).strip()

    def prompt_user(self) -> str:
        fd = self._tty_input()
        style = self._style(TEXT_FG, USER_BG)
        buffer: list[str] = []
        original_attributes = termios.tcgetattr(fd)

        def render() -> None:
            self._write(f"\r{style} 🙂 {''.join(buffer)}{CLEAR_TO_EOL}")
            self._write("\033[?25h")

        updated_attributes = termios.tcgetattr(fd)
        updated_attributes[3] &= ~(termios.ECHO | termios.ICANON)
        updated_attributes[6][termios.VMIN] = 1
        updated_attributes[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSADRAIN, updated_attributes)

        try:
            render()
            while True:
                raw = os.read(fd, 1)
                if not raw:
                    self._write(f"{RESET}\n")
                    raise EOFError

                char = raw.decode("utf-8", errors="ignore")
                if not char:
                    continue

                if char in {"\r", "\n"}:
                    self._write(f"{RESET}\n")
                    return "".join(buffer)

                if char == "\x03":
                    self._write(f"{RESET}\n")
                    raise KeyboardInterrupt

                if char == "\x04":
                    self._write(f"{RESET}\n")
                    if buffer:
                        return "".join(buffer)
                    raise EOFError

                if char in {"\x7f", "\b"}:
                    if buffer:
                        buffer.pop()
                    render()
                    continue

                if char == "\x1b":
                    os.read(fd, 2)
                    continue

                if ord(char) >= 32 or char == "\t":
                    buffer.append(char)
                    render()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, original_attributes)

    def review_proposed_command(self, command: str) -> str:
        fd = self._tty_input()
        original_attributes = termios.tcgetattr(fd)

        self.proposal_line(command)

        updated_attributes = termios.tcgetattr(fd)
        updated_attributes[3] &= ~(termios.ECHO | termios.ICANON)
        updated_attributes[6][termios.VMIN] = 1
        updated_attributes[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSADRAIN, updated_attributes)

        try:
            while True:
                raw = os.read(fd, 1)
                if not raw:
                    return "edit"

                char = raw.decode("utf-8", errors="ignore")
                if not char:
                    continue

                if char in {"\r", "\n"}:
                    self._write(f"{RESET}\n")
                    return "run"

                if char == "\x1b":
                    self._write(f"{RESET}\n")
                    return "edit"

                if char == "\x03":
                    self._write(f"{RESET}\n")
                    raise KeyboardInterrupt
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, original_attributes)

    def _tty_input(self):
        if self._tty_fd is None:
            try:
                self._tty_fd = os.open("/dev/tty", os.O_RDONLY)
            except OSError as exc:
                raise ShelpError(f"Unable to open /dev/tty for inline input: {exc}", stage="opening the interactive terminal input") from exc

        return self._tty_fd
