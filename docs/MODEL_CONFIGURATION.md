# Model configuration

The current adapter uses Meta Model API's OpenAI-compatible endpoint. Defaults are `https://api.meta.ai/v1` and `muse-spark-1.3`; the Meta account controls which model IDs are available. The API key is read from `COCONERD_MODEL_API_KEY` (or the compatibility names `MODEL_API_KEY`, `COCONERD_META_API_KEY`, and `META_API_KEY`). The key is never returned by the admin API or written to logs.

Use one local `.env` at the root of the checkout you run. `Settings` resolves `.env` against the process working directory; it does not search other worktrees or load `.env.example`. The example is a tracked template and must not contain real credentials. Process environment variables take precedence over dotenv values, including an exported empty value. Run API and worker from the same checkout and restart them after configuration changes. A provider-only Meta evaluation needs the model key, not bot/admin keys.

Topic classification uses Meta JSON-Schema structured output and `topic-policy-v4` reference validation. The local index searches old eligible topics, combines at most 30 matches with 30 recent topics, and ranks at most five compact cards. This adds no model provider or paid subagent. Blank text becomes local `irrelevant`; acknowledgements without an explicit anchor can become local `defer`, both with zero tokens. Assignments below confidence 0.7 abstain; this is not calibrated accuracy. Structured memory replacements require a known previous fact and a verbatim target quote. Other passes use one Meta call. A message can have at most one evidence-triggered reassessment and two durable call reservations across retries.

The request keeps a stable prompt prefix and versioned cache key (`coconerd-topic-classification-v4-memory-v1`) so Meta can apply prompt-prefix caching. Counts are recorded only when returned; cache hits or lower cost are not guaranteed. There is no cross-message decision cache. Context is capped at six messages/1,600 characters and five topic cards. The original target text keeps the configured ingestion length limit.

`COCONERD_LLM_REASONING_EFFORT` defaults to `low` and accepts `minimal`, `low`, `medium`, `high`, `xhigh`, or `max`. `COCONERD_LLM_MAX_TOKENS` defaults to `2048`; `LLM_MAX_TOKENS` remains an alias. Reasoning tokens count toward the output limit and are stored when Meta reports them. A response ending with `finish_reason=length` is recorded as a distinct truncation failure, not a valid topic decision. Check measured output usage before changing the limit or effort: lower effort does not by itself prove lower cost or equal accuracy.

Configuration precedence:

1. Enabled guild model configuration written by an administrator.
2. Global model configuration written by an administrator.
3. `COCONERD_META_MODEL_NAME`, `LLM_TEMPERATURE`, and `COCONERD_LLM_MAX_TOKENS`.

Bot callers cannot change a model. The admin API accepts provider `meta`, model ID, temperature, and max tokens. Reasoning effort is set globally through the environment and is not overridden by the admin API. Unsupported providers fail explicitly.

For local tests, set `COCONERD_MOCK_LLM=true` and `COCONERD_APP_ENV=development` or `test`. The mock is unavailable in production mode. To verify a live call, set the key and `COCONERD_MOCK_LLM=false`; the automated suite intentionally does not make paid external requests.

If the provider returns authentication, rate-limit, timeout, connection/status, or invalid structured output errors, the worker records the error class and retries within both the configured attempt bound and the two-call lifetime bound. SDK retries are disabled. Reservation commits before provider construction, so failed setup/crashes may consume budget without a billed request. The two-call limit, one reassessment, ten-minute window and context/card limits are code policy constants, not additional environment variables.

Output truncation is an exception to automatic retries: `MetaOutputTruncatedError` moves the job to `DEAD` after the first failed attempt, preserving the original message and error type. Repeating the same output budget can waste paid tokens. Review the input, reasoning effort, and token limit before any operator-managed retry; there is currently no public job-retry endpoint. The worker never increases the budget automatically.
