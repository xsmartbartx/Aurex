"""Market Impact Graph: mandatory link attributes, governance, scenario paths and the Macro Agent."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from core.db import system_session
from pipelines.worker import run_one


def test_curated_graph_and_neighborhood(account):
    result = account.get("/graph/nodes/indicator:financing-costs").json()
    relations = {(link["source"]["key"], link["target"]["key"], link["relation"]) for link in result["links"]}
    assert ("indicator:eur-10y", "indicator:financing-costs", "transmits_to") in relations
    assert ("indicator:financing-costs", "sector:utilities", "exposed_to") in relations
    for link in result["links"]:
        assert link["source_ref"] and link["method"] and 0 <= link["confidence"] <= 1 and link["confidence_basis"]
    reported = [link for link in result["links"] if link["method"] == "reported_fact" and link["evidence"]]
    assert reported and "Interest rate risk" in reported[0]["evidence"]["text"]  # the company's own filing


def test_statistical_links_carry_window_and_error(account):
    result = account.get("/graph/nodes/instrument:DEMO10.DEMO").json()
    estimates = [link for link in result["links"] if link["method"] == "statistical_estimate"]
    assert len(estimates) == 10
    for link in estimates:
        assert link["estimation"]["observations"] > 200 and link["estimation"]["standard_error"] > 0
        assert "Not evidence of cause and effect" in link["description"]


def test_scenario_paths_use_weakest_link_and_are_not_forecasts(account):
    result = account.get("/graph/scenario", params={"start": "event:ecb-policy", "direction": "rises"}).json()
    assert "not a forecast" in result["label"]
    utilities = [p for p in result["paths"] if p["end"]["key"] == "sector:utilities"]
    assert utilities and utilities[0]["effect"] == "falls"
    for path in result["paths"]:
        assert path["confidence"] == pytest.approx(min(s["link"]["confidence"] for s in path["steps"]))
        assert all(s["link"]["method"] != "statistical_estimate" for s in path["steps"])
    falling = account.get("/graph/scenario", params={"start": "event:ecb-policy", "direction": "falls"}).json()
    assert [p for p in falling["paths"] if p["end"]["key"] == "sector:utilities"][0]["effect"] == "rises"


def test_links_need_source_and_proposals_stay_private_until_reviewed(make_account):
    analyst = make_account(plan="business")
    other = make_account(plan="business")
    body = {
        "source": "indicator:financing-costs",
        "target": "sector:industrials",
        "relation": "exposed_to",
        "confidence": 0.5,
        "confidence_basis": "Capital-intensive manufacturers",
        "source_ref": "Internal memo",
        "sign": -1,
        "description": "Industrials borrow to fund equipment.",
    }
    assert analyst.post("/graph/links", {**body, "source_ref": ""}).status_code == 422
    proposal = analyst.post("/graph/links", body).json()
    assert proposal["review_status"] == "proposed" and proposal["private"]

    def ends(account, proposed=False):
        result = account.get("/graph/nodes/sector:industrials", params={"proposed": proposed}).json()
        return [link for link in result["links"] if link["id"] == proposal["id"]]

    assert ends(analyst) == [] and len(ends(analyst, proposed=True)) == 1  # hidden by default
    assert ends(other, proposed=True) == []  # never visible to another organization
    assert analyst.post(f"/graph/links/{proposal['id']}/review", {"decision": "accepted"}).status_code == 200
    assert len(ends(analyst)) == 1 and ends(other) == []
    assert make_account(plan="pro").post("/graph/links", body).status_code == 403


def test_database_refuses_links_without_source():
    with pytest.raises(IntegrityError), system_session() as session:
        session.execute(
            text(
                "INSERT INTO graph_links (id, source_id, target_id, relation, method, confidence, confidence_basis, "
                "source_ref, sign, review_status, estimation) SELECT gen_random_uuid(), a.id, b.id, 'supplies', "
                "'analyst_defined', 0.5, 'x', '', 0, 'accepted', '{}' FROM graph_nodes a, graph_nodes b LIMIT 1"
            )
        )


def test_macro_agent_explains_paths_with_evidence(account):
    response = account.post(
        "/intelligence/questions", {"question": "What happens if the ECB raises rates?", "agent": "macro"}
    )
    while run_one():
        pass
    record = account.get(f"/intelligence/questions/{response.json()['id']}").json()
    claims = [c for s in record["answer"]["sections"] for c in s["claims"]]
    assert any(c["text"].startswith("Starting from") and "Utilities falls" in c["text"] for c in claims)
    assert all(c["status"] == "supported" for c in claims)
    assert any("not a forecast" in g for g in record["answer"]["gaps"])
