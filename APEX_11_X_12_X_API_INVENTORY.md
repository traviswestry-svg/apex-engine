# Complete Flask API Inventory

```text
APEX Trade Command Center routes registered (sandbox).
APEX Active Trade Director routes registered (8.0_ACTIVE_TRADE_DIRECTOR).
APEX Range Intelligence routes registered (7.2_RANGE_INTELLIGENCE_ENGINE).
APEX Confluence route registered (7.5.3_CONFLUENCE_SYNTHESIZER).
APEX Event Intelligence route registered (10.0.0_EVENT_INTELLIGENCE).
APEX Decision Intelligence route registered (7.5.7_DECISION_INTELLIGENCE).
APEX Premium Strategy routes registered (7.7.0_PREMIUM_CHAIN_PRICED).
APEX Institutional Narrative/Replay routes registered (11.2/11.3).
APEX Probability Distribution route registered (11.0.0).
APEX Confirmation Scanner route registered (11.0.0).
APEX Flow Classifier routes registered (9.2.0_FLOW_CLASSIFIER).
APEX Flow Clusters routes registered (9.3.0_FLOW_CLUSTERS).
APEX Flow P/L routes registered (9.4.0_FLOW_PL).
APEX Flow P/L scanner sampling ENABLED (sessions: MARKET_OPEN).
APEX Feature Store routes registered (9.5.0_FEATURE_STORE).
APEX 10 provenance routes registered.
APEX 10 similarity routes registered.
APEX 10 learning routes registered.
APEX 10 dashboard evidence route registered.
APEX 10 institutional state routes registered.
APEX 11.4-12.3 institutional roadmap routes registered.
APEX Release Manager routes registered (11.0.0_RELEASE_MANAGER) — /api/system/{version,build,features,migrations,integrity,release}.
APEX 10 production readiness routes registered.
APEX Operations Center routes registered (11.0D).
APEX Institutional Execution OS routes registered (11.1).
GET        /
GET        /apex_os
GET        /apex_os/adaptive_learning
GET        /apex_os/execution
GET        /apex_os/institutional_intelligence
GET        /apex_os/institutional_research
GET        /apex_os/operations
GET        /apex_os/readiness
GET        /apex_os/trade_command
GET        /api/active_trade_director
GET,POST   /api/active_trade_director/evaluate
GET        /api/active_trade_director/log
POST       /api/active_trade_director/reset
GET        /api/active_trade_director/scorecard
GET        /api/active_trade_director/timeline
GET        /api/apex10/evidence
GET        /api/apex_signals
GET        /api/assistant
GET        /api/auction_intelligence
GET        /api/auction_state
GET        /api/backtest_stats
GET        /api/broker/etrade/accounts
GET        /api/broker/etrade/status
GET        /api/chart_data
GET        /api/charts/state
GET        /api/confidence_timeline
POST       /api/confidence_timeline/reset
GET        /api/confirmation_scan
GET        /api/confirmation_scan/health
GET        /api/confluence
GET        /api/consensus
GET        /api/consensus/contributors
GET        /api/consensus/history
GET        /api/conviction
GET        /api/conviction/contributors
GET        /api/dealer_positioning
GET        /api/decay
GET        /api/decision
GET        /api/decision-replay/<recommendation_id>
GET        /api/decision-review/<recommendation_id>
POST       /api/decision-review/<recommendation_id>/snapshot
GET        /api/decision_trace
GET        /api/diagnostics
GET        /api/diagnostics/es_ticker
GET        /api/diagnostics/gamma
GET        /api/edge_stats
GET        /api/endpoints
GET        /api/endpoints/<category>
GET        /api/endpoints/openapi
GET        /api/endpoints/search
GET        /api/endpoints/stats
GET        /api/engine_health
GET        /api/events
GET        /api/evidence_graph
GET        /api/execution/fill-probability
GET        /api/execution/liquidity
GET        /api/execution/position-quality
GET        /api/execution/quality
GET        /api/execution/score
GET        /api/execution/simulator
GET        /api/execution/slippage
GET        /api/execution_intelligence
GET        /api/feature_store/coverage
GET        /api/feature_store/health
GET        /api/feature_store/sample/<sample_id>
GET        /api/feature_store/samples
GET        /api/flow
GET        /api/flow/<ticker>
GET        /api/flow_classifier
GET        /api/flow_classifier/health
GET        /api/flow_clusters
GET        /api/flow_clusters/health
GET        /api/flow_pl
GET        /api/flow_pl/health
GET        /api/flow_tape
GET        /api/gameplan
GET        /api/heatmap
GET        /api/history/calibration-readiness
GET        /api/history/confidence-calibration
GET        /api/history/coverage
POST       /api/history/outcomes
GET        /api/history/quality
GET        /api/history/scorecard
GET        /api/history/status
GET        /api/institutional-consensus
GET        /api/institutional-conviction
GET        /api/institutional-decision
GET        /api/institutional-decision/<recommendation_id>
GET        /api/institutional-narrative
GET        /api/institutional_intelligence
GET        /api/institutional_os
GET        /api/institutional_state
GET        /api/learning/apply
GET        /api/learning/audit
GET        /api/learning/calibration
GET        /api/learning/candidates
POST       /api/learning/candidates
GET        /api/learning/candidates/<candidate_id>
POST       /api/learning/candidates/<candidate_id>/approve-shadow
POST       /api/learning/candidates/<candidate_id>/rollback
GET        /api/learning/drift
GET        /api/learning/outcomes/<sample_id>
POST       /api/learning/policies/<policy_id>/promote
POST       /api/learning/proposals
GET        /api/learning/readiness
GET        /api/learning/status
GET        /api/market_drivers
GET        /api/market_health
GET        /api/market_state
GET        /api/market_status
GET        /api/market_story
GET        /api/mission_control
GET        /api/narrative
GET        /api/narrative/invalidation
GET        /api/narrative/risks
GET        /api/narrative/story
GET        /api/narrative/thesis
GET        /api/nine_engines
GET        /api/options_chain_intelligence
GET        /api/overnight_briefing
GET        /api/performance
GET,POST   /api/position
POST       /api/position/clear
GET        /api/premium_strategy
GET        /api/premium_strategy/scorecard
GET        /api/probability_distribution
GET        /api/probability_distribution/health
GET        /api/provenance/<sample_id>
GET        /api/range_intelligence
GET        /api/range_intelligence/history
POST       /api/range_intelligence/record_actuals
GET        /api/range_intelligence/scorecard
GET        /api/readiness
GET        /api/readiness/checks
GET        /api/readiness/details
GET        /api/readiness/history
GET        /api/readiness/providers
GET        /api/readiness/report
GET        /api/recommendation-evolution/<recommendation_id>
GET        /api/recommendation/<recommendation_id>/decision
GET        /api/recommendation/<recommendation_id>/explanation
GET        /api/recommendation/<recommendation_id>/review
GET        /api/recommendation/<recommendation_id>/timeline
GET        /api/replay/consensus
GET        /api/replay/decision
GET        /api/replay/frame
GET        /api/replay/narrative
GET        /api/replay/session
GET        /api/replay/thesis
GET        /api/research/clusters
GET        /api/research/findings
GET        /api/research/similarity
GET        /api/research/similarity/<vector_id>
GET        /api/research/status
GET        /api/review/summary
POST       /api/review/trade
GET        /api/review/trades
GET,POST   /api/run
GET        /api/scanner_ideas
GET        /api/session
GET        /api/signal_log
POST       /api/signal_outcome
GET        /api/signal_scorecard
GET        /api/similarity/<sample_id>
GET        /api/status
GET        /api/story
GET        /api/strike_magnets
GET        /api/system/build
GET        /api/system/checks
GET        /api/system/checks/<name>
GET        /api/system/features
GET        /api/system/integrity
GET        /api/system/metrics
GET        /api/system/migrations
GET        /api/system/readiness
GET        /api/system/release
GET        /api/system/version
GET        /api/trade/spx/active-position
GET        /api/trade/spx/audit-log
POST       /api/trade/spx/cancel-order
GET        /api/trade/spx/candles
GET        /api/trade/spx/chain
GET        /api/trade/spx/expirations
POST       /api/trade/spx/flatten
POST       /api/trade/spx/place-change
POST       /api/trade/spx/place-entry
POST       /api/trade/spx/preview-change
POST       /api/trade/spx/preview-entry
POST       /api/trade/spx/project-levels
GET        /api/trade/spx/recommended-contracts
POST       /api/trade/spx/select-contract
GET        /api/v45/status
GET        /api/volume_profile
GET        /assistant
GET        /chart
GET        /dashboard.json
GET        /flow
GET        /health
GET        /scanner
GET        /static/<path:filename>
POST       /tv_signal
```
