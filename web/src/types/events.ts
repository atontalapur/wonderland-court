export type ScenarioId =
  | "vault"
  | "system_prompt"
  | "refund_tool"
  | "drink_me"
  | "mcp_poison";

export type TargetKind = "model" | "agent";
export type MatchMode = "fixed" | "adaptive";
export type Ruling = "leak" | "held";
export type JudgeLayer = "canary" | "tool_call" | "similarity" | "llm";

export type TechniqueFamily =
  | "direct_ask"
  | "role_play"
  | "indirect_injection"
  | "authority"
  | "encoding"
  | "foot_in_the_door"
  | "autoadv"
  | "pair"
  | "tap"
  | "agentdojo"
  | "bipia"
  | "rag_n_roll"
  | "encoding_smuggling"
  | "multilingual"
  | "mcp_tool_poisoning"
  | "jailbreakbench"
  | "harmbench"
  | "camel_dual_flow";

export type MutatorId =
  | "homoglyphs"
  | "spaced_letters"
  | "base64"
  | "caesar"
  | "low_resource_language"
  | "mixed_language"
  | "riddle"
  | "junk_tokens";

export interface Message {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  tool_call_id?: string | null;
}

export interface ToolSpec {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export type DocumentKind = "email" | "web_page" | "tool_output";

export interface Document {
  id: string;
  kind: DocumentKind;
  title: string;
  body: string;
  poisoned: boolean;
}

export interface ToolRule {
  tool: string;
  argument: string;
  max_value: number | null;
  allowed_suffix: string | null;
  description: string;
}

export interface Stakes {
  scenario: ScenarioId;
  objective: string;
  canary: string;
  protected_text: string | null;
  tool_rules: ToolRule[];
}

export interface TargetReply {
  content: string;
  tool_calls: ToolCall[];
  blocked_by: string | null;
  latency_ms: number;
}

export interface Attack {
  family: string;
  mutators: string[];
  message: string;
  document: Document | null;
  /** The Cat's text before mutation. Missing in events recorded before it existed. */
  payload?: string | null;
}

export interface Verdict {
  ruling: Ruling;
  layer: JudgeLayer;
  confidence: number;
  reason: string;
}

export interface Turn {
  index: number;
  attack: Attack;
  reply: TargetReply;
  verdict: Verdict;
}

export interface MatchSpec {
  match_id: string;
  round: number;
  target: string;
  target_kind: TargetKind;
  defense: string;
  scenario: ScenarioId;
  attacker: string;
  mode: MatchMode;
  family: string | null;
  enabled_families: TechniqueFamily[] | null;
  enabled_mutators: MutatorId[] | null;
  max_turns: number;
  seed: number;
}

export interface Standing {
  defense: string;
  elo: number;
  matches: number;
  attack_success: number;
  ci_low: number;
  ci_high: number;
  mean_turns_to_break: number | null;
  utility: number | null;
}

export interface EventBase {
  v: 1;
  seq: number;
  ts: string;
  run_id: string;
}

export interface RunStartedEvent extends EventBase {
  type: "run_started";
  targets: string[];
  defenses: string[];
  scenarios: ScenarioId[];
  mode: MatchMode;
  rounds: number;
}

export interface MatchStartedEvent extends EventBase {
  type: "match_started";
  match: MatchSpec;
  stakes: Stakes;
}

export interface AttackSentEvent extends EventBase {
  type: "attack";
  match_id: string;
  turn: number;
  attack: Attack;
}

export interface ReplyReceivedEvent extends EventBase {
  type: "reply";
  match_id: string;
  turn: number;
  reply: TargetReply;
}

export interface VerdictRuledEvent extends EventBase {
  type: "verdict";
  match_id: string;
  turn: number;
  verdict: Verdict;
}

export interface MatchEndedEvent extends EventBase {
  type: "match_ended";
  match_id: string;
  broken: boolean;
  turns: number;
  broken_on_turn: number | null;
  breaking_family: string | null;
}

export interface StandingsUpdatedEvent extends EventBase {
  type: "standings";
  round: number;
  standings: Standing[];
}

export interface RunEndedEvent extends EventBase {
  type: "run_ended";
  matches: number;
  leaks: number;
}

export type CourtEvent =
  | RunStartedEvent
  | MatchStartedEvent
  | AttackSentEvent
  | ReplyReceivedEvent
  | VerdictRuledEvent
  | MatchEndedEvent
  | StandingsUpdatedEvent
  | RunEndedEvent;

// Read-side Courtroom models (src/wonderland_court/courtroom/models.py)

export interface RunSummary {
  run_id: string;
  mode: MatchMode;
  targets: string[];
  defenses: string[];
  scenarios: ScenarioId[];
  rounds: number;
  matches: number;
  leaks: number;
  status: "running" | "completed";
  source: "sqlite" | "jsonl" | "static";
}

export interface HeatmapCell {
  defense: string;
  family: string;
  scenario: ScenarioId;
  matches: number;
  leaks: number;
  asr: number;
  match_ids: string[];
}

export interface HeatmapData {
  run_id: string;
  defenses: string[];
  families: string[];
  scenarios: ScenarioId[];
  cells: HeatmapCell[];
}

export interface MatchTranscript {
  match: MatchSpec;
  stakes: Stakes;
  turns: Turn[];
  broken: boolean;
  broken_on_turn: number | null;
  breaking_family: string | null;
  status: "running" | "broken" | "held";
}

export interface CalibrationSummary {
  run_id: string;
  total_exact_checked: number;
  llm_evaluated: number;
  agreement_count: number;
  agreement_rate: number;
  false_positives: number;
  false_negatives: number;
}

export interface FailureClusterView {
  cluster_id: string;
  family_label: string;
  technique_family: string;
  scenario: ScenarioId;
  count: number;
  example_match_ids: string[];
  root_cause_summary: string;
}

export interface RemediationAdviceView {
  run_id: string;
  target_kind: string;
  clusters: FailureClusterView[];
  recommended_defense: string;
  config_patch_yaml: string;
  rationale: string;
}

export interface RetrialComparisonView {
  baseline_run_id: string;
  retrial_run_id: string;
  matched_seeds: number[];
  baseline_asr: number;
  retrial_asr: number;
  asr_delta: number;
  baseline_utility: number | null;
  retrial_utility: number | null;
  per_scenario_diff: Record<string, Record<string, number>>;
}

export interface RunBundle {
  summary: RunSummary;
  events: CourtEvent[];
  matches: MatchTranscript[];
  standings: Standing[];
  heatmap: HeatmapData;
  calibration: CalibrationSummary | null;
  advice: RemediationAdviceView | null;
  retrial: RetrialComparisonView | null;
}

export type StreamConnectionMode = "live" | "replaying" | "static" | "disconnected";

export interface HealthResponse {
  status: string;
  mode?: "live" | "replay" | "static";
  replay?: boolean;
  active_run_id?: string | null;
  studio_enabled?: boolean;
}

export interface StudioJob {
  job_id: string;
  kind: "trial" | "advise" | "retrial";
  status: "running" | "completed" | "failed";
  run_id: string | null;
  retrial_run_id: string | null;
  progress_done: number;
  progress_total: number;
  message: string;
  error: string | null;
}

export interface StudioOptions {
  ollama_available: boolean;
  ollama_models: string[];
  embed_models: string[];
  scenarios: ScenarioId[];
  defenses: string[];
  default_defenses: string[];
  active_job: StudioJob | null;
}

export interface StartTrialPayload {
  target: string;
  scenarios: ScenarioId[];
  defenses: string[];
  mode: MatchMode;
  rounds: number;
  max_turns: number;
  utility?: boolean;
}

export interface StaticManifest {
  runs: RunSummary[];
  default_run_id?: string;
}
