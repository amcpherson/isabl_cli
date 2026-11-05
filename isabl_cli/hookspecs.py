"""
Hooks that installed packages can implement to extend Isabl CLI.

Implement hooks in a module and register it in the `isabl_cli` entry point
group, for example in the package's `setup.py`:

    entry_points={"isabl_cli": ["my_apps = my_apps.plugin"]}

And in `my_apps/plugin.py`:

    from isabl_cli.discovery import find_applications
    from isabl_cli.hookspecs import hookimpl

    @hookimpl
    def isabl_applications():
        return find_applications("my_apps.apps")

Plugins are only loaded if the LOAD_PLUGINS setting is True, and plugins named in
DISABLED_PLUGINS are skipped. A plugin implements only the hooks it needs.
"""

# pylint: disable=unused-argument

import pluggy

hookspec = pluggy.HookspecMarker("isabl_cli")
hookimpl = pluggy.HookimplMarker("isabl_cli")


@hookspec
def isabl_applications():
    """
    Return applications to add to the CLI, like INSTALLED_APPLICATIONS.

    Returns:
        list: application classes or import strings.
    """


@hookspec
def isabl_commands():
    """
    Return commands to add to the CLI, like CUSTOM_COMMANDS.

    Returns:
        list: click commands.
    """


@hookspec
def isabl_status_change_signals():
    """
    Return signals run when an analysis changes status, like ON_STATUS_CHANGE.

    Signals are functions that take an analysis. They are run and recorded like
    the ones in the setting, so failures can be rerun with `isabl rerun-signals`.

    Returns:
        list: functions.
    """


@hookspec
def isabl_data_import_signals():
    """
    Return signals run when raw data is imported, like ON_DATA_IMPORT.

    Returns:
        list: functions that take an experiment.
    """


@hookspec
def isabl_signal_failure(endpoint, instance, signal, error):
    """
    Handle a failed signal, called in addition to ON_SIGNAL_FAILURE.

    Arguments:
        endpoint (str): `analyses` or `experiments`.
        instance (dict): the analysis or experiment.
        signal (function): the signal that failed.
        error (Exception): the error raised by the signal.
    """
