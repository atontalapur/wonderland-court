import {
  Check,
  ChevronRight,
  Cpu,
  Globe,
  Loader2,
  Sparkles,
  Zap,
} from "lucide-react";
import { useEffect, useState } from "react";
import {
  CHARACTERS,
  formatDefenseName,
  formatScenario,
} from "../theme/wonderland";
import type {
  ScenarioId,
  StartTrialPayload,
  StudioJob,
  StudioOptions,
} from "../types/events";
import { CharacterAvatar } from "./CharacterAvatar";

interface TrialSetupPanelProps {
  options: StudioOptions | null;
  activeJob: StudioJob | null;
  hasExistingRuns: boolean;
  onStartTrial: (payload: StartTrialPayload) => Promise<void>;
  onSkipToExisting?: () => void;
}

const OTHER_MODEL_PRESETS = [
  { label: "OpenAI GPT-4o Mini", spec: "openai:gpt-4o-mini" },
  { label: "Anthropic Claude Haiku", spec: "anthropic:claude-3-5-haiku-latest" },
  {
    label: "LM Studio / Local OpenAI API",
    spec: "openai-compat:http://localhost:1234/v1|local-model",
  },
];

export function TrialSetupPanel({
  options,
  activeJob,
  hasExistingRuns,
  onStartTrial,
  onSkipToExisting,
}: TrialSetupPanelProps) {
  const ollamaModels = options?.ollama_models ?? [];
  const availableScenarios = options?.scenarios ?? [
    "refund_tool",
    "vault",
    "system_prompt",
    "drink_me",
    "mcp_poison",
  ];
  const availableDefenses = options?.defenses ?? [
    "plain",
    "sandwich",
    "spotlighting",
    "spotlighting+output_filter",
  ];

  const [modelMode, setModelMode] = useState<"local" | "mock" | "custom">(
    ollamaModels.length > 0 ? "local" : "mock"
  );
  const [selectedOllama, setSelectedOllama] = useState<string>(
    ollamaModels[0] ?? ""
  );
  const [customSpec, setCustomSpec] = useState<string>("openai:gpt-4o-mini");
  const [selectedScenarios, setSelectedScenarios] = useState<ScenarioId[]>([
    "refund_tool",
    "vault",
  ]);
  const [selectedDefenses, setSelectedDefenses] = useState<string[]>([
    "plain",
    "sandwich",
    "spotlighting",
    "spotlighting+output_filter",
  ]);
  const [speedPreset, setSpeedPreset] = useState<"quick" | "thorough">("quick");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (ollamaModels.length > 0 && !selectedOllama) {
      setSelectedOllama(ollamaModels[0]);
      setModelMode("local");
    }
  }, [ollamaModels, selectedOllama]);

  const isRunning = activeJob?.status === "running";

  const toggleScenario = (sc: ScenarioId) => {
    setSelectedScenarios((prev) =>
      prev.includes(sc)
        ? prev.length > 1
          ? prev.filter((x) => x !== sc)
          : prev
        : [...prev, sc]
    );
  };

  const toggleDefense = (def: string) => {
    setSelectedDefenses((prev) =>
      prev.includes(def)
        ? prev.length > 1
          ? prev.filter((x) => x !== def)
          : prev
        : [...prev, def]
    );
  };

  const resolvedTarget =
    modelMode === "mock"
      ? "mock"
      : modelMode === "local"
        ? selectedOllama
          ? `ollama:${selectedOllama}`
          : "mock"
        : customSpec.trim();

  const totalMatches =
    selectedScenarios.length *
    selectedDefenses.length *
    (speedPreset === "quick" ? 1 : 2);

  const handleLaunch = async () => {
    if (!resolvedTarget) {
      setFormError("Please enter or select a model to test as Alice.");
      return;
    }
    setFormError(null);
    setSubmitting(true);
    try {
      await onStartTrial({
        target: resolvedTarget,
        scenarios: selectedScenarios,
        defenses: selectedDefenses,
        mode: "adaptive",
        rounds: speedPreset === "quick" ? 1 : 2,
        max_turns: speedPreset === "quick" ? 3 : 4,
        utility: false,
      });
    } catch (err) {
      setFormError(
        err instanceof Error ? err.message : "Could not start the trial."
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="animate-page-in space-y-6" data-testid="trial-setup-panel">
      {/* Storybook Welcome Banner */}
      <section className="storybook-card flex flex-col items-center gap-5 rounded-3xl bg-gradient-to-r from-[#fffdf9] via-[#f4f8fd] to-[#fffdf9] p-6 sm:flex-row sm:px-8">
        <CharacterAvatar character={CHARACTERS.alice} size="lg" showLabel={false} />
        <div className="flex-1 text-center sm:text-left">
          <h2 className="font-editorial text-2xl font-bold text-[#231f1a]">
            Put an AI Model on Trial as Alice
          </h2>
          <p className="mt-1 text-sm leading-relaxed text-[#5c4f41]">
            Pick any model on your laptop (or a cloud/custom endpoint), choose
            which Wonderland traps to run, and click <strong>Begin the Trial</strong>.
            Everything runs right here on your machine.
          </p>
        </div>

        {hasExistingRuns && onSkipToExisting && (
          <button
            type="button"
            onClick={onSkipToExisting}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-[#dec8a4] bg-[#fffdf9] px-4 py-2 text-xs font-semibold text-[#4a3b2c] transition hover:border-[#2b5b84] hover:text-[#2b5b84]"
          >
            View Saved Trials
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        )}
      </section>

      {/* Step A: Choose Alice's Model */}
      <section className="storybook-card rounded-3xl p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="font-editorial text-lg font-bold text-[#231f1a]">
              1. Choose Who Plays Alice
            </h3>
            <p className="text-xs text-[#6b5e4e]">
              {options?.ollama_available && ollamaModels.length > 0
                ? `Found ${ollamaModels.length} local Ollama models on this machine.`
                : "Test instantly offline, or connect Ollama / OpenAI / Anthropic / any custom model."}
            </p>
          </div>
        </div>

        {/* 3 Clean Source Tabs */}
        <div className="mb-4 grid grid-cols-1 gap-2.5 sm:grid-cols-3">
          <button
            type="button"
            onClick={() => setModelMode("local")}
            disabled={ollamaModels.length === 0}
            className={`flex items-center gap-3 rounded-2xl border-2 px-4 py-3 text-left transition ${
              modelMode === "local"
                ? "border-[#2b5b84] bg-[#eff6ff] text-[#1e4568]"
                : "border-[#e9dcc6] bg-[#faf4e8]/60 text-[#4a3b2c] hover:border-[#cfb489] disabled:cursor-not-allowed disabled:opacity-50"
            }`}
          >
            <Cpu className="h-5 w-5 shrink-0" />
            <div>
              <div className="text-sm font-bold">Local Ollama Model</div>
              <div className="text-[11px] opacity-80">
                {ollamaModels.length > 0
                  ? `${ollamaModels.length} installed locally`
                  : "Ollama not detected"}
              </div>
            </div>
          </button>

          <button
            type="button"
            onClick={() => setModelMode("mock")}
            className={`flex items-center gap-3 rounded-2xl border-2 px-4 py-3 text-left transition ${
              modelMode === "mock"
                ? "border-[#2b5b84] bg-[#eff6ff] text-[#1e4568]"
                : "border-[#e9dcc6] bg-[#faf4e8]/60 text-[#4a3b2c] hover:border-[#cfb489]"
            }`}
          >
            <Zap className="h-5 w-5 shrink-0" />
            <div>
              <div className="text-sm font-bold">Instant Demo Alice</div>
              <div className="text-[11px] opacity-80">
                Offline · finishes in ~2 seconds
              </div>
            </div>
          </button>

          <button
            type="button"
            onClick={() => setModelMode("custom")}
            className={`flex items-center gap-3 rounded-2xl border-2 px-4 py-3 text-left transition ${
              modelMode === "custom"
                ? "border-[#2b5b84] bg-[#eff6ff] text-[#1e4568]"
                : "border-[#e9dcc6] bg-[#faf4e8]/60 text-[#4a3b2c] hover:border-[#cfb489]"
            }`}
          >
            <Globe className="h-5 w-5 shrink-0" />
            <div>
              <div className="text-sm font-bold">Other / Cloud Model</div>
              <div className="text-[11px] opacity-80">
                OpenAI, Anthropic, LM Studio, HTTP
              </div>
            </div>
          </button>
        </div>

        {/* Local Ollama Model Cards */}
        {modelMode === "local" && ollamaModels.length > 0 && (
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {ollamaModels.map((model) => {
              const active = selectedOllama === model;
              return (
                <button
                  key={model}
                  type="button"
                  onClick={() => setSelectedOllama(model)}
                  className={`flex items-center justify-between gap-2 rounded-xl border-2 px-3.5 py-2.5 text-left text-xs font-semibold transition ${
                    active
                      ? "border-[#2b5b84] bg-[#eff6ff] text-[#1e4568] shadow-sm"
                      : "border-[#e9dcc6] bg-[#fffdf9] text-[#3a3026] hover:border-[#cfb489]"
                  }`}
                >
                  <span className="truncate font-mono">{model}</span>
                  {active && <Check className="h-4 w-4 shrink-0 text-[#2b5b84]" />}
                </button>
              );
            })}
          </div>
        )}

        {/* Mock Info */}
        {modelMode === "mock" && (
          <div className="rounded-2xl border border-[#e4d2b4] bg-[#faf4e8] px-4 py-3 text-xs text-[#5c4f41]">
            Runs a complete offline trial with scripted Wonderland attackers,
            Alice, and the Queen of Hearts — ideal for testing the full workflow
            (Trial → Scoreboard → Caterpillar’s Fix → Retrial) in seconds.
          </div>
        )}

        {/* Custom / Other Model Input */}
        {modelMode === "custom" && (
          <div className="space-y-3 rounded-2xl border border-[#e4d2b4] bg-[#faf4e8]/70 p-4">
            <label className="block text-xs font-semibold text-[#3a3026]">
              Model or Agent Spec
              <input
                type="text"
                value={customSpec}
                onChange={(e) => setCustomSpec(e.target.value)}
                placeholder="openai:gpt-4o-mini or anthropic:claude-3-5-haiku-latest or ollama:llama3.1"
                className="mt-1.5 w-full rounded-xl border border-[#d6be96] bg-[#fffdf9] px-3.5 py-2 font-mono text-xs text-[#231f1a] focus:border-[#2b5b84] focus:outline-none"
              />
            </label>

            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] font-medium text-[#6b5e4e]">
                Quick fill:
              </span>
              {OTHER_MODEL_PRESETS.map((p) => (
                <button
                  key={p.spec}
                  type="button"
                  onClick={() => setCustomSpec(p.spec)}
                  className="rounded-full border border-[#dec8a4] bg-[#fffdf9] px-2.5 py-1 text-[11px] font-semibold text-[#4a3b2c] transition hover:border-[#2b5b84] hover:text-[#2b5b84]"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* Step B: Scenarios & Defenses */}
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        <section className="storybook-card rounded-3xl p-6">
          <h3 className="font-editorial text-lg font-bold text-[#231f1a]">
            2. Pick Wonderland Scenarios
          </h3>
          <p className="mt-0.5 text-xs text-[#6b5e4e]">
            Which rules should Alice try to protect?
          </p>

          <div className="mt-4 space-y-2">
            {availableScenarios.map((sc) => {
              const meta = formatScenario(sc);
              const checked = selectedScenarios.includes(sc);
              return (
                <button
                  key={sc}
                  type="button"
                  onClick={() => toggleScenario(sc)}
                  className={`flex w-full items-center justify-between gap-3 rounded-xl border-2 px-3.5 py-2.5 text-left transition ${
                    checked
                      ? "border-[#2b5b84] bg-[#eff6ff]"
                      : "border-[#efe2cc] bg-[#fffdf9] hover:border-[#cfb489]"
                  }`}
                >
                  <div className="flex items-center gap-2.5">
                    <span className="text-base" aria-hidden="true">
                      {meta.emoji}
                    </span>
                    <div>
                      <div className="text-xs font-bold text-[#231f1a]">
                        {meta.title}
                      </div>
                      <div className="text-[11px] text-[#6b5e4e]">
                        {meta.shortGoal}
                      </div>
                    </div>
                  </div>
                  <span
                    className={`flex h-5 w-5 items-center justify-center rounded-full border ${
                      checked
                        ? "border-[#2b5b84] bg-[#2b5b84] text-white"
                        : "border-[#cfb489] bg-white"
                    }`}
                  >
                    {checked && <Check className="h-3 w-3" />}
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="storybook-card flex flex-col justify-between rounded-3xl p-6">
          <div>
            <h3 className="font-editorial text-lg font-bold text-[#231f1a]">
              3. Pick Shields to Compare
            </h3>
            <p className="mt-0.5 text-xs text-[#6b5e4e]">
              Compare Alice with no shield vs. hardened defenses.
            </p>

            <div className="mt-4 flex flex-wrap gap-2">
              {availableDefenses.map((def) => {
                const checked = selectedDefenses.includes(def);
                return (
                  <button
                    key={def}
                    type="button"
                    onClick={() => toggleDefense(def)}
                    className={`inline-flex items-center gap-1.5 rounded-full border-2 px-3 py-1.5 text-xs font-semibold transition ${
                      checked
                        ? "border-[#2b5b84] bg-[#eff6ff] text-[#1e4568]"
                        : "border-[#e9dcc6] bg-[#fffdf9] text-[#5c4f41] hover:border-[#cfb489]"
                    }`}
                  >
                    {checked && <Check className="h-3.5 w-3.5" />}
                    <span>{formatDefenseName(def)}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="mt-6 border-t border-[#efe2cc] pt-4">
            <div className="mb-2 text-xs font-bold text-[#4a3b2c]">
              Trial Length
            </div>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setSpeedPreset("quick")}
                className={`rounded-xl border-2 px-3 py-2 text-left text-xs transition ${
                  speedPreset === "quick"
                    ? "border-[#2b5b84] bg-[#eff6ff] text-[#1e4568]"
                    : "border-[#e9dcc6] bg-[#fffdf9] text-[#5c4f41]"
                }`}
              >
                <div className="font-bold">Quick (Recommended)</div>
                <div className="text-[11px] opacity-80">1 round · 3 turns</div>
              </button>
              <button
                type="button"
                onClick={() => setSpeedPreset("thorough")}
                className={`rounded-xl border-2 px-3 py-2 text-left text-xs transition ${
                  speedPreset === "thorough"
                    ? "border-[#2b5b84] bg-[#eff6ff] text-[#1e4568]"
                    : "border-[#e9dcc6] bg-[#fffdf9] text-[#5c4f41]"
                }`}
              >
                <div className="font-bold">Thorough</div>
                <div className="text-[11px] opacity-80">2 rounds · 4 turns</div>
              </button>
            </div>
          </div>
        </section>
      </div>

      {formError && (
        <div className="rounded-2xl border border-[#f5b7c2] bg-[#fff1f2] px-4 py-3 text-xs font-medium text-[#a5152e]">
          {formError}
        </div>
      )}

      {/* Big Primary Launch Footer */}
      <div className="storybook-card flex flex-wrap items-center justify-between gap-4 rounded-3xl bg-[#faf4e8]/90 px-6 py-4">
        <div className="text-xs text-[#5c4f41]">
          Ready to run{" "}
          <strong className="text-[#231f1a]">{totalMatches} trials</strong>{" "}
          against{" "}
          <span className="rounded bg-[#efe2cc] px-1.5 py-0.5 font-mono font-semibold text-[#231f1a]">
            {resolvedTarget || "—"}
          </span>
        </div>

        <button
          type="button"
          disabled={submitting || isRunning}
          onClick={handleLaunch}
          className="inline-flex items-center gap-2 rounded-2xl bg-[#c81e3a] px-6 py-3 text-sm font-bold text-white shadow-md transition hover:bg-[#a5152e] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting || isRunning ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>Starting Trial…</span>
            </>
          ) : (
            <>
              <Sparkles className="h-4 w-4" />
              <span>Begin the Trial</span>
              <ChevronRight className="h-4 w-4" />
            </>
          )}
        </button>
      </div>
    </div>
  );
}
