"""
Load plugins and merge what they provide with the client settings.

See `isabl_cli.hookspecs` for the hooks a plugin can implement. Each plugin is
called separately, so a failing plugin is reported without breaking the rest.
"""

from functools import lru_cache
from functools import partial

import click
import pluggy

from isabl_cli import hookspecs
from isabl_cli.discovery import get_command_name
from isabl_cli.discovery import get_entry_points
from isabl_cli.discovery import import_string
from isabl_cli.discovery import is_excluded
from isabl_cli.settings import import_from_string
from isabl_cli.settings import system_settings

ENTRY_POINT_GROUP = "isabl_cli"

_SIGNAL_HOOKS = {
    "status_change": "isabl_status_change_signals",
    "data_import": "isabl_data_import_signals",
}


@lru_cache(maxsize=None)
def get_plugin_manager():
    """Return a plugin manager with the installed plugins, if LOAD_PLUGINS."""
    manager = pluggy.PluginManager(ENTRY_POINT_GROUP)
    manager.add_hookspecs(hookspecs)

    if not system_settings.LOAD_PLUGINS:
        return manager

    for name in system_settings.DISABLED_PLUGINS:
        manager.set_blocked(name)

    for entry_point in get_entry_points(ENTRY_POINT_GROUP):
        if manager.is_blocked(entry_point.name) or manager.has_plugin(entry_point.name):
            continue

        try:
            manager.register(entry_point.load(), name=entry_point.name)
        except Exception as error:  # pylint: disable=W0703
            _warn(
                f"Failed to load plugin '{entry_point.name}' "
                f"({entry_point.value}): {error}"
            )

    return manager


def reset_plugin_manager():
    """Load plugins again on next use, e.g. after changing settings."""
    get_plugin_manager.cache_clear()


def get_applications(installed=(), excluded=()):
    """
    Merge INSTALLED_APPLICATIONS with the applications provided by plugins.

    Arguments:
        installed (list): imported INSTALLED_APPLICATIONS, they take precedence.
        excluded (list): EXCLUDED_APPLICATIONS patterns, see `is_excluded`.

    Returns:
        list: application classes, deduplicated by import string.
    """
    apps, seen = [], set()

    for item in list(installed) + _collect("isabl_applications"):
        try:
            if isinstance(item, str):
                item = import_from_string(item, "isabl_applications")
            path = import_string(item)
        except (ImportError, AttributeError) as error:
            _warn(f"Invalid application {item}: {error}")
            continue

        if path in seen:
            continue

        # building command names instantiates apps, only do it if needed
        if excluded and is_excluded(path, get_command_name(item), excluded):
            continue

        seen.add(path)
        apps.append(item)

    return apps


def get_commands():
    """Return the click commands provided by plugins."""
    commands = []

    for i in _collect("isabl_commands"):
        if isinstance(i, click.Command):
            commands.append(i)
        else:
            _warn(f"Invalid command provided by a plugin: {i}")

    return commands


def get_signals(kind, configured=()):
    """
    Merge the signals of a setting with the ones provided by plugins.

    Arguments:
        kind (str): `status_change` (ON_STATUS_CHANGE) or `data_import`
            (ON_DATA_IMPORT).
        configured (list): signals from the setting, they run first.

    Returns:
        list: signals, a signal listed twice runs once.
    """
    signals, seen = [], set()

    for i in list(configured) + _collect(_SIGNAL_HOOKS[kind]):
        if import_string(i) not in seen:
            seen.add(import_string(i))
            signals.append(i)

    return signals


def get_signal_failure_handlers(configured=None):
    """
    Return the functions to call when a signal fails.

    Arguments:
        configured (function): ON_SIGNAL_FAILURE, called first if set.

    Returns:
        list: functions that take endpoint, instance, signal and error.
    """
    handlers = [configured] if configured else []
    hook = get_plugin_manager().hook.isabl_signal_failure
    return handlers + [partial(_call_failure_hook, i) for i in hook.get_hookimpls()]


def _call_failure_hook(impl, endpoint, instance, signal, error):
    # pluggy lets implementations accept a subset of the hook arguments
    kwargs = {
        "endpoint": endpoint,
        "instance": instance,
        "signal": signal,
        "error": error,
    }
    return impl.function(*[kwargs[i] for i in impl.argnames])


def _collect(hook_name):
    """Call a hook on each plugin and concatenate the lists they return."""
    results = []

    for impl in getattr(get_plugin_manager().hook, hook_name).get_hookimpls():
        try:
            results.extend(impl.function() or [])
        except Exception as error:  # pylint: disable=W0703
            _warn(f"Plugin '{impl.plugin_name}' failed in {hook_name}: {error}")

    return results


def _warn(msg):
    click.secho(msg, err=True, fg="red")
