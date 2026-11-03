# Model configuration

The current adapter uses Meta Model API's OpenAI-compatible endpoint. Defaults are `https://api.meta.ai/v1` and `muse-spark-1.3`; the Meta account controls which model IDs are available. The API key is read from `COCONERD_MODEL_API_KEY` (or the compatibility names `MODEL_API_KEY`, `COCONERD_META_API_KEY`, and `META_API_KEY`). The key is never returned by the admin API or written to logs.

Configuration precedence:

1. Enabled guild model configuration written by an administrator.
2. Global model configuration written by an administrator.
3. `COCONERD_META_MODEL_NAME`, `LLM_TEMPERATURE`, and `LLM_MAX_TOKENS`.

Bot callers cannot change a model. The admin API accepts provider `meta`, model ID, temperature, and max tokens. Unsupported providers fail explicitly.

For local tests, set `COCONERD_MOCK_LLM=true` and `COCONERD_APP_ENV=development` or `test`. The mock is unavailable in production mode. To verify a live call, set the key and `COCONERD_MOCK_LLM=false`; the automated suite intentionally does not make paid external requests.

If the provider returns authentication, rate-limit, timeout, connection/status, or invalid structured output errors, the worker records the error class and retries the durable job up to its configured bound. No AI failure is reported as successful processing.
