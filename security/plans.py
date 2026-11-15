"""Plans are entitlement sets on one build (section 3.2). A tenant can hold one module without the others."""

from dataclasses import dataclass, field

from core.entitlements import (
    ALERTS,
    API_KEYS,
    ASK,
    AUDIT,
    BACKTEST,
    DATA_DEMO,
    DATA_LICENSED,
    DATA_PRIVATE,
    DATA_PUBLIC,
    DATALAB,
    DATALAB_IMPORT,
    DOCUMENTS,
    EXPORT,
    GRAPH,
    GRAPH_EDIT,
    MARKETS,
    MEMBERS,
    PORTFOLIO,
    PORTFOLIO_SCENARIOS,
    REPORTS,
    SCREENER,
    SIMULATE,
    THESES,
    UNLIMITED,
    WORKSPACES,
)


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    audience: str
    entitlements: frozenset[str]
    limits: dict[str, int] = field(default_factory=dict)
    highlights: tuple[str, ...] = ()


_COMMUNITY = frozenset({MARKETS, DOCUMENTS, ASK, PORTFOLIO, GRAPH, DATALAB, DATA_PUBLIC, DATA_DEMO, WORKSPACES})
_PRO = _COMMUNITY | {ALERTS, SCREENER, REPORTS, THESES, PORTFOLIO_SCENARIOS, SIMULATE}
_QUANT = _PRO | {BACKTEST, API_KEYS, EXPORT, DATALAB_IMPORT, DATA_PRIVATE}
_BUSINESS = _QUANT | {MEMBERS, AUDIT, GRAPH_EDIT}
_ENTERPRISE = _BUSINESS | {DATA_LICENSED}

PLANS: dict[str, Plan] = {
    "community": Plan(
        "community",
        "Community",
        "Students and people learning analysis",
        _COMMUNITY,
        {
            "ai_questions_per_day": 5,
            "watchlists": 1,
            "portfolios": 1,
            "alerts": 0,
            "members": 1,
            "api_keys": 0,
            "backtests_per_day": 0,
            "workspaces": 1,
        },
        ("Public and demonstration data", "Charts, screens of the market and one watchlist", "Portfolio analytics"),
    ),
    "pro": Plan(
        "pro",
        "Pro",
        "Analysts and independent researchers",
        _PRO,
        {
            "ai_questions_per_day": 100,
            "watchlists": 20,
            "portfolios": 10,
            "alerts": 50,
            "members": 1,
            "api_keys": 0,
            "backtests_per_day": 0,
            "workspaces": 10,
        },
        ("AI research with evidence", "Alerts, screener and reports", "Scenarios and simulations"),
    ),
    "quant": Plan(
        "quant",
        "Quant",
        "Python users and modeling teams",
        _QUANT,
        {
            "ai_questions_per_day": 200,
            "watchlists": 50,
            "portfolios": 25,
            "alerts": 200,
            "members": 1,
            "api_keys": 5,
            "backtests_per_day": 200,
            "workspaces": 25,
        },
        ("Backtesting with costs and latency", "API keys and data export", "Import your own series"),
    ),
    "business": Plan(
        "business",
        "Business",
        "Small analytical teams",
        _BUSINESS,
        {
            "ai_questions_per_day": 1000,
            "watchlists": 200,
            "portfolios": 100,
            "alerts": 1000,
            "members": 25,
            "api_keys": 25,
            "backtests_per_day": 1000,
            "workspaces": 100,
        },
        ("Team members and roles", "Audit trail", "Shared impact-graph links"),
    ),
    "enterprise": Plan(
        "enterprise",
        "Enterprise",
        "Financial institutions",
        _ENTERPRISE,
        {
            "ai_questions_per_day": UNLIMITED,
            "watchlists": UNLIMITED,
            "portfolios": UNLIMITED,
            "alerts": UNLIMITED,
            "members": UNLIMITED,
            "api_keys": UNLIMITED,
            "backtests_per_day": UNLIMITED,
            "workspaces": UNLIMITED,
        },
        ("Licensed data connectors", "Self-hosted or dedicated cloud", "Local model inference"),
    ),
}


def get_plan(code: str) -> Plan:
    return PLANS.get(code, PLANS["community"])
