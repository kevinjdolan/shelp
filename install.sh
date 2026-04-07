#!/usr/bin/env bash
set -euo pipefail

DEFAULT_TRANSLATE_HOTKEY="ctrl+g"
DEFAULT_REPAIR_HOTKEY="ctrl+h"
GITHUB_REPO="${SHELP_GITHUB_REPO:-kevinjdolan/shelp}"
GITHUB_API_BASE="https://api.github.com/repos/${GITHUB_REPO}"
SHELP_VERSION="${SHELP_VERSION:-}"
SHELP_RELEASE_TAG=""
SHELP_WHEEL_URL=""
SHELP_BIN=""

say() {
  printf '%s\n' "$*"
}

error() {
  printf '%s\n' "$*" >&2
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

is_tty() {
  [[ -t 0 && -t 1 ]]
}

path_contains() {
  local dir="$1"
  [[ ":$PATH:" == *":$dir:"* ]]
}

detect_shell() {
  local shell_name="${SHELL##*/}"
  case "$shell_name" in
    fish|zsh|bash) printf '%s\n' "$shell_name" ;;
    *) printf '\n' ;;
  esac
}

ensure_curl() {
  if command_exists curl; then
    return 0
  fi

  error "curl is required to install shelp."
  exit 1
}

prompt_yes_no() {
  local prompt="$1"
  local default_answer="$2"
  local reply=""

  while true; do
    if [[ "$default_answer" == "Y" ]]; then
      printf '%s [Y/n] ' "$prompt"
    else
      printf '%s [y/N] ' "$prompt"
    fi

    IFS= read -r reply || return 1
    reply="${reply//[[:space:]]/}"
    reply="${reply,,}"

    if [[ -z "$reply" ]]; then
      [[ "$default_answer" == "Y" ]] && return 0
      return 1
    fi

    case "$reply" in
      y|yes) return 0 ;;
      n|no) return 1 ;;
    esac

    say "Please answer y or n."
  done
}

prompt_with_default() {
  local prompt="$1"
  local default_value="$2"
  local reply=""

  printf '%s [%s] ' "$prompt" "$default_value"
  IFS= read -r reply || reply=""
  if [[ -z "$reply" ]]; then
    printf '%s\n' "$default_value"
  else
    printf '%s\n' "$reply"
  fi
}

refresh_path_for_uv() {
  local candidate=""
  for candidate in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
    if [[ -x "$candidate/uv" ]] && ! path_contains "$candidate"; then
      PATH="$candidate:$PATH"
    fi
  done
  export PATH
}

ensure_uv() {
  if command_exists uv; then
    return 0
  fi

  if ! is_tty; then
    error "uv is required to install shelp. Re-run install.sh interactively, or install uv first."
    exit 1
  fi

  if ! prompt_yes_no "uv is not installed. Install it now?" "Y"; then
    error "uv is required to install shelp."
    exit 1
  fi

  curl -LsSf https://astral.sh/uv/install.sh | sh
  refresh_path_for_uv

  if ! command_exists uv; then
    error "uv installed, but I still could not find it on PATH."
    exit 1
  fi
}

normalize_release_tag() {
  local version="$1"
  version="${version#v}"
  printf 'v%s\n' "$version"
}

github_api_curl() {
  local url="$1"
  local -a args
  args=(-fsSL -H "Accept: application/vnd.github+json")
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    args+=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
  fi
  curl "${args[@]}" "$url"
}

extract_json_string() {
  local key="$1"
  sed -n "s/.*\"${key}\":[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" | sed 's#\\/#/#g' | head -n 1
}

extract_wheel_url() {
  sed -n 's/.*"browser_download_url":[[:space:]]*"\([^"]*\)".*/\1/p' \
    | sed 's#\\/#/#g' \
    | grep -E '/shelp-[^/]+-py3-none-any\.whl$' \
    | head -n 1
}

