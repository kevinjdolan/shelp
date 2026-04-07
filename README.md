# shelp

`shelp` is an AI shell assistant for fish, zsh, and bash. It turns plain-English requests into shell commands you can review before they run, and it can repair a broken command by looking at your recent shell history.

## Quick Install

### Prerequisites

- A Unix-like shell environment with fish, zsh, or bash
- `git`
- `uv` for manual installs. `./install.sh` will offer to install it if it is missing.
- An API key for Gemini, OpenAI, or Anthropic

### One-Liner

```bash
git clone https://github.com/kevinjdolan/shelp.git && cd shelp && ./install.sh
```

The installer will:

- offer to install `uv` if it is missing
- install `shelp` as a normal CLI tool with `uv`
- make sure the `uv` tool bin directory is the place your shell expects for user-installed commands
- offer to wire hotkeys into your current fish, zsh, or bash shell
- recommend `Ctrl-G` for command generation and `Ctrl-H` for command repair, while letting you choose different bindings

## Quickstart

1. Run the install command above.
2. Launch `shelp` once and paste your API key when prompted, or save it in `~/.config/shelp/config.yaml`.
3. At a shell prompt, type what you want in plain English and press `Ctrl-G`.
4. Review the proposed command. Press Enter to run it or Esc to revise it.
5. If a command fails or is close-but-wrong, press `Ctrl-H` or run `shelp repair`.

`shelp repair` inspects recent shell commands, tries to infer what you were attempting, proposes a repaired command, and usually gives a short rationale for the fix. If the intent is still too ambiguous, it asks one pointed follow-up question instead of guessing wildly.

`Ctrl-H` can overlap with Backspace in some terminals. If that is a problem in your setup, choose another control key during install or rerun:

```bash
shelp install --shell zsh --translate-hotkey ctrl+g --repair-hotkey ctrl+r
```

Replace `zsh` with `fish` or `bash` if needed.

## Commands

- `shelp` opens the interactive helper
- `shelp repair` repairs the current or most relevant recent command
- `shelp install --shell zsh` installs shell integration for one shell
- `shelp install --all-shells` installs integration for fish, zsh, and bash
- `shelp paths` shows important config and integration paths

## Shell Integration

`shelp install` writes a small loader for your shell. That loader calls `shelp init <shell>` at startup so your saved hotkey settings stay in sync.

- Fish: `~/.config/fish/conf.d/shelp.fish`
- Zsh: a managed block in `~/.zshrc`
- Bash: a managed block in `~/.bashrc`, plus `~/.bash_profile` sourcing `~/.bashrc`

## Manual Install

If you already have `uv`, you can install `shelp` directly from a checkout:

```bash
uv tool install .
shelp install --shell zsh
```

If you are developing on `shelp` itself and want live edits to apply immediately:

```bash
uv tool install --editable .
```

## macOS

On macOS, `shelp install` also creates `~/Library/Services/SHelp Trigger.workflow`.

After installation:

1. Open System Settings.
2. Go to Keyboard > Keyboard Shortcuts > Services.
3. Assign a shortcut to `SHelp Trigger`.
4. If macOS asks for Accessibility access for `System Events` or `osascript`, allow it.

The Quick Action sends your configured translate hotkey to the frontmost app.

## Config

The main config file lives at:

```text
~/.config/shelp/config.yaml
```

If that file does not exist yet, `shelp` falls back to the legacy Fish config at `~/.config/fish/ai_help.yaml`. Running `shelp install` migrates the legacy config into the new location.
