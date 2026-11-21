-- Wonderland Court store. One writer task owns writes; `court serve` opens it read-only.
-- Frozen for wave 1 and wave 2: add tables or columns in a PR all three tracks review.
-- Every statement is idempotent, so the store can apply this file on every start.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    parent_run_id TEXT,          -- the baseline run, for a retrial
    created_at TEXT,
    mode TEXT,
    target TEXT,
    target_kind TEXT,
    config_json TEXT,
    status TEXT
);

-- The event stream, one row per line of `dump_event(event)` from contracts/events.py.
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER NOT NULL,
    run_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    event_json TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    round INTEGER,
    target TEXT,
    target_kind TEXT,
    defense TEXT,
    scenario TEXT,
    mode TEXT,
    family TEXT,
    seed INTEGER,
    broken INTEGER,
    turns INTEGER,
    broken_on_turn INTEGER,
    breaking_family TEXT
);
CREATE INDEX IF NOT EXISTS matches_by_run ON matches (run_id);

CREATE TABLE IF NOT EXISTS standings (
    run_id TEXT NOT NULL,
    round INTEGER NOT NULL,
    defense TEXT NOT NULL,
    elo REAL,
    matches INTEGER,
    attack_success REAL,
    ci_low REAL,
    ci_high REAL,
    mean_turns_to_break REAL,
    utility REAL,
    PRIMARY KEY (run_id, round, defense)
);

-- The Dodo's benign-task results.
CREATE TABLE IF NOT EXISTS utility_results (
    run_id TEXT NOT NULL,
    defense TEXT NOT NULL,
    scenario TEXT NOT NULL,
    pass_rate REAL,
    false_refusal_rate REAL,
    details_json TEXT,
    PRIMARY KEY (run_id, defense, scenario)
);

-- How often the LLM judge agrees with the exact checks.
CREATE TABLE IF NOT EXISTS judge_calibration (
    run_id TEXT PRIMARY KEY,
    total_exact_checked INTEGER,
    llm_evaluated INTEGER,
    agreement_count INTEGER,
    agreement_rate REAL,
    false_positives INTEGER,
    false_negatives INTEGER
);

-- Advice from a Caterpillar.
CREATE TABLE IF NOT EXISTS remediation_advice (
    run_id TEXT PRIMARY KEY,
    target_kind TEXT,
    clusters_json TEXT,
    recommended_defense TEXT,
    config_patch_yaml TEXT,
    rationale TEXT
);

CREATE TABLE IF NOT EXISTS retrial_comparisons (
    retrial_run_id TEXT PRIMARY KEY,
    baseline_run_id TEXT NOT NULL,
    matched_seeds_json TEXT,
    baseline_asr REAL,
    retrial_asr REAL,
    asr_delta REAL,
    baseline_utility REAL,
    retrial_utility REAL,
    per_scenario_json TEXT
);

-- Responses to temperature-0 calls, keyed by llm.cache_key().
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    reply_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
