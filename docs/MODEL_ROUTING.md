# VYOM Model Routing

## Principle

Use the cheapest reliable model capable of completing the task. Escalate only when capability, verification, failure history, criticality, or quality requires it.

## Registry

Models live in `config/models.yaml`; model IDs are not scattered through runtime source. Each entry describes provider, capabilities, quality/speed/cost/context tiers, tool/vision/streaming support, privacy policy, and priority.

External model IDs are supplied with environment variables. A provider is available only when:

1. its model entry is enabled;
2. a non-empty model ID is configured;
3. required credentials are present;
4. the provider health circuit is not open.

`local-rules` is an honest, limited deterministic provider for known Phase 4 commands and tests. It is not advertised as a general language model.

## Selection inputs

- domain and complexity
- required capabilities
- latency and quality priority
- cost tier and remaining budget
- privacy policy
- provider availability and recent failures
- historical success and verification score for similar tasks

The router filters incapable/unavailable models, then scores remaining candidates. A routing decision contains a primary model, bounded fallback list, optional verifier, concise selection reason, and estimated cost tier.

## Fallback

Timeouts, rate limits, provider failures, malformed structured output, and failed verification may advance to the next compatible fallback. Every fallback is an event. Retries and fallbacks are bounded; the runtime never loops indefinitely or reports success after all attempts fail.

## Adding a provider/model

1. Implement the common provider interface or reuse the OpenAI-compatible adapter.
2. Add a model entry to `config/models.yaml` using an environment-supplied model ID.
3. Declare capabilities and policy metadata conservatively.
4. Add mocked routing/fallback tests.
5. Configure credentials only in the Brain environment.

