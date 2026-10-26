# How agents are billed on Google Cloud (a developer's notes)

I'm a developer, not a cost expert. Whenever someone asked me "what will this agent cost?", my honest answer was
"it depends", so for Day 28 I went and read the official docs. These are my notes, checked on **2026-10-25**.
Plans and prices change, so follow the links before you quote anything.

## The short version

Whatever the wrapper is (an API call, a managed agent, a seat, a credit), usage underneath is priced the same way:
**tokens times the price of the model that produced them**, plus the compute where the agent runs. Seats add a flat
fee on top, and in exchange they prepay a pool of that usage.
That's why the Day 28 code measures tokens on every model call and then prices the task with `prices.json`.

| How you use agents | What you pay for | Where the meter is |
| :-- | :-- | :-- |
| Agents you build and deploy (ADK on Agent Runtime or Cloud Run) | Model tokens + hosting compute | Per token, per vCPU and GiB second |
| Managed agents (the Antigravity agent in the Managed Agents API) | Model tokens | Per token (sandbox compute not billed in preview) |
| Seats for people (Gemini Enterprise, which is also how teams get Antigravity) | A seat, which brings pooled quota and credits | Usage draws the pool down; after that it stops or goes pay-as-you-go |
| Antigravity on a personal Google AI plan | A plan with rate limits | Rate limits follow the work the agent does; AI credits for overages |
| Partner and open models (Claude, gpt-oss, Llama, Mistral and more) | Model tokens | Per token, per model, on the same Google Cloud bill |

## 1. Agents you build and deploy

- **Model calls, per token.** Input, cached input (billed at a fraction of the input price) and output.
  Thinking (reasoning) tokens are billed as output. You're only charged for requests that return a 200.
  Besides the Standard tier there are Priority, Flex and Batch tiers, Provisioned Throughput for reserved capacity,
  and Flexible Savings Plans for committed spend.
  [Generative AI pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing)
- **Hosting on Agent Runtime.** Agent Compute (vCPU-hours) and Agent Memory (GiB-hours), rounded to the second.
  Idle time waiting for the next prompt between turns isn't billed. Sessions and Memory Bank are billed per read and
  write operation, plus storage. There's a monthly free tier.
  [Agent Platform pricing](https://cloud.google.com/gemini-enterprise-agent-platform/pricing)
- **Hosting on Cloud Run.** Instance CPU and memory time and requests.
  [Cloud Run pricing](https://cloud.google.com/run/pricing)

## 2. Managed agents

- The Antigravity agent in the Managed Agents API is pay-as-you-go on tokens. The docs say complex agentic workflows
  with many tool calls can use 3 to 5 million tokens in a single interaction, and that 50 to 70% of input tokens are
  typically cached. Environment compute (CPU, memory, sandbox execution) isn't billed during the preview.
  [Antigravity agent](https://ai.google.dev/gemini-api/docs/antigravity-agent)

## 3. Seats: Gemini Enterprise, and Antigravity for teams

- **Standard and Plus editions are per seat.** Each seat adds to quotas that are pooled per edition, project and
  location, including a monthly credit per seat for the AI developer tools (the Antigravity app and CLI,
  Antigravity for IDEs, Android Studio), enforced as a shared weekly pool.
- **When the pool runs out, usage stops**, unless an admin turns on pay-as-you-go overages. Overages for Gemini models
  are billed at Agent Platform prices (Claude models at Claude pricing).
- **The Pay-as-you-go edition** has no seat fee and no feature quotas: you pay for what you use.
- **The spend limit is a Cloud Billing spend cap.** Overages and pay-as-you-go usage bill under the Agent Platform API
  (`aiplatform.googleapis.com`, still listed as "Vertex AI" in Cloud Billing), and the project's monthly spend limit is a Cloud Billing budget with a spend cap on
  that service, the same kind of spend cap Day 28 uses for agents. It covers the Gemini Enterprise app,
  Agent Platform and AI coding tools such as Antigravity. Stopping can take a few minutes.
- Admins can see third-party model tokens per user and per model in Cloud Logging.

Links: [Quotas and overages](https://docs.cloud.google.com/gemini/enterprise/docs/quotas-and-overages),
[Configure overages](https://docs.cloud.google.com/gemini/enterprise/docs/configure-overages),
[AI developer tools](https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools-overview),
[Track third-party model token usage](https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools-track-token-usage),
[Antigravity pricing](https://antigravity.google/pricing)

## 4. Antigravity on a personal plan

- Individual plans (no plan, Google AI Pro, Google AI Ultra) come with rate limits, not a token bill. In the docs'
  words, the limits "correlate with the amount of work done by the agent": straightforward tasks get you more prompts,
  complex ones use more quota. Pro and Ultra refresh every five hours up to a weekly limit; without a plan, weekly.
- Past the limit, Pro and Ultra users can spend AI credits, "consumed at standard Gemini Enterprise consumption
  pricing", if they set AI Credit Overages to Always.
- You also pick the model and a thinking level (Low, Medium, High), the same two knobs the Day 28 experiment tests.

Links: [Plans](https://antigravity.google/docs/plans), [Models](https://antigravity.google/docs/models)

## 5. Partner and open models

- Agent Platform serves partner and open models per token, per model, on the same Google Cloud bill: Anthropic's Claude,
  OpenAI's gpt-oss, Meta's Llama, Mistral, Qwen, DeepSeek and others.
  [Model Garden](https://cloud.google.com/model-garden) and the partner sections of the
  [pricing page](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing)
- OpenAI's newest GPT models are in private preview for select customers
  ([announcement](https://cloud.google.com/blog/products/ai-machine-learning/google-cloud-brings-openai-models-to-customers)).
- Compare models by **dollars per successful task**, never raw tokens: every provider counts tokens with its own
  tokenizer, and prices differ per model.
- Caching rules differ per provider. Anthropic bills prompt-cache writes above the input price (5-minute writes at
  1.25x) and reads at a tenth of it. In the Day 28 lab, Claude Sonnet 5.5 with a per-request header at the top of the
  prompt wrote its cache on every call and never read it; with the static part first, its cost per task almost halved.

## Where the Day 28 controls fit

| Control | Agents you build | Managed agents | Gemini Enterprise and Antigravity seats |
| :-- | :-- | :-- | :-- |
| Meter tokens per task (`TaskMeter`, trace spans) | Yes | Yes (usage metadata) | Admin metrics and logs |
| `max_llm_calls` per run | Yes (ADK `RunConfig`) | n/a | n/a |
| Billing labels per agent | Yes | n/a | n/a |
| Alert on tokens per agent (Cloud Monitoring) | Yes | n/a | n/a |
| Spend cap budget (Cloud Billing) | Yes (Agent Platform, Gemini API, Cloud Run) | Yes | Yes, for overages and pay-as-you-go |

What I still want to learn: how FinOps teams forecast this, and how committed-use discounts and reserved capacity
change the math. If you know, tell me!
