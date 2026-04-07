from __future__ import annotations

from pathlib import Path

from shelp.shells import install_shell_loader, shell_init


def test_shell_init_contains_expected_bindings() -> None:
    assert "bindkey '^G' __shelp_widget" in shell_init("zsh")
    assert "bind -x '\"\\C-g\":__shelp_widget'" in shell_init("bash")
    assert "bind -M insert \\cg __shelp_translate_buffer" in shell_init("fish")


def test_install_fish_loader_writes_conf_d_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    changed = install_shell_loader("fish")

    fish_loader = tmp_path / ".config" / "fish" / "conf.d" / "shelp.fish"
    assert changed == [fish_loader]
    assert "shelp init fish | source" in fish_loader.read_text(encoding="utf-8")


def test_install_bash_loader_writes_bashrc_and_profile(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    changed = install_shell_loader("bash")

    bashrc = tmp_path / ".bashrc"
    bash_profile = tmp_path / ".bash_profile"
    assert bashrc in changed
    assert bash_profile in changed
    assert 'eval "$(shelp init bash)"' in bashrc.read_text(encoding="utf-8")
    assert '. "$HOME/.bashrc"' in bash_profile.read_text(encoding="utf-8")
