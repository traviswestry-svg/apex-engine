import json
import logging

from engine import configuration_governance as cg


def safe_env():
    return {
        "APEX_ENVIRONMENT":"production", "ETRADE_ENV":"production",
        "ETRADE_ENABLE_TRADING":"true", "APEX_CONFIRMATION_GATED_EXECUTION_ENABLED":"true",
        "ETRADE_CONSUMER_KEY":"consumer-key-secret", "ETRADE_CONSUMER_SECRET":"consumer-secret-value",
        "ETRADE_OAUTH_TOKEN":"oauth-token-value", "ETRADE_OAUTH_TOKEN_SECRET":"oauth-secret-value",
        "ETRADE_ACCOUNT_ID_KEY":"account-secret-value", "TV_WEBHOOK_SECRET":"webhook-secret-value",
        "APEX_BUILD_ID":"build-1804", "APEX_RELEASE_NAME":"APEX 18.0.4", "APEX_GIT_COMMIT":"abc123",
        "APEX_GIT_BRANCH":"main", "APEX_DEPLOYED_AT":"2026-07-19T00:00:00Z",
        "APEX_DATABASE_SCHEMA_VERSION":"5", "APEX_INSTANCE_NAME":"apex-web", "APEX_REGION":"oregon",
        "LOG_JSON":"true", "LOG_LEVEL":"INFO", "SOURCE_TIMEOUT_SECONDS":"10",
    }


def test_fully_configured_safe_production_state():
    d=cg.diagnostics(safe_env())
    assert d["execution_safety"]["safe_to_submit"] is True
    assert not d["execution_safety"]["blocking_reasons"]


def test_missing_optional_metadata_warns_not_crashes():
    d=cg.diagnostics({})
    assert d["state"] in {"WARNING","INFO"}
    assert any(i["code"]=="OPTIONAL_METADATA_MISSING" for i in d["issues"])


def test_missing_broker_variable_under_live_submission_is_blocking():
    env=safe_env(); env.pop("ETRADE_OAUTH_TOKEN_SECRET")
    assert cg.diagnostics(env)["state"]=="BLOCKING"


def test_sandbox_live_mismatch_detected():
    env=safe_env(); env["ETRADE_ENV"]="sandbox"
    assert any("sandbox" in x.lower() for x in cg.execution_safety(env)["blocking_reasons"])


def test_invalid_boolean_parsing_detected():
    env=safe_env(); env["ETRADE_ENABLE_TRADING"]="perhaps"
    assert any(i["code"]=="INVALID_VALUE" and i["variable"]=="ETRADE_ENABLE_TRADING" for i in cg.diagnostics(env)["issues"])


def test_invalid_numeric_timeout_detected():
    env=safe_env(); env["SOURCE_TIMEOUT_SECONDS"]="slow"
    assert any(i["code"]=="INVALID_VALUE" and i["variable"]=="SOURCE_TIMEOUT_SECONDS" for i in cg.diagnostics(env)["issues"])


def test_human_confirmation_conflict_detected():
    env=safe_env(); env["APEX_CONFIRMATION_GATED_EXECUTION_ENABLED"]="false"
    assert any("confirmation" in x.lower() for x in cg.execution_safety(env)["blocking_reasons"])


def test_global_kill_switch_is_authoritative():
    env=safe_env(); env["ETRADE_ENABLE_TRADING"]="false"
    s=cg.execution_safety(env)
    assert s["safe_to_submit"] is False and s["broker_mutation_enabled"] is False


def test_secret_values_never_appear_in_diagnostics_or_api_shape():
    env=safe_env(); payload=json.dumps(cg.diagnostics(env))
    for secret in ("consumer-key-secret","consumer-secret-value","oauth-token-value","oauth-secret-value","account-secret-value","webhook-secret-value"):
        assert secret not in payload
    assert "[REDACTED]" in payload


def test_secret_values_never_appear_in_logs(caplog):
    env=safe_env(); env.pop("ETRADE_OAUTH_TOKEN_SECRET")
    with caplog.at_level(logging.INFO): cg.safe_startup_validation(env)
    assert "consumer-key-secret" not in caplog.text
    assert "oauth-token-value" not in caplog.text


def test_deprecated_and_unknown_variables_reported_safely():
    env={"WEBHOOK_SECRET":"legacy-secret-value","APEX_MYSTERY_FLAG":"secret-looking-value"}
    d=cg.diagnostics(env); payload=json.dumps(d)
    assert any(i["code"]=="DEPRECATED_VARIABLE" for i in d["issues"])
    assert any(i["code"]=="UNKNOWN_APEX_VARIABLE" for i in d["issues"])
    assert "legacy-secret-value" not in payload


def test_configuration_endpoints_and_existing_health_and_mission_control_render():
    import app as apex_app
    c=apex_app.app.test_client()
    for route in ("/api/configuration/status","/api/configuration/diagnostics","/api/configuration/categories","/api/configuration/execution-safety","/health","/apex_os"):
        r=c.get(route); assert r.status_code==200, (route,r.status_code,r.data[:200])
    health=c.get('/health').get_json()
    assert isinstance(health,dict) and "ok" in health
    assert b"CONFIGURATION HEALTH" in c.get('/apex_os').data
