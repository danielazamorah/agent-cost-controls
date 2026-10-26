-- burn_rate_by_agent.sql
-- Which agent is consuming the most tokens? One row per agent and model, last 24 hours.
-- Source: the Cloud Trace _Trace bucket linked to BigQuery (dataset agent_spans, zero copy, Observability Analytics).
-- ADK writes token counts on the `generate_content <model>` spans, next to gen_ai.agent.name.
-- ADK's output_tokens already include the reasoning (thinking) tokens.
-- adk.experimental.context_cache.hit is true when the call reused ADK's context cache.
SELECT
  JSON_VALUE(attributes, '$."gen_ai.agent.name"') AS agent_name,
  JSON_VALUE(attributes, '$."gen_ai.request.model"') AS model,
  COUNT(DISTINCT JSON_VALUE(attributes, '$."gen_ai.conversation.id"')) AS sessions,
  COUNT(*) AS llm_calls,
  ROUND(COUNT(*) / COUNT(DISTINCT JSON_VALUE(attributes, '$."gen_ai.conversation.id"')), 1) AS llm_calls_per_session,
  SUM(SAFE_CAST(JSON_VALUE(attributes, '$."gen_ai.usage.input_tokens"') AS INT64)) AS input_tokens,
  SUM(SAFE_CAST(JSON_VALUE(attributes, '$."gen_ai.usage.output_tokens"') AS INT64)) AS output_tokens,
  ROUND(100 * SAFE_DIVIDE(
    SUM(SAFE_CAST(JSON_VALUE(attributes, '$."gen_ai.usage.reasoning.output_tokens"') AS INT64)),
    SUM(SAFE_CAST(JSON_VALUE(attributes, '$."gen_ai.usage.output_tokens"') AS INT64))), 0) AS thinking_pct,
  ROUND(100 * COUNTIF(JSON_VALUE(attributes, '$."adk.experimental.context_cache.hit"') = 'true') / COUNT(*), 0) AS cache_hit_pct,
  ROUND(SUM(SAFE_CAST(JSON_VALUE(attributes, '$."gen_ai.usage.input_tokens"') AS INT64))
        / COUNT(DISTINCT JSON_VALUE(attributes, '$."gen_ai.conversation.id"'))) AS input_tokens_per_session
FROM `YOUR_PROJECT.agent_spans._AllSpans`
WHERE start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND name LIKE 'generate_content %'
GROUP BY agent_name, model
ORDER BY input_tokens + output_tokens DESC;
