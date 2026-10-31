"""Curated domains. One domain is one vector database collection."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Domain:
    name: str
    description: str


DOMAINS: tuple[Domain, ...] = (
    Domain("User Information", "Stable facts about who the user is."),
    Domain("Preferences", "Enduring likes, dislikes, and working style."),
    Domain("Coding", "Languages, tools, repositories, and engineering habits."),
    Domain("Work", "Job, employer, role, and workplace context."),
    Domain("Projects", "Ongoing projects that are not a single code repository."),
    Domain("Startup Ideas", "Product and company ideas the user wants kept."),
    Domain("Travel", "Trips, destinations, and travel preferences."),
    Domain("Shopping", "Purchases, products, and shopping preferences."),
    Domain("Finance", "Money, budgets, and financial preferences."),
    Domain("Education", "Study, courses, and learning goals."),
    Domain("Health", "Health facts the user has asked to keep."),
    Domain("Relationships", "People and relationships the user has described."),
    Domain("Entertainment", "Media, games, and leisure preferences."),
    Domain("Communication", "How the user wants to be contacted or written to."),
    Domain("Commitments", "Promises, plans, and obligations the user stated."),
    Domain("Uncategorised", "Fallback when a suggested domain cannot be resolved."),
)

_BY_KEY = {domain.name.casefold(): domain for domain in DOMAINS}
UNCATEGORISED = "Uncategorised"


def resolve_domain(value: str | None) -> str | None:
    """Map a model suggestion to a catalogue name. Unknown names resolve to nothing."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    match = _BY_KEY.get(cleaned.casefold())
    if match is None:
        return None
    return match.name


def catalogue() -> list[dict[str, str]]:
    return [{"name": domain.name, "description": domain.description} for domain in DOMAINS]
