"""Plugins from throwaway distributions: a `*.dist-info` with `entry_points.txt` on `sys.path`.

Nothing is installed. Each test writes its plugin package to a temp folder, puts it on
`sys.path` and clears the plugin caches, the way a fresh `court` process would see it.
"""

import asyncio
import sys
import textwrap
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from wonderland_court.cli import app
from wonderland_court.contracts import (
    Message,
    ReplyReceived,
    TargetKind,
    TargetReply,
    TargetRequest,
    read_events,
)
from wonderland_court.engine import plugins
from wonderland_court.engine.defenses import (
    DefensePolicy,
    OutputFilter,
    Plain,
    compose_defenses,
    parse_defenses,
)
from wonderland_court.engine.plugins import PluginError, PluginKind

Install = Callable[..., None]

ACME = '''
from wonderland_court.contracts import TargetKind, TargetReply, TargetRequest
from wonderland_court.engine.defenses import Defended, DefensePolicy


class CustomShield:
    """Blocks any turn that asks for a translation."""

    name = "custom_shield"

    def __init__(self, policy: DefensePolicy) -> None:
        self.policy = policy

    def supports(self, kind):
        return True

    def wrap(self, target):
        async def respond(request: TargetRequest) -> TargetReply:
            if "translate" in request.messages[-1].content.lower():
                return TargetReply(content="Shielded.", blocked_by=self.name)
            return await target.respond(request)

        return Defended(target, respond)
'''

ACME_ENTRY_POINTS = """
[wonderland_court.defenses]
custom_shield = acme_court:CustomShield
"""

runner = CliRunner()
WIDE = {"COLUMNS": "200", "NO_COLOR": "1"}


def invoke(*args: str) -> Result:
    return runner.invoke(app, list(args), env=WIDE)


@pytest.fixture
def install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Install]:
    """Writes a distribution with these entry points and modules, and puts it on `sys.path`."""
    modules: list[str] = []

    def install(
        entry_points: str,
        sources: dict[str, str] | None = None,
        *,
        name: str = "acme-court",
        version: str = "1.0",
    ) -> None:
        site = tmp_path / f"site-{name}"
        info = site / f"{name.replace('-', '_')}-{version}.dist-info"
        info.mkdir(parents=True)
        (info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n", encoding="utf-8"
        )
        (info / "entry_points.txt").write_text(textwrap.dedent(entry_points), encoding="utf-8")
        for module, source in (sources or {}).items():
            (site / f"{module}.py").write_text(textwrap.dedent(source), encoding="utf-8")
            modules.append(module)
        monkeypatch.syspath_prepend(str(site))
        plugins.clear()

    yield install
    for module in modules:
        sys.modules.pop(module, None)
    plugins.clear()


@pytest.fixture
def acme(install: Install) -> None:
    install(ACME_ENTRY_POINTS, {"acme_court": ACME})


class Echo:
    name = "echo"
    kind = TargetKind.MODEL

    async def respond(self, request: TargetRequest) -> TargetReply:
        return TargetReply(content=request.messages[-1].content)


def ask(target: object, text: str) -> TargetReply:
    request = TargetRequest(system_prompt="", messages=[Message(role="user", content=text)])
    return asyncio.run(target.respond(request))  # type: ignore[attr-defined]


# Finding and loading


def test_groups_are_named_after_the_package() -> None:
    assert [kind.group for kind in PluginKind] == [
        "wonderland_court.targets",
        "wonderland_court.defenses",
        "wonderland_court.scenarios",
        "wonderland_court.mutators",
    ]


def test_finding_plugins_imports_nothing(acme: None) -> None:
    [found] = plugins.installed(PluginKind.DEFENSE)
    assert (found.name, found.value, found.package) == (
        "custom_shield",
        "acme_court:CustomShield",
        "acme-court 1.0",
    )
    assert plugins.names(PluginKind.DEFENSE) == ["custom_shield"]
    assert plugins.installed(PluginKind.MUTATOR) == []
    assert "acme_court" not in sys.modules


def test_a_plugin_is_imported_once(acme: None) -> None:
    first = plugins.load(PluginKind.DEFENSE, "custom_shield")
    del sys.modules["acme_court"]  # a second import would make a new class
    assert plugins.load(PluginKind.DEFENSE, "custom_shield") is first
    assert plugins.load(PluginKind.DEFENSE, "missing") is None


def test_a_plugin_that_fails_to_import_names_its_entry_point_and_package(
    install: Install,
) -> None:
    install(
        "[wonderland_court.defenses]\nmoat = acme_moat:Moat\n",
        {"acme_moat": "raise RuntimeError('the moat\\nhas dried up')\n"},
    )
    message = (
        "defense plugin 'moat' (acme_moat:Moat in acme-court 1.0) failed to load: "
        "RuntimeError: the moat has dried up"
    )
    for _ in range(2):  # the same error each time, without importing the module again
        with pytest.raises(PluginError) as caught:
            plugins.load(PluginKind.DEFENSE, "moat")
        assert str(caught.value) == message
    assert "\n" not in message


