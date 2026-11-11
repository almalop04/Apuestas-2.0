from app.config import Settings
from app.model import devig, kelly_stake, market_probabilities, poisson_probs
from app.picks import analyse_event, generate
from app.stats import match_team, normalize


def test_devig_sums_to_one():
    p = devig({"A": 2.0, "B": 3.5, "Draw": 3.4})
    assert abs(sum(p.values()) - 1) < 1e-9


def test_poisson_consistent():
    p = poisson_probs(1.6, 1.1)
    assert abs(p["home"] + p["draw"] + p["away"] - 1) < 1e-9
    assert p["home"] > p["away"]
    assert abs(p["over25"] + p["under25"] - 1) < 1e-9


def test_kelly():
    assert kelly_stake(0.5, 2.0, 0.25) == 0
    assert kelly_stake(0.55, 2.0, 1.0) > 9.9


def test_team_matching():
    teams = {"Wolves": 1, "Brighton": 2, "Atletico Madrid": 3, "Inter": 4, "1. FC Köln": 5, "Athletic Club": 6}
    assert match_team("Wolverhampton Wanderers", teams) == 1
    assert match_team("Brighton and Hove Albion", teams) == 2
    assert match_team("Atlético Madrid", teams) == 3
    assert match_team("Inter Milan", teams) == 4
    assert match_team("FC Koln", teams) == 5
    assert match_team("Athletic Bilbao", teams) == 6
    assert match_team("Real Madrid", {"Barcelona": 1}) is None
    assert normalize("Real Betis") == "real betis"


def _event(soft_home):
    def book(key, h, d, a):
        return {"key": key, "title": key, "markets": [{"key": "h2h", "outcomes": [
            {"name": "Home FC", "price": h}, {"name": "Draw", "price": d}, {"name": "Away FC", "price": a}]}]}
    return {"home_team": "Home FC", "away_team": "Away FC", "commence_time": "2026-11-14T15:00:00Z",
            "bookmakers": [book("pinnacle", 2.0, 3.6, 3.9), book("bet365", soft_home, 3.4, 3.6)]}


def test_value_found_vs_pinnacle():
    s = Settings(odds_api_key="x", fdio_key="", market_weight=1.0)
    fair = market_probabilities(_event(2.3), "pinnacle")
    assert fair["h2h"]["source"] == "pinnacle"
    picks = analyse_event(_event(2.3), {"name": "Test"}, None, s)
    assert len(picks) == 1 and picks[0]["selection"] == "Gana Home FC"
    assert picks[0]["edge"] > 0.1
    assert analyse_event(_event(1.9), {"name": "Test"}, None, s) == []


def test_demo_generation():
    data = generate(Settings(odds_api_key="", demo_env="1", max_odds=5.0, min_prob=0.0, max_model_gap=1.0))
    assert data["demo"] and data["matches_analysed"] > 0
    assert len(data["picks"]) <= 10
    edges = [p["edge"] for p in data["picks"]]
    assert edges == sorted(edges, reverse=True)
    assert any(p.get("xg_home") for p in data["picks"]), "el modelo de estadísticas debe emparejar equipos"


def test_manchester_united_never_matches_city():
    teams = {"Manchester City FC": {"id": 1}, "Liverpool FC": {"id": 2}}
    assert match_team("Manchester United", teams) is None
    assert match_team("Manchester City", teams)["id"] == 1
    both = {"Manchester City FC": {"id": 1}, "Manchester United FC": {"id": 3}}
    assert match_team("Manchester United", both)["id"] == 3
    assert match_team("Man Utd", both) is None  # mejor sin modelo que con el equipo equivocado


def test_longshots_and_model_disagreement_are_filtered():
    from app.picks import analyse_event
    s = Settings(odds_api_key="x", market_weight=1.0)  # rango 1.5-2.3, prob mín 40 %
    def ev(home_soft):
        def book(key, h, d, a):
            return {"key": key, "title": key, "markets": [{"key": "h2h", "outcomes": [
                {"name": "Liverpool", "price": h}, {"name": "Draw", "price": d}, {"name": "Man United", "price": a}]}]}
        return {"home_team": "Liverpool", "away_team": "Man United", "commence_time": "2026-11-22T15:00:00Z",
                "bookmakers": [book("pinnacle", 1.55, 4.4, 5.6), book("bet365", home_soft, 4.0, 6.5)]}
    # La sorpresa a 6.5 tendría "valor" pero queda fuera por cuota y probabilidad
    picks = analyse_event(ev(1.5), {"name": "PL"}, None, s)
    assert all(p["selection"] != "Gana Man United" for p in picks)
    # Favorito con valor dentro del rango -> sí sale
    picks = analyse_event(ev(1.75), {"name": "PL"}, None, s)
    assert [p["selection"] for p in picks] == ["Gana Liverpool"]
    assert picks[0]["prob"] >= 0.40
