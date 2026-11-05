"""Tests for pluggy plugins."""

import sys

import pytest

from isabl_cli import api
from isabl_cli import plugins
from isabl_cli import settings

from .test_discovery import FAKE_PACKAGES
from .test_discovery import install_packages  # pylint: disable=W0611

PLUGIN_PACKAGES = dict(
    FAKE_PACKAGES,
    **{
        "fakeapps/plugin.py": """
            import click

            from isabl_cli.discovery import find_applications
            from isabl_cli.hookspecs import hookimpl

            CALLS = []

            @hookimpl
            def isabl_applications():
                apps = find_applications(
                    "fakeapps.apps", required=("NAME", "VERSION", "ASSEMBLY")
                )
                return apps + ["fakeapps.apps.call.Call"]

            @click.command()
            def hello():
                \"\"\"Say hello.\"\"\"

            @hookimpl
            def isabl_commands():
                return [hello, "not a command"]

            def on_status_change(analysis):
                CALLS.append(("status", analysis["pk"]))

            def on_data_import(experiment):
                CALLS.append(("import", experiment["pk"]))

            def configured_failure(endpoint, instance, signal, error):
                CALLS.append(("configured failure", signal.__name__))

            @hookimpl
            def isabl_status_change_signals():
                return [on_status_change]

            @hookimpl
            def isabl_data_import_signals():
                return [on_data_import]

            @hookimpl
            def isabl_signal_failure(signal, error):
                CALLS.append(("plugin failure", signal.__name__, str(error)))
        """,
        "fakeapps/broken_plugin.py": """
            from isabl_cli.hookspecs import hookimpl

            @hookimpl
            def isabl_applications():
                raise RuntimeError("hook boom")
        """,
        "fakeapps/disabled_plugin.py": "raise RuntimeError('should not be imported')",
    },
)

ENTRY_POINTS = {
    plugins.ENTRY_POINT_GROUP: {
        "fake": "fakeapps.plugin",
        "broken": "fakeapps.broken_plugin",
        "disabled": "fakeapps.disabled_plugin",
        "missing": "fakeapps.does_not_exist",
    }
}


@pytest.fixture
def fake_plugins(install_packages, monkeypatch):  # pylint: disable=W0621
    """Install a package with plugins and enable them."""
    install_packages(PLUGIN_PACKAGES, entry_points=ENTRY_POINTS)
    monkeypatch.setitem(settings._DEFAULTS, "LOAD_PLUGINS", True)
    monkeypatch.setitem(settings._DEFAULTS, "DISABLED_PLUGINS", ["disabled"])
    plugins.reset_plugin_manager()
    yield sys.modules
    plugins.reset_plugin_manager()


def test_plugins_are_opt_in(install_packages, monkeypatch):  # pylint: disable=W0621
    install_packages(PLUGIN_PACKAGES, entry_points=ENTRY_POINTS)
    monkeypatch.setitem(settings._DEFAULTS, "LOAD_PLUGINS", False)
    plugins.reset_plugin_manager()

    assert plugins.get_applications() == []
    assert plugins.get_commands() == []
    assert "fakeapps.plugin" not in sys.modules


def test_get_applications(fake_plugins, capsys):  # pylint: disable=W0621
    from fakeapps.apps.align import AlignGRCh37  # pylint: disable=C0415

    apps = plugins.get_applications(installed=[AlignGRCh37])
    assert [i.__name__ for i in apps] == [
        "AlignGRCh37",
        "FinaliseAlignGRCh37",
        "NeedsEnvGRCh37",
        "Call",
        "Nested",
    ]

    stderr = capsys.readouterr().err
    assert "Plugin 'broken' failed in isabl_applications: hook boom" in stderr
    assert "Failed to load plugin 'missing'" in stderr
    assert "fakeapps.disabled_plugin" not in sys.modules

    apps = plugins.get_applications(installed=[AlignGRCh37], excluded=["call-*"])
    assert [i.__name__ for i in apps] == [
        "AlignGRCh37",
        "FinaliseAlignGRCh37",
        "NeedsEnvGRCh37",
        "Nested",
    ]

    # exclude by a command name that the app overrides
    apps = plugins.get_applications(excluded=["*_finalise"])
    assert "FinaliseAlignGRCh37" not in [i.__name__ for i in apps]


def test_get_commands(fake_plugins, capsys):  # pylint: disable=W0621
    assert [i.name for i in plugins.get_commands()] == ["hello"]
    assert "Invalid command provided by a plugin" in capsys.readouterr().err


def test_get_signals(fake_plugins):  # pylint: disable=W0621
    from fakeapps import plugin  # pylint: disable=C0415

    def configured(_):
        pass

    signals = plugins.get_signals("status_change", [configured])
    assert signals == [configured, plugin.on_status_change]

    # a signal also listed in the setting runs once
    signals = plugins.get_signals("status_change", [plugin.on_status_change])
    assert signals == [plugin.on_status_change]
    assert plugins.get_signals("data_import") == [plugin.on_data_import]


def test_signal_failures(fake_plugins, monkeypatch, capsys):  # pylint: disable=W0621
    from fakeapps import plugin  # pylint: disable=C0415

    monkeypatch.setitem(
        settings._DEFAULTS, "ON_SIGNAL_FAILURE", "fakeapps.plugin.configured_failure"
    )

    def failing_signal(_):
        raise ValueError("signal boom")

    signals = [failing_signal] + plugins.get_signals("status_change")
    api._run_signals("analyses", {"pk": 1}, signals, create_record=False)

    assert plugin.CALLS == [
        ("configured failure", "failing_signal"),
        ("plugin failure", "failing_signal", "signal boom"),
        ("status", 1),
    ]
    assert "some signals failed" in capsys.readouterr().err
