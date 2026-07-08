import importlib

def _reload():
    return importlib.reload(importlib.import_module("tools.run_storymap_checks"))

def test_python_bin_prefers_active_virtualenv(monkeypatch):
    module = _reload()
    active_python = "/tmp/custom-venv/bin/python"

    monkeypatch.setenv("VIRTUAL_ENV", "/tmp/custom-venv")
    monkeypatch.setattr(module, "REPO_ROOT", module.Path("/tmp/repo"))
    monkeypatch.setattr(module, "sys", type("Sys", (), {"executable": "/usr/bin/python3"})())
    monkeypatch.setattr(
        module.Path,
        "exists",
        lambda self: str(self) in {active_python, "/usr/bin/python3"},
    )
    monkeypatch.setattr(module, "_has_module", lambda python_bin, module_name: python_bin == active_python)

    assert module._python_bin() == active_python

def test_python_bin_falls_back_to_sys_executable(monkeypatch):
    module = _reload()
    sys_python = "/usr/bin/python3"

    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(module, "REPO_ROOT", module.Path("/tmp/repo"))
    monkeypatch.setattr(module, "sys", type("Sys", (), {"executable": sys_python})())
    monkeypatch.setattr(module.Path, "exists", lambda self: str(self) == sys_python)
    monkeypatch.setattr(module, "_has_module", lambda python_bin, module_name: python_bin == sys_python)

    assert module._python_bin() == sys_python

def test_main_runs_default_smoke_targets(monkeypatch):
    module = _reload()
    calls = []

    monkeypatch.setattr(module, "_python_bin", lambda: "/usr/bin/python3")
    monkeypatch.setattr(module, "_ruff_command", lambda _python_bin: None)
    monkeypatch.setattr(module, "_run", lambda command: calls.append(command) or 0)
    monkeypatch.setattr(
        module.argparse.ArgumentParser,
        "parse_args",
        lambda self: type("Args", (), {"skip_ruff": False, "all_tests": False})(),
    )

    assert module.main() == 0
    assert calls == [["/usr/bin/python3", "-m", "pytest", *module.DEFAULT_TESTS]]

def test_main_runs_all_tests_when_requested(monkeypatch):
    module = _reload()
    calls = []

    monkeypatch.setattr(module, "_python_bin", lambda: "/usr/bin/python3")
    monkeypatch.setattr(module, "_ruff_command", lambda _python_bin: None)
    monkeypatch.setattr(module, "_run", lambda command: calls.append(command) or 0)
    monkeypatch.setattr(
        module.argparse.ArgumentParser,
        "parse_args",
        lambda self: type("Args", (), {"skip_ruff": False, "all_tests": True})(),
    )

    assert module.main() == 0
    assert calls == [["/usr/bin/python3", "-m", "pytest", "tests"]]
