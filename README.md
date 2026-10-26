# Agent cost controls (Advent of Agents, Day 28)

**The question:** how do I track which agent is consuming the most tokens, create real-time billing alerts,
and enforce project / agent / Cloud Run instance spend caps automatically?

This repo is the code behind the Day 28 video. It runs real ADK agents on Gemini Enterprise Agent Platform,
sends their telemetry to Cloud Trace, Cloud Logging and Cloud Monitoring, and measures **cost next to quality**:
every answer the LLM judge grades gets the tokens, cache hits, calls and seconds it took.

The unit is **cost per successful task** (price the task, not the token): failed tasks still cost money,
so they count against the variant that produced them. Tokens are what you can measure on every call;
`prices.json` turns them into dollars, because a token's price depends on the model and on whether it was cached.

New to how agents are billed? Start with [COSTS.md](COSTS.md): my notes, as a developer, on what you actually pay
for when you build agents, run managed agents, or buy seats for tools like Gemini Enterprise and Google Antigravity.

## What's inside

| File | What it does |
| :-- | :-- |
| `cost_lab/db.py` | An in-memory SQLite sales mart for a fictional cafe chain, Cymbal Coffee (stores, products, about 5,300 sales rows, refunds, an internal test kitchen that must be excluded). Same data every run. |
| `cost_lab/semantic_layer.py` | The analyst agent's semantic layer (about 8.5k tokens): schema, glossary ("revenue" means net revenue, fiscal Q3 is August to October), metric SQL, playbook. |
| `cost_lab/agents.py` | `make_sql_agent(layout, thinking, glossary, model)`, plus `research_agent` (a runaway loop) and `router_agent`. Every model call carries billing labels. |
| `cost_lab/meter.py` | `TaskMeter`: model calls, input / cached / thinking / output tokens and tool payload size for one task, from `usage_metadata`. |
| `cost_lab/evals.py` | 8 analyst questions (reference answers computed from the data), an LLM judge, and the summary table (tokens and dollars per successful task). |
| `prices.json` | List prices per 1M tokens from the official pricing page, dated. Update it before you trust a dollar figure. |
| `run_lab.py` | `loop`, `router`, `experiments`, `all`, or `summary` (re-price saved results, no model calls). |
| `burn_rate.py` + `sql/burn_rate_by_agent.sql` | Which agent is consuming the most tokens, in BigQuery, from the trace spans. |
| `infra/alert_policy_*.json` | Cloud Monitoring alert policies (PromQL): token burn per agent, LLM calls per invocation. |
| `deploy/sql_analyst/` | The analyst agent as a Cloud Run service, for the instance caps. |
| `tests/` | Offline tests (no model calls): `pytest -q`. |

## Run it (about 5 minutes)

```bash
git clone https://github.com/danielazamorah/agent-cost-controls.git && cd agent-cost-controls
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest
pytest -q                                   # offline checks, no Google Cloud calls

gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=<your-project> GOOGLE_CLOUD_LOCATION=global GOOGLE_GENAI_USE_VERTEXAI=TRUE   # Agent Platform (the SDK flag keeps its old name)
export MODEL=gemini-3.8-flash JUDGE_MODEL=gemini-3.8-flash ADK_EXPERIMENTAL_TELEMETRY=true

python run_lab.py loop                      # 40-call safety net vs RunConfig(max_llm_calls=8)
python run_lab.py experiments baseline static_first   # two variants, about 2 minutes
python run_lab.py experiments               # all variants (writes out/experiments_table.md)
```

## The five controls in this repo

1. **Meter every task.** `TaskMeter` reads `usage_metadata` on every model response (an ADK `after_model_callback`).
   In production, the same numbers are on the `generate_content` spans in Cloud Trace (`gen_ai.agent.name`,
   `gen_ai.usage.*`), and ADK exports per-agent metrics to Cloud Monitoring.
2. **Find the hungriest agent.** `sql/burn_rate_by_agent.sql` over the Cloud Trace data linked to BigQuery
   (Observability Analytics): calls per session, tokens per session and cache hit rate per agent.
3. **Alarm in minutes, attribute in hours.** A PromQL alert on tokens per agent over 5 minutes
   (`infra/alert_policy_1.json`), plus `labels={"agent": ...}` on every model call so Cloud Billing reports,
   budgets and spend cap budgets can be scoped per agent and project.
4. **Bound the agent.** `RunConfig(max_llm_calls=8)` (the ADK default is 500) raises `LlmCallsLimitExceededError`;
   `thinking_level` keeps simple steps from overthinking.