resolve_release() {
  local release_url=""
  local release_json=""

  if [[ -n "$SHELP_VERSION" ]]; then
    release_url="${GITHUB_API_BASE}/releases/tags/$(normalize_release_tag "$SHELP_VERSION")"
  else
    release_url="${GITHUB_API_BASE}/releases/latest"
  fi

  say "Resolving shelp release metadata from ${GITHUB_REPO}..."
  if ! release_json="$(github_api_curl "$release_url")"; then
    error "Unable to fetch release metadata from GitHub."
    exit 1
  fi

  SHELP_RELEASE_TAG="$(printf '%s\n' "$release_json" | extract_json_string tag_name || true)"
  SHELP_WHEEL_URL="$(printf '%s\n' "$release_json" | extract_wheel_url || true)"

  if [[ -z "$SHELP_RELEASE_TAG" || -z "$SHELP_WHEEL_URL" ]]; then
    error "Could not locate a release tag and universal wheel asset for shelp."
    exit 1
  fi
}

install_shelp() {
  local tmpdir=""
  local wheel_path=""

  resolve_release
  tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/shelp-install.XXXXXX")"
  wheel_path="${tmpdir}/${SHELP_WHEEL_URL##*/}"

  say "Downloading shelp ${SHELP_RELEASE_TAG}..."
  curl -fsSL "$SHELP_WHEEL_URL" -o "$wheel_path"

  say "Installing shelp with uv..."
  uv tool install --force "$wheel_path"
  rm -rf "$tmpdir"
}

ensure_shelp_on_path() {
  local uv_bin_dir=""
  local had_uv_bin_on_path=0

  uv_bin_dir="$(uv tool dir --bin)"
  if path_contains "$uv_bin_dir"; then
    had_uv_bin_on_path=1
  fi

  PATH="$uv_bin_dir:$PATH"
  export PATH
  SHELP_BIN="$uv_bin_dir/shelp"

  if [[ ! -x "$SHELP_BIN" ]]; then
    error "shelp was installed, but the executable was not found at $SHELP_BIN."
    exit 1
  fi

  if [[ "$had_uv_bin_on_path" -eq 0 ]]; then
    say "Adding $uv_bin_dir to your shell PATH with uv..."
    uv tool update-shell --quiet
    say "Future shells will find shelp on PATH automatically."
    say "If this terminal cannot find shelp yet, open a new shell or source your shell startup file."
  fi
}

configure_detected_shell() {
  local shell_name="$1"
  local translate_hotkey=""
  local repair_hotkey=""

  if ! prompt_yes_no "Set up shelp hotkeys for your $shell_name shell?" "Y"; then
    say "shelp is installed at $SHELP_BIN."
    say "When you are ready, run:"
    say "  $SHELP_BIN install --shell $shell_name"
    return 0
  fi

  say "Recommended translate hotkey: Ctrl-G"
  translate_hotkey="$(prompt_with_default "Translate hotkey" "$DEFAULT_TRANSLATE_HOTKEY")"
  say "Recommended repair hotkey: Ctrl-H"
  say "Ctrl-H can overlap with Backspace in some terminals, so feel free to pick another control letter."
  repair_hotkey="$(prompt_with_default "Repair hotkey" "$DEFAULT_REPAIR_HOTKEY")"

  "$SHELP_BIN" install \
    --shell "$shell_name" \
    --translate-hotkey "$translate_hotkey" \
    --repair-hotkey "$repair_hotkey"

  say "Installed shell hotkeys for $shell_name."
}

main() {
  ensure_curl
  ensure_uv
  install_shelp
  ensure_shelp_on_path

  if (($# > 0)); then
    exec "$SHELP_BIN" install "$@"
  fi

  local shell_name=""
  shell_name="$(detect_shell)"
  if [[ -z "$shell_name" ]]; then
    say "shelp is installed at $SHELP_BIN."
    say "I could not detect a supported shell from SHELL=${SHELL:-unset}."
    say "Run one of these when you are ready:"
    say "  $SHELP_BIN install --shell fish"
    say "  $SHELP_BIN install --shell zsh"
    say "  $SHELP_BIN install --shell bash"
    return 0
  fi

  configure_detected_shell "$shell_name"
}

main "$@"
