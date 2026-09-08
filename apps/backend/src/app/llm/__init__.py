"""LLM provider clients (build-plan #8 Part 2).

Import boundary: only `app.services.llm_gateway` may import from this package.
Every other module goes through the gateway, which builds the sanitized payload
via `app.services.privacy_gateway` first. Nothing here touches a `Transaction`,
the database, or an unsanitized string.
"""