5. **Cap around the agent.** Cloud Run `--max-instances`, `--concurrency`, `--timeout`; a gateway token quota
   (for example Apigee's LLMTokenQuota policy) for hard per-caller limits; a Cloud Billing spend cap budget to pause
   Agent Platform or Cloud Run usage in a project when estimated spend passes the cap (not instantaneous).

## The experiment: one change at a time

All variants run the same 8 questions in one analyst chat session, with ADK's context cache turned on
(`App(context_cache_config=ContextCacheConfig(...))`). Each variant changes one thing against the baseline:

| Variant | The one change |
| :-- | :-- |
| `baseline` | A per-request header (time, request ID) on top of the instruction, the semantic layer below it, `thinking_level=HIGH` |
| `thinking_medium`, `thinking_low` | `thinking_level` MEDIUM or LOW |
| `static_first` | The semantic layer moves to ADK's `static_instruction` (sent first and identical on every call); the header moves after it |
| `no_glossary` | Drop the business definitions from the prompt to save tokens |
| `best` | `static_first` + `thinking_low` |
| `model_argon` | The same agent on Gemini 4 Argon instead of Gemini 3.8 Flash |
| `model_claude` | The same agent on Claude Sonnet 5.5 (a partner model from Model Garden) |
| `claude_static_first` | Claude Sonnet 5.5 + `static_first` (ad hoc: `claude_static_first=model:claude-sonnet-5-5,layout:static_first`) |

Results from our run (`out/experiments_table.md`):

| variant | change | judge | tokens / successful task | of which cached | thinking | calls / task | sec / task | $ / successful task | cost index |
|---|---|---|---|---|---|---|---|---|---|
| baseline | (baseline) | 8/8 | 30,034 | 0 (0.0%) | 567 | 2.38 | 9.4 | 0.02511 | 100 |
| thinking_medium | thinking=medium | 8/8 | 29,169 | 0 (0.0%) | 362 | 2.5 | 7.6 | 0.02382 | 95 |
| thinking_low | thinking=low | 8/8 | 20,908 | 0 (0.0%) | 195 | 2.0 | 5.6 | 0.01689 | 67 |
| static_first | layout=static_first | 8/8 | 25,181 | 17,096 (70.2%) | 612 | 2.0 | 8.4 | 0.00981 | 39 |
| no_glossary | glossary=False | 8/8 | 72,134 | 0 (0.0%) | 2,755 | 4.75 | 29.7 | 0.06392 | 255 |
| best | layout=static_first, thinking=low | 8/8 | 19,530 | 16,402 (84.9%) | 0 | 2.0 | 7.1 | 0.00419 | 17 |
| model_argon | model=gemini-4-argon | 8/8 | 21,828 | 0 (0.0%) | 237 | 2.0 | 14.3 | 0.04733 | 188 |
| model_claude | model=claude-sonnet-5-5 | 8/8 | 27,894 | 0 (0.0%) | 0 | 2.0 | 3.4 | 0.07225 | 288 |
| claude_static_first | model=claude-sonnet-5-5, layout=static_first | 8/8 | 28,413 | 15,085 (53.8%) | 11 | 2.0 | 3.4 | 0.03897 | 155 |

(Gemini 3.8 Flash unless the change says otherwise, global endpoint, 2026-10-25. Dollars use the list prices in
`prices.json` on that date; the cost index is dollars relative to the baseline (= 100). Your numbers will differ;
the shape is the point.)

Three things this table taught me:

- **Tokens and dollars don't move together.** `best` uses 35% fewer tokens than the baseline but costs about 83% less,
  because cached input tokens are billed at a fraction of the input price.
- **A cheaper prompt can make a pricier task.** `no_glossary` sends a much smaller prompt, still passes 8/8, and costs
  about 2.5 times as much per task: the agent goes digging through the data for what the glossary used to tell it.
- **Fewer tokens isn't cheaper if each token costs more.** Gemini 4 Argon needed fewer steps (27% fewer tokens), but
  a flagship token costs more, so the same task cost almost twice as much, and took longer. For this simple SQL
  agent, Flash was the better deal; on harder tasks a stronger model can win by finishing in fewer steps.
  You only know by pricing the task.
- **A partner model is one line away, and needs the same care.** Claude Sonnet 5.5 (from Model Garden, same agent,
  same eval) also scored 8/8 and was the fastest (3.4 s per question), but the first run cost about 2.9 times the
  baseline per task: with ADK's context cache on and a per-request header at the top of the prompt, Claude wrote its
  prompt cache on every call (Anthropic bills cache writes above the input price) and never read it. Putting the
  static part first almost halved it (cost index 288 to 155).

Why the layout matters: caching only works on an identical prefix. A header that changes on every request
(a timestamp, a request ID, a user name) at the top of the instruction makes every request start differently,
so nothing can be reused. Implicit caching on Gemini Enterprise Agent Platform is automatic but best-effort, and on
Gemini 3.8 Flash and 3.1 Pro Preview it needs a shared prefix of at least 6,144 tokens; ADK's context cache
(explicit caching) gives you predictable hits once the prefix is stable. See the
[context caching overview](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/context-cache/context-cache-overview).

## Price the task: tokens into dollars

`prices.json` holds list prices per 1M tokens from the official
[pricing page](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing), with the date I copied them. The summary
prices each task with its own model's prices: uncached input, cached input (discounted) and output, where
**thinking tokens are billed as output**. Prices change (promotions, introductory pricing), so update the file and run:

```bash
python run_lab.py summary   # re-prices out/experiments_rows.json, no model calls
```

## What about other models?

The model is just another knob: `make_sql_agent(model="gemini-4-argon")`. Agent Platform also serves partner and open
models per token on the same Google Cloud bill (Anthropic's Claude, OpenAI's gpt-oss, Llama, Mistral and more; see
Model Garden). `make_sql_agent` routes `claude-*` model names through ADK's `Claude` class (enable the model in
Model Garden first); other providers work through ADK's LiteLLM integration. Claude ran in a different project
than the traces: set `GOOGLE_CLOUD_PROJECT` to the project where the model is enabled and `TELEMETRY_PROJECT` to the
one that holds your traces (`GOOGLE_CLOUD_LOCATION=global`). Two cautions when you compare across
providers: each one counts tokens with its own tokenizer, and prices differ per model, so compare **dollars per
successful task**, never raw tokens.

## Clean up

```bash
gcloud run services delete day28-sql-analyst --region=us-central1
gcloud alpha monitoring policies list --filter='displayName:"Day 28"' --format='value(name)' | xargs -n1 gcloud alpha monitoring policies delete
```

## License

Apache 2.0. This is a demo, not an official Google product.
