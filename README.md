# shelp

`shelp` turns natural-language requests into shell commands, keeps the interactive review flow from the original Fish helper, and packages it as a proper `uv` project with installable CLI entrypoints.

## What Changed

- Packaged as a Python project named `shelp`
- Installed as a CLI command: `shelp`
- Split into focused modules instead of one large script
- Added shell integration for Fish, Zsh, and Bash
- Added an installer that can wire shell startup files for you
- Added an optional macOS Quick Action that can trigger the helper through a standard macOS keyboard shortcut

## Install

```bash
./install.sh
```

By default the script installs the CLI with `uv tool install --editable` and then configures all supported shells. To scope installation more narrowly, pass the same flags accepted by `shelp install`, for example:

```bash
./install.sh --shell fish
./install.sh --shell zsh --no-macos-quick-action
```

## Manual Commands

```bash
uv tool install --editable .
shelp install --all-shells
```

## Shell Integration

Each shell loads a small bootstrap line and then asks `shelp init <shell>` to emit the live integration code.

- Fish: installs `~/.config/fish/conf.d/shelp.fish`
- Zsh: adds a managed block to `~/.zshrc`
- Bash: adds a managed block to `~/.bashrc`, and ensures login shells source it from `~/.bash_profile`

The default key chord inside the shell integration is `Ctrl-G`.

## macOS Quick Action

On macOS, `shelp install` also creates `~/Library/Services/SHelp Trigger.workflow`. The Quick Action sends `Ctrl-G` to the frontmost app, which lets Terminal apps trigger the shell binding through a normal macOS keyboard shortcut.

After installation:

1. Open System Settings.
2. Go to Keyboard > Keyboard Shortcuts > Services.
3. Assign your preferred shortcut to `SHelp Trigger`.
4. If macOS asks for Accessibility access for `System Events` or `osascript`, allow it.

## Config

The packaged helper reads and writes config at:

```text
~/.config/shelp/config.yaml
```

If that file does not exist yet, `shelp` will fall back to the legacy Fish config at `~/.config/fish/ai_help.yaml`. Running `shelp install` migrates the legacy config into the new location.
