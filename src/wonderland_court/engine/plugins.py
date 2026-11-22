"""Plugins: targets, defenses, scenarios and Mad Hatter mutators from other packages.

A package adds plugins with entry points in its `pyproject.toml`, one group per kind:

    [project.entry-points."wonderland_court.defenses"]
    custom_shield = "acme_court.shield:CustomShield"

    wonderland_court.targets    `(argument: str) -> Target`, named `plugin:<name>[:<argument>]`
    wonderland_court.defenses   a `DefenseFactory`, `(DefensePolicy) -> Defense`
    wonderland_court.scenarios  `(canary: str) -> ScenarioDefinition`
    wonderland_court.mutators   a mutator, `(text: str, rng: random.Random) -> str`

Finding plugins reads package metadata and imports nothing. A plugin's module is imported the
first time Court needs that plugin, and only once: what it pointed at, or why it failed, is
kept for the rest of the process. A plugin that can't load raises `PluginError`, one line that
names the entry point and its package, and only when something asks for it, so a broken
plugin never breaks a command that doesn't use it.

Built-in names win: a plugin that reuses one (`sandwich`, `vault`, `base64`) is never loaded.
A name that two packages register is an error until one of them is uninstalled. `court
plugins` lists every installed plugin and why any of them can't be used.

Plugins run inside Court with its permissions. Installing one means trusting its code.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from importlib.metadata import EntryPoint, entry_points

from wonderland_court.config import DEFENSE_PART
from wonderland_court.contracts import MutatorId, ScenarioId

log = logging.getLogger(__name__)


class PluginKind(StrEnum):
    TARGET = "targets"
    DEFENSE = "defenses"
    SCENARIO = "scenarios"
    MUTATOR = "mutators"

    @property
    def group(self) -> str:
        """The entry point group, such as `wonderland_court.defenses`."""
        return f"wonderland_court.{self.value}"

    @property
    def noun(self) -> str:
        return self.value.removesuffix("s")


class PluginError(ValueError):
    """A plugin that can't be used. The message names the entry point and its package."""

    def __init__(self, message: str, problem: str) -> None:
        super().__init__(message)
        self.problem = problem
        """What is wrong, without the plugin's name, for `court plugins`."""


@dataclass(frozen=True)
class Plugin:
    """One installed entry point."""

    kind: PluginKind
    name: str
    value: str
    """What the entry point points at, such as `acme_court.shield:CustomShield`."""
    package: str
    """The distribution that registers it, with its version, such as `acme-court 1.0`."""
    entry_point: EntryPoint = field(repr=False, compare=False)

    def __str__(self) -> str:
        return f"{self.kind.noun} plugin {self.name!r} ({self.value} in {self.package})"

    def error(self, problem: str) -> PluginError:
        return PluginError(f"{self} {problem}", problem)


_found: dict[PluginKind, dict[str, list[Plugin]]] = {}
_loaded: dict[tuple[PluginKind, str], Callable[..., object] | PluginError] = {}


def clear() -> None:
    """Forget what was found and loaded, so the next lookup reads package metadata again."""
    _found.clear()
    _loaded.clear()


def _package(entry_point: EntryPoint) -> str:
    dist = entry_point.dist
    return f"{dist.name} {dist.version}" if dist is not None else "an unknown package"


def _one_line(exc: BaseException) -> str:
    return " ".join(f"{type(exc).__name__}: {exc}".split())


def _scan(kind: PluginKind) -> dict[str, list[Plugin]]:
    """Installed plugins of one kind by name, from package metadata."""
    if kind not in _found:
        found: dict[str, list[Plugin]] = {}
        try:
            points = list(entry_points(group=kind.group))
        except Exception as exc:  # one package's bad metadata must not break Court
            log.warning("can't read %s plugins from package metadata: %s", kind.noun, exc)
            points = []
        for point in points:
            plugin = Plugin(kind, point.name, point.value, _package(point), point)
            found.setdefault(point.name, []).append(plugin)
        _found[kind] = found
    return _found[kind]


