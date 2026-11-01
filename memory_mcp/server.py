"""Memplug MCP server.

Exposes save_memory, search_memory, get_user_context, list_domains, and
list_sub_domains. The model cannot supply a user id, tenant id, or grant.
Hosted callers are identified by their Memplug API key. A local stdio
process is bound to MEMPLUG_USER_ID.
"""

from __future__ import annotations

import asyncio
import logging

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from starlette.applications import Starlette

from memory_mcp.config import database_url, load_settings, public_base_url, _granted_domains
from memory_mcp.store import MemoryStore

log = logging.getLogger("memplug.mcp")

_stdio_user = ""
_base_store: MemoryStore | None = None


class ApiKeyVerifier:
    """Map a Memplug API key to the user who owns it. The shared capture key is rejected."""

    async def verify_token(self, token: str) -> AccessToken | None:
        from app.users import user_id_for_api_key

        user_id = await asyncio.to_thread(user_id_for_api_key, token.strip())
        if not user_id:
            return None
        return AccessToken(token=token, client_id=user_id, scopes=[], subject=user_id)


def _resource_url() -> str:
    return public_base_url()


mcp = MCPServer(
    "Memplug",
    token_verifier=ApiKeyVerifier(),
    auth=AuthSettings(
        issuer_url=_resource_url(),
        resource_server_url=_resource_url(),
        validate_token_resource=False,
    ),
    instructions=(
        "Memplug stores durable user memories. "
        "A domain is one vector database collection. "
        "A sub-domain is an optional grouping inside a single domain. "
        "Never send a user id, tenant id, or permission scope. "
        "Call get_user_context at the start of a task. "
        "Call search_memory for a narrower lookup. "
        "Call save_memory only when the user asks you to remember a specific fact. "
        "Call list_domains to see the domains this user already has memories in. "
        "Call list_sub_domains with a domain to see the groupings inside it. "
        "Do not edit or delete memories. The user does that in the Memplug UI."
    ),
)


@mcp.tool()
def save_memory(
    content: str,
    domain: str | None = None,
    sub_domain: str | None = None,
    memory_type: str | None = None,
    source_event_ids: list[str] | None = None,
) -> dict:
    """Save one user-approved fact, preference, decision, or intention.

    Call this when the user says "remember this" or equivalent. Do not wait
    for a checkpoint. A correction in chat also uses this tool. An exact
    duplicate is stored once. A very similar fact in the same domain replaces
    the older one.

    domain is a suggestion only. The server resolves it to the catalogue and
    rejects a domain this application is not granted. sub_domain is an optional
    grouping inside that domain.

    Returns status saved, needs_review, rejected, or retryable_error.
    """
    store = _store()
    if isinstance(store, dict):
        return store
    return store.save(
        content=content,
        domain=domain,
        sub_domain=sub_domain,
        memory_type=memory_type,
        source_event_ids=source_event_ids,
    )


@mcp.tool()
def search_memory(
    query: str,
    domains: list[str] | None = None,
    sub_domain: str | None = None,
    memory_type: str | None = None,
    limit: int | None = None,
) -> dict:
    """Search memories when you need specific facts.

    domains is a metadata filter only. Pass a list of one domain, several
    domains, or null. Null searches every domain this application is allowed
    to see. The server intersects the list with the grant. sub_domain narrows
    to one grouping inside those domains.

    Returns memory id, content, domain, sub_domain, confidence, updated_at,
    and sources. Nothing outside the grant is returned.
    """
    store = _store()
    if isinstance(store, dict):
        return store
    return store.search(
        query=query,
        domains=domains,
        sub_domain=sub_domain,
        memory_type=memory_type,
        limit=limit,
    )


@mcp.tool()
def get_user_context(task: str, domains: list[str] | None = None) -> dict:
    """Load a compact memory bundle for the current task.

    Call this at the start of a task, for example "plan a Japan trip".
    Use search_memory for a narrower lookup. Returns the same memory shape
    as search_memory.

    domains is a metadata filter only. Pass a list of one domain, several
    domains, or null. Null means no domain filter. The server still intersects
    the list with the grant.
    """
    store = _store()
    if isinstance(store, dict):
        return store
    result = store.search(query=task, domains=domains)
    if "query" in result:
        result["query"] = task.strip() if isinstance(task, str) else ""
    return result


@mcp.tool()
def list_domains() -> dict:
    """List domains this user already has memories in, with descriptions.

    A domain with no memories for this user is omitted. This tool takes no
    arguments. save_memory can still use any granted catalogue domain.
    """
    store = _store()
    if isinstance(store, dict):
        return store
    return store.list_domains()


@mcp.tool()
def list_sub_domains(domain: str) -> dict:
    """List sub-domains inside one domain.

    domain is required. A sub-domain always belongs to that domain, for
    example Travel → Japan Trip. Call list_domains first if you do not know
    a valid domain name.
    """
    store = _store()
    if isinstance(store, dict):
        return store
    return store.list_sub_domains(domain)


def _request_user_id() -> str:
    token = get_access_token()
    if token is not None and token.subject:
        return token.subject
    return _stdio_user


def _store() -> MemoryStore | dict:
    user_id = _request_user_id()
    if not user_id:
        return {"status": "rejected", "reason": "not authenticated"}
    url = database_url()
    if not url:
        return {"status": "retryable_error", "reason": "DATABASE_URL is not set"}
    return _database().for_user(user_id)


def _database() -> MemoryStore:
    global _base_store
    if _base_store is None:
        _base_store = MemoryStore(database_url(), "schema", _granted_domains())
    return _base_store


def warmup() -> None:
    """Open the memory tables once. User scope is applied per request."""
    if database_url():
        _database()


def http_app() -> Starlette:
    """ASGI app whose only route is `/`. Mount it at `/mcp` on the capture service."""
    return mcp.streamable_http_app(
        streamable_http_path="/",
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",
    )


def main() -> None:
    global _stdio_user
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = load_settings()
    _stdio_user = settings.user_id
    if settings.transport == "stdio":
        mcp.run(transport="stdio")
        return
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=settings.port,
        json_response=True,
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
