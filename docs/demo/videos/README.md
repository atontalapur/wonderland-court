# Backup demo videos

Screen recordings of the Courtroom, for when the live demo fails. Both are 1440x900 and have no audio.

- `wonderland-court-live-studio-demo.mp4` (2 min 52 s): a live run from the Choose Alice screen. Alice is local `llama3.1`, the scenario is The Refund Ledger, and the shields are No Shield against Full Royal Guard. No Shield refunds $400 on turn 1 and Full Royal Guard holds. Then Ask the Caterpillar recommends Full Royal Guard, and the seed-locked retrial takes the breach rate from 50% to 0%.
- `wonderland-court-benchmark-walkthrough.mp4` (2 min 34 s): the recorded #30 benchmark (`docs/benchmark/benchmark.db`). It steps through all 8 trials, then the Scoreboard and heatmap, then the Caterpillar's advice and the retrial (75% to 0% breach rate, 34% to 25% helpfulness).

Recorded with Playwright against `court serve` on 2026-11-22.