def builtin_names(kind: PluginKind) -> frozenset[str]:
    """The names Court ships for a kind. Plugin targets have their own `plugin:` prefix."""
    if kind is PluginKind.DEFENSE:
        from .defenses import DEFENSES, PLANNED  # imported here: defenses imports this module

        return frozenset([*DEFENSES, *PLANNED])
    if kind is PluginKind.SCENARIO:
        return frozenset(ScenarioId)
    if kind is PluginKind.MUTATOR:
        return frozenset(MutatorId)
    return frozenset()


def installed(kind: PluginKind) -> list[Plugin]:
    """Every installed plugin of a kind, ignored ones included, by name."""
    return sorted(
        (plugin for same in _scan(kind).values() for plugin in same),
        key=lambda plugin: (plugin.name, plugin.package),
    )


def names(kind: PluginKind) -> list[str]:
    """The plugin names a user can pick: installed, not built in and registered once."""
    builtin = builtin_names(kind)
    return sorted(
        name for name, same in _scan(kind).items() if len(same) == 1 and name not in builtin
    )


def find(kind: PluginKind, name: str) -> Plugin | None:
    """The plugin that registers `name`, or None when none does or the name is built in.

    Raises `PluginError` when more than one package registers it.
    """
    same = _scan(kind).get(name)
    if not same or name in builtin_names(kind):
        return None
    if len(same) > 1:
        packages = ", ".join(plugin.package for plugin in same)
        problem = f"is registered by more than one package ({packages}). Uninstall all but one."
        raise PluginError(f"{kind.noun} plugin {name!r} {problem}", problem)
    return same[0]


def _import(plugin: Plugin) -> Callable[..., object] | PluginError:
    if not DEFENSE_PART.fullmatch(plugin.name):
        return plugin.error("has a name Court can't use: use letters, digits, '_', '.' and '-'.")
    try:
        loaded = plugin.entry_point.load()
    except Exception as exc:  # anything the plugin's module raises on import
        return plugin.error(f"failed to load: {_one_line(exc)}")
    if not callable(loaded):
        return plugin.error(f"points at a {type(loaded).__name__}, not a class or function.")
    return loaded


def load(kind: PluginKind, name: str) -> Callable[..., object] | None:
    """What plugin `name` points at, imported on first use. None when no plugin has the name.

    Raises `PluginError` when the plugin can't load, every time it's asked for.
    """
    plugin = find(kind, name)
    if plugin is None:
        return None
    key = (kind, name)
    if key not in _loaded:
        _loaded[key] = _import(plugin)
    loaded = _loaded[key]
    if isinstance(loaded, PluginError):
        raise PluginError(str(loaded), loaded.problem)
    return loaded


def build(
    kind: PluginKind,
    name: str,
    *args: object,
    check: Callable[[object], bool],
    expected: str,
) -> object | None:
    """Call plugin `name` with `args` and return what it built. None when no plugin has the name.

    Raises `PluginError` when the plugin can't load, raises, or builds something `check`
    rejects. `expected` says what it should have built, such as "a Defense".
    """
    factory = load(kind, name)
    plugin = find(kind, name)
    if factory is None or plugin is None:
        return None
    try:
        built = factory(*args)
    except Exception as exc:
        raise plugin.error(f"raised {_one_line(exc)}") from exc
    if not check(built):
        raise plugin.error(f"built a {type(built).__name__}, not {expected}.")
    return built


def problem(plugin: Plugin) -> str | None:
    """What stops a user from picking this plugin, or None. Imports it to find out."""
    if plugin.name in builtin_names(plugin.kind):
        return f"ignored: {plugin.name} is built in"
    try:
        load(plugin.kind, plugin.name)
    except PluginError as exc:
        return exc.problem
    return None
