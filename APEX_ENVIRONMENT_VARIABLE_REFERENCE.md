# APEX Environment Variable Reference

Release: APEX 18.0.4 — Configuration Governance  
Runtime: `11.0.2_CONFIGURATION_GOVERNANCE`

This reference is generated from the authoritative registry in `engine/configuration_governance.py`. Secret examples are placeholders only; no deployed values are included.

| Variable | Category | Classification | Required condition | Type | Allowed values | Secret | Description | Example placeholder |
|---|---|---|---|---|---|---|---|---|
| `ACCOUNT_SIZE` | RISK | OPTIONAL | — | number | — | No | APEX runtime setting used by risk components. | `<value>` |
| `APEX_BUILD` | DEPLOYMENT | DEPRECATED | — | string | — | No | Legacy build identity; use APEX_BUILD_ID. | `<value>` |
| `APEX_BUILD_ID` | DEPLOYMENT | OPTIONAL | — | string | — | No | APEX runtime setting used by deployment components. | `<value>` |
| `APEX_CONFIRMATION_GATED_EXECUTION_ENABLED` | EXECUTION | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by execution components. | `false` |
| `APEX_DATABASE_SCHEMA_VERSION` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_DEPLOYED_AT` | DEPLOYMENT | OPTIONAL | — | string | — | No | APEX runtime setting used by deployment components. | `<value>` |
| `APEX_ENVIRONMENT` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_EVIDENCE_DB` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_GIT_BRANCH` | DEPLOYMENT | OPTIONAL | — | string | — | No | APEX runtime setting used by deployment components. | `<value>` |
| `APEX_GIT_COMMIT` | DEPLOYMENT | OPTIONAL | — | string | — | No | APEX runtime setting used by deployment components. | `<value>` |
| `APEX_GOVERNANCE_DB` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_HISTORY_MAX_EXCLUSION_RATE_PCT` | APPLICATION | OPTIONAL | — | number | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_HISTORY_MIN_DATE_DAYS` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_HISTORY_MIN_ELIGIBLE` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_HISTORY_MIN_GRADED` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_INSTANCE_NAME` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_MIN_GRADED_HISTORY` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_MIN_SIMILAR_OUTCOMES` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_OPTIMIZER_MIN_ROWS` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_REGION` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_RELEASE_NAME` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_RESEARCH_DB` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_RESEARCH_MATERIAL_GAP_PCT` | APPLICATION | OPTIONAL | — | number | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_RESEARCH_MIN_COHORT` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_RESEARCH_MIN_COMPARISON_COHORTS` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_SIMILARITY_DB` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `APEX_VERSION` | APPLICATION | DERIVED | — | string | — | No | Derived from the authoritative release manager. | `<value>` |
| `APP_VERSION` | APPLICATION | DERIVED | — | string | — | No | Derived from the authoritative release manager. | `<value>` |
| `ASSISTANT_DEFAULT_RISK_POINTS` | RISK | OPTIONAL | — | integer | — | No | APEX runtime setting used by risk components. | `<value>` |
| `ASSISTANT_SIGNAL_VALID_SECONDS` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `ASSISTANT_STRIKE_STEP_ETF` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `ASSISTANT_STRIKE_STEP_SPX` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `ASSISTANT_TARGET1_R_MULT` | APPLICATION | OPTIONAL | — | number | — | No | APEX runtime setting used by application components. | `<value>` |
| `ASSISTANT_TARGET2_R_MULT` | APPLICATION | OPTIONAL | — | number | — | No | APEX runtime setting used by application components. | `<value>` |
| `ASSISTANT_TICKER` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `BENZINGA_API_KEY` | NEWS | CONDITIONAL | — | string | — | Yes | Benzinga news credential. | `[REDACTED_SECRET]` |
| `BENZINGA_SOURCE` | NEWS | OPTIONAL | — | string | — | No | APEX runtime setting used by news components. | `<value>` |
| `BRACKET_SNAPSHOT_PATH` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `BREAKER_MAX_FAILURES` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `BUILD_ID` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `COMPOSE_IOS_IN_SCANNER` | FEATURE_FLAGS | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by feature flags components. | `<value>` |
| `CONFIDENCE_TIMELINE_MAX_POINTS` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `DARK_POOL_ENDPOINT_ENABLED` | FEATURE_FLAGS | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by feature flags components. | `<value>` |
| `DARK_POOL_LEVELS_ENABLED` | FEATURE_FLAGS | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by feature flags components. | `<value>` |
| `DARK_POOL_LEVELS_LOOKBACK_DAYS` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `DATABASE_URL` | DATABASE | OPTIONAL | — | string | — | Yes | APEX runtime setting used by database components. | `[REDACTED_SECRET]` |
| `DB_PATH` | DATABASE | OPTIONAL | — | string | — | No | APEX runtime setting used by database components. | `<value>` |
| `DIRECTOR_COOLDOWN_EXIT_S` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `DIRECTOR_COOLDOWN_STOP_S` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `DIRECTOR_DB_PATH` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `DIRECTOR_EXIT_CONFIRM_READS` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `DIRECTOR_FLOW_ACC_STRONG` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `DIRECTOR_FLOW_MAX_SAMPLES` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `DIRECTOR_FLOW_MIN_SAMPLES` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `DIRECTOR_FLOW_MIN_WINDOW_S` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `DIRECTOR_FLOW_PERSIST_WINDOWS` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `DIRECTOR_FLOW_VEL_MOVING` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `DIRECTOR_LEVELFAIL_CONFIRM_READS` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `DIRECTOR_MIN_DIRECTIVE_S` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `DIRECTOR_REVERSAL_CONFIRM_READS` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `DISABLE_BACKGROUND_SCANNER` | APPLICATION | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by application components. | `<value>` |
| `DYNAMIC_TICKERS_ENABLED` | FEATURE_FLAGS | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by feature flags components. | `<value>` |
| `ENVIRONMENT` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `ETRADE_ACCOUNT_ID_KEY` | BROKER | CONDITIONAL | — | string | — | Yes | E*TRADE account identifier key. | `[REDACTED_SECRET]` |
| `ETRADE_CONSUMER_KEY` | BROKER | CONDITIONAL | — | string | — | Yes | E*TRADE OAuth consumer key. | `[REDACTED_SECRET]` |
| `ETRADE_CONSUMER_SECRET` | BROKER | CONDITIONAL | — | string | — | Yes | E*TRADE OAuth consumer secret. | `[REDACTED_SECRET]` |
| `ETRADE_ENABLE_TRADING` | BROKER | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by broker components. | `false` |
| `ETRADE_ENV` | BROKER | OPTIONAL | — | string | sandbox, production, live | No | APEX runtime setting used by broker components. | `sandbox` |
| `ETRADE_HTTP_TIMEOUT` | BROKER | OPTIONAL | — | string | — | No | APEX runtime setting used by broker components. | `<value>` |
| `ETRADE_OAUTH_TOKEN` | BROKER | CONDITIONAL | — | string | — | Yes | E*TRADE OAuth access token. | `[REDACTED_SECRET]` |
| `ETRADE_OAUTH_TOKEN_SECRET` | BROKER | CONDITIONAL | — | string | — | Yes | E*TRADE OAuth token secret. | `[REDACTED_SECRET]` |
| `FEATURE_MAX_FRAME_STALENESS_S` | FEATURE_FLAGS | OPTIONAL | — | integer | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FEATURE_WRITE_SESSIONS` | FEATURE_FLAGS | OPTIONAL | — | string | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLASK_ENV` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `FLATFILES_OUT` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `FLOW_CLASSIFIER_ENABLED` | FEATURE_FLAGS | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_CLOCK_SYNC_WINDOW_S` | FEATURE_FLAGS | OPTIONAL | — | integer | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_CLUSTERING_ENABLED` | FEATURE_FLAGS | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_CLUSTER_GAP_S` | FEATURE_FLAGS | OPTIONAL | — | integer | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_CLUSTER_MIN_PRINTS` | FEATURE_FLAGS | OPTIONAL | — | string | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_CLUSTER_SESSION_BOUNDARIES` | FEATURE_FLAGS | OPTIONAL | — | string | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_CLUSTER_STRIKE_BAND_PCT` | FEATURE_FLAGS | OPTIONAL | — | number | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_COMPLEX_RATIO_THRESHOLD` | FEATURE_FLAGS | OPTIONAL | — | string | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_DASHBOARD_TICKERS` | FEATURE_FLAGS | OPTIONAL | — | string | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_DELAYED_PRINT_S` | FEATURE_FLAGS | OPTIONAL | — | integer | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_INSTITUTIONAL_PREMIUM` | FEATURE_FLAGS | OPTIONAL | — | number | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_LABEL_STOP_PCT` | FEATURE_FLAGS | OPTIONAL | — | number | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_LABEL_TARGET_PCT` | FEATURE_FLAGS | OPTIONAL | — | number | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_PAIR_WINDOW_S` | FEATURE_FLAGS | OPTIONAL | — | integer | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_PL_DEFAULT_MULTIPLIER` | FEATURE_FLAGS | OPTIONAL | — | string | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_PL_ENABLED` | FEATURE_FLAGS | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_PL_ILLIQUID_SCORE` | FEATURE_FLAGS | OPTIONAL | — | number | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_PL_MARK_METHOD` | FEATURE_FLAGS | OPTIONAL | — | string | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_PL_RISK_FREE` | FEATURE_FLAGS | OPTIONAL | — | number | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_PL_SAMPLE_SESSIONS` | FEATURE_FLAGS | OPTIONAL | — | string | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_PL_STALE_QUOTE_S` | FEATURE_FLAGS | OPTIONAL | — | integer | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_PL_WIDE_SPREAD_PCT` | FEATURE_FLAGS | OPTIONAL | — | number | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `FLOW_RETAIL_PREMIUM` | FEATURE_FLAGS | OPTIONAL | — | number | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `GAMEPLAN_TICKERS` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `GEX_ENABLED` | FEATURE_FLAGS | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by feature flags components. | `<value>` |
| `GIT_COMMIT` | APPLICATION | DEPRECATED | — | string | — | No | Legacy commit identity; use APEX_GIT_COMMIT. | `<value>` |
| `HEALTH_REFRESH_SECONDS` | HEALTH | OPTIONAL | — | integer | — | No | APEX runtime setting used by health components. | `30` |
| `HEALTH_STALE_AFTER_S` | HEALTH | OPTIONAL | — | integer | — | No | APEX runtime setting used by health components. | `180` |
| `HEATMAP_TICKERS` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `IOS_CACHE_TTL_SECONDS` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `IOS_COMPOSE_SESSIONS` | FEATURE_FLAGS | OPTIONAL | — | string | — | No | APEX runtime setting used by feature flags components. | `<value>` |
| `IOS_FETCH_TIMEOUT_SECONDS` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `LOG_JSON` | LOGGING | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by logging components. | `false` |
| `LOG_LEVEL` | LOGGING | OPTIONAL | — | string | DEBUG, INFO, WARNING, ERROR, CRITICAL | No | APEX runtime setting used by logging components. | `INFO` |
| `MASSIVE_API_KEY` | MARKET_DATA | CONDITIONAL | — | string | — | Yes | Massive market data credential. | `[REDACTED_SECRET]` |
| `MASSIVE_BASE_URL` | MARKET_DATA | OPTIONAL | — | string | — | No | APEX runtime setting used by market data components. | `<value>` |
| `MASSIVE_S3_ACCESS_KEY` | MARKET_DATA | OPTIONAL | — | string | — | Yes | APEX runtime setting used by market data components. | `[REDACTED_SECRET]` |
| `MASSIVE_S3_SECRET_KEY` | MARKET_DATA | OPTIONAL | — | string | — | Yes | APEX runtime setting used by market data components. | `[REDACTED_SECRET]` |
| `MAX_DYNAMIC_TICKERS` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `MAX_RISK_PER_TRADE` | RISK | OPTIONAL | — | number | — | No | APEX runtime setting used by risk components. | `<value>` |
| `MIN_ACCUMULATION_SCORE` | APPLICATION | OPTIONAL | — | number | — | No | APEX runtime setting used by application components. | `<value>` |
| `MIN_ALERT_SCORE` | APPLICATION | OPTIONAL | — | number | — | No | APEX runtime setting used by application components. | `<value>` |
| `MIN_FINAL_SCORE` | APPLICATION | OPTIONAL | — | number | — | No | APEX runtime setting used by application components. | `<value>` |
| `ORDER_FLOW_ENABLED` | FEATURE_FLAGS | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by feature flags components. | `<value>` |
| `POLYGON_API_KEY` | MARKET_DATA | CONDITIONAL | — | string | — | Yes | Polygon/Massive market data credential. | `[REDACTED_SECRET]` |
| `POLYGON_OPTIONS_UNDERLYING` | MARKET_DATA | OPTIONAL | — | string | — | No | APEX runtime setting used by market data components. | `<value>` |
| `POLYGON_STRIKE_WINDOW_PCT` | MARKET_DATA | OPTIONAL | — | number | — | No | APEX runtime setting used by market data components. | `<value>` |
| `PORT` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `POSITION_MONITOR_ENABLED` | FEATURE_FLAGS | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by feature flags components. | `<value>` |
| `PREBREAKOUT_DISTANCE_PCT` | APPLICATION | OPTIONAL | — | number | — | No | APEX runtime setting used by application components. | `<value>` |
| `PREMIUM_GRADE_DEADBAND_PTS` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `PREMIUM_NO_PREMIUM_BID` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `PREMIUM_SETTLE_HOUR_ET` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `QUANTDATA_API_KEY` | MARKET_DATA | CONDITIONAL | — | string | — | Yes | QuantData order-flow credential. | `[REDACTED_SECRET]` |
| `QUANTDATA_BASE_URL` | MARKET_DATA | OPTIONAL | — | string | — | No | APEX runtime setting used by market data components. | `<value>` |
| `QUANTDATA_NEWS_ENABLED` | MARKET_DATA | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by market data components. | `<value>` |
| `RANGE_DB_PATH` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `RECOMMENDATION_LEDGER_DB_PATH` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `RENDER_DEPLOY_CREATED_AT` | DEPLOYMENT | OPTIONAL | — | string | — | No | APEX runtime setting used by deployment components. | `<value>` |
| `RENDER_DEPLOY_ID` | DEPLOYMENT | OPTIONAL | — | string | — | No | APEX runtime setting used by deployment components. | `<value>` |
| `RENDER_GIT_BRANCH` | DEPLOYMENT | OPTIONAL | — | string | — | No | APEX runtime setting used by deployment components. | `<value>` |
| `RENDER_GIT_COMMIT` | DEPLOYMENT | OPTIONAL | — | string | — | No | APEX runtime setting used by deployment components. | `<value>` |
| `RENDER_INSTANCE_ID` | DEPLOYMENT | OPTIONAL | — | string | — | No | APEX runtime setting used by deployment components. | `<value>` |
| `RENDER_REGION` | DEPLOYMENT | OPTIONAL | — | string | — | No | APEX runtime setting used by deployment components. | `<value>` |
| `RENDER_SERVICE_NAME` | DEPLOYMENT | OPTIONAL | — | string | — | No | APEX runtime setting used by deployment components. | `<value>` |
| `REPLAY_MAX_FRAMES` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `REQUEST_TIMEOUT` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `REVIEW_DB_PATH` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `RUN_SCANNER_ON_IMPORT` | APPLICATION | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by application components. | `false` |
| `SAMPLE_FLOW_PL_IN_SCANNER` | FEATURE_FLAGS | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by feature flags components. | `<value>` |
| `SCANNER_HEARTBEAT_SECONDS` | SCANNER | OPTIONAL | — | integer | — | No | APEX runtime setting used by scanner components. | `60` |
| `SCAN_INTERVAL_SECONDS` | SCANNER | OPTIONAL | — | integer | — | No | APEX runtime setting used by scanner components. | `30` |
| `SCAN_WORKERS` | SCANNER | OPTIONAL | — | integer | — | No | APEX runtime setting used by scanner components. | `<value>` |
| `SEND_TELEGRAM` | APPLICATION | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by application components. | `<value>` |
| `SIGNAL_EVAL_DB_PATH` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `SIGNAL_TTL_SECONDS` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `SOURCE_TIMEOUT_SECONDS` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `10` |
| `SOURCE_VERSION` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `SPINE_DB_PATH` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `SPINE_ENABLED` | FEATURE_FLAGS | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by feature flags components. | `<value>` |
| `SPINE_LOG_WHEN_CLOSED` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `SPINE_MAX_HOLD_MIN` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `SPINE_MIN_STAGE` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `STATIC_TICKERS_EXTRA` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `STORY_ENABLED` | FEATURE_FLAGS | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by feature flags components. | `<value>` |
| `TELEGRAM_BOT_TOKEN` | MESSAGING | CONDITIONAL | — | string | — | Yes | Telegram bot credential. | `[REDACTED_SECRET]` |
| `TELEGRAM_CHAT_ID` | MESSAGING | CONDITIONAL | — | string | — | Yes | Telegram destination identifier. | `[REDACTED_SECRET]` |
| `TRACKING_ENABLED` | FEATURE_FLAGS | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by feature flags components. | `<value>` |
| `TRACK_MAX_HOLD_DAYS` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `TRACK_MIN_SAMPLE` | APPLICATION | OPTIONAL | — | integer | — | No | APEX runtime setting used by application components. | `<value>` |
| `TRADE_AUDIT_DIR` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `TRADE_NO_NEW_AFTER_ET` | APPLICATION | OPTIONAL | — | string | — | No | APEX runtime setting used by application components. | `<value>` |
| `TRADINGVIEW_SECRET` | EXECUTION | DEPRECATED | — | string | — | Yes | Legacy TradingView secret; use TV_WEBHOOK_SECRET. | `[REDACTED_SECRET]` |
| `TV_WEBHOOK_SECRET` | APPLICATION | CONDITIONAL | — | string | — | Yes | TradingView webhook authentication secret. | `[REDACTED_SECRET]` |
| `WEBHOOK_SECRET` | APPLICATION | DEPRECATED | — | string | — | Yes | Legacy webhook secret; use TV_WEBHOOK_SECRET. | `[REDACTED_SECRET]` |
| `WRITE_FEATURES_IN_SCANNER` | FEATURE_FLAGS | OPTIONAL | — | boolean | true, false | No | APEX runtime setting used by feature flags components. | `<value>` |