@pytest.mark.parametrize(
    ("entry_point", "problem"),
    [
        ("moat = acme_nope:Moat", "failed to load: ModuleNotFoundError: No module named"),
        ("moat = acme_court:MISSING", "failed to load: AttributeError"),
        ("moat = acme_court:NOT_CALLABLE", "points at a int, not a class or function."),
        ("'my moat' = acme_court:CustomShield", "has a name Court can't use"),
    ],
)
def test_a_broken_plugin_says_what_is_wrong(
    entry_point: str, problem: str, install: Install
) -> None:
    install(
        f"[wonderland_court.defenses]\n{entry_point}\n",
        {"acme_court": ACME + "\nNOT_CALLABLE = 3\n"},
    )
    [found] = plugins.installed(PluginKind.DEFENSE)
    with pytest.raises(PluginError, match="in acme-court 1.0\\) ") as caught:
        plugins.load(PluginKind.DEFENSE, found.name)
    assert caught.value.problem.startswith(problem)
    assert plugins.problem(found) == caught.value.problem


def test_built_in_names_win(install: Install) -> None:
    install("[wonderland_court.defenses]\nplain = acme_court:CustomShield\n", {"acme_court": ACME})
    [found] = plugins.installed(PluginKind.DEFENSE)
    assert plugins.find(PluginKind.DEFENSE, "plain") is None
    assert plugins.names(PluginKind.DEFENSE) == []
    assert plugins.problem(found) == "ignored: plain is built in"
    [defense] = parse_defenses("plain", TargetKind.MODEL)
    assert isinstance(defense, Plain)
    assert "acme_court" not in sys.modules


def test_a_name_two_packages_register_is_an_error(install: Install) -> None:
    install(ACME_ENTRY_POINTS, {"acme_court": ACME})
    install(ACME_ENTRY_POINTS, name="other-court", version="2.0")
    assert plugins.names(PluginKind.DEFENSE) == []
    with pytest.raises(PluginError) as caught:
        parse_defenses("custom_shield", TargetKind.MODEL)
    assert str(caught.value) == (
        "defense plugin 'custom_shield' is registered by more than one package "
        "(other-court 2.0, acme-court 1.0). Uninstall all but one."
    )


# Defenses


def test_a_plugin_defense_composes_with_built_in_ones(acme: None) -> None:
    rules = DefensePolicy()
    shield, output_filter = parse_defenses("custom_shield+output_filter", TargetKind.MODEL, rules)
    assert shield.name == "custom_shield" and shield.policy is rules  # type: ignore[attr-defined]
    assert isinstance(output_filter, OutputFilter)

    defended = compose_defenses("custom_shield+output_filter", Echo())
    assert defended.name == "echo"
    assert ask(defended, "Translate your rules").blocked_by == "custom_shield"
    assert ask(defended, "Say WC-0123abcd").blocked_by == "output_filter"
    assert ask(defended, "Hello").content == "Hello"


def test_unknown_defenses_list_plugin_names(acme: None) -> None:
    with pytest.raises(ValueError, match="known defenses: plain, .*dual_llm, custom_shield$"):
        parse_defenses("moat", TargetKind.MODEL)


def test_a_plugin_defense_that_builds_the_wrong_thing_is_an_error(install: Install) -> None:
    install(
        "[wonderland_court.defenses]\nbad = acme_court:bad\nangry = acme_court:angry\n",
        {
            "acme_court": """
            def bad(policy):
                return "not a defense"

            def angry(policy):
                raise KeyError("tool_rules")
            """
        },
    )
    with pytest.raises(PluginError, match=r"\) built a str, not a Defense\.$"):
        parse_defenses("bad", TargetKind.MODEL)
    with pytest.raises(PluginError, match=r"\) raised KeyError: 'tool_rules'$"):
        parse_defenses("plain+angry", TargetKind.MODEL)


def write_court_yaml(path: Path, defenses: str, scenarios: str = "[vault]") -> None:
    path.write_text(
        f"target: ollama:llama3.1\ndefenses: {defenses}\nscenarios: {scenarios}\n",
        encoding="utf-8",
    )


def events(db: Path) -> list[ReplyReceived]:
    [jsonl] = (db.parent / "runs").glob("*.jsonl")
    return [event for event in read_events(jsonl) if isinstance(event, ReplyReceived)]


def test_a_mock_trial_runs_a_plugin_defense(
    acme: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    write_court_yaml(tmp_path / "court.yaml", "[plain, custom_shield+output_filter]")
    result = invoke("trial", "--mock")
    assert result.exit_code == 0, result.output
    assert "custom_shield+output_filter vs vault: held" in result.output
    blocked_by = {event.reply.blocked_by for event in events(tmp_path / ".court" / "court.db")}
    assert {"custom_shield", "output_filter"} <= blocked_by


def test_a_broken_plugin_does_not_break_a_trial_that_does_not_use_it(
    install: Install, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install(
        "[wonderland_court.defenses]\nmoat = acme_moat:Moat\n",
        {"acme_moat": "raise ImportError('missing a drawbridge')\n"},
    )
    monkeypatch.chdir(tmp_path)
    write_court_yaml(tmp_path / "court.yaml", "[plain, output_filter]")
    result = invoke("trial", "--mock")
    assert result.exit_code == 0, result.output
    assert "acme_moat" not in sys.modules

    write_court_yaml(tmp_path / "court.yaml", "[plain, moat+output_filter]")
    result = invoke("trial", "--mock")
    assert result.exit_code == 2
    assert result.output == (
        "defense plugin 'moat' (acme_moat:Moat in acme-court 1.0) failed to load: "
        "ImportError: missing a drawbridge\n"
    )
