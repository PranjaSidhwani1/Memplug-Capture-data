"""Memplug MCP server.

Exposes save_memory, search_memory, get_user_context, list_domains, and
list_sub_domains. The model cannot supply a user id, tenant id, or grant.
"""

import logging

from mcp.server import MCPServer

from memory_mcp.config import load_settings
from memory_mcp.store import MemoryStore

settings = load_settings()
store = MemoryStore(settings.database_url, settings.user_id, settings.granted_domains)

mcp = MCPServer(
    "Memplug",
    instructions=(
        "Memplug stores durable user memories. "
        "A domain is one vector database collection. "
        "A sub-domain is an optional grouping inside a single domain. "
        "Never send a user id, tenant id, or permission scope. "
        "Call get_user_context at the start of a task. "
        "Call search_memory for a narrower lookup. "
        "Call save_memory only when the user asks you to remember a specific fact. "
        "Call list_domains before suggesting a domain. "
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
    result = store.search(query=task, domains=domains)
    if "query" in result:
        result["query"] = task.strip() if isinstance(task, str) else ""
    return result


@mcp.tool()
def list_domains() -> dict:
    """List domains this application may use, with descriptions.

    Call this before suggesting a domain to save_memory. A domain is one
    vector database collection. This tool takes no arguments.
    """
    return store.list_domains()


@mcp.tool()
def list_sub_domains(domain: str) -> dict:
    """List sub-domains inside one domain.

    domain is required. A sub-domain always belongs to that domain, for
    example Travel → Japan Trip. Call list_domains first if you do not know
    a valid domain name.
    """
    return store.list_sub_domains(domain)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if settings.transport == "stdio":
        mcp.run(transport="stdio")
        return
    mcp.run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        json_response=True,
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
