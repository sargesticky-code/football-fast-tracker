import importlib.util
from pathlib import Path

P=Path(__file__).parents[1]/"scripts"/"build_graph_sandwich_shadow.py"
spec=importlib.util.spec_from_file_location("gs",P); gs=importlib.util.module_from_spec(spec); spec.loader.exec_module(gs)

def test_shadow_graph_relationships():
    rows=[{"hkjc_event_id":"FB1","kickoff_hkt":"2026-09-28T20:00+08:00","status":"UPCOMING","tournament":"EPL",
           "home_zh":"阿仙奴","away_zh":"車路士","had_home":"2.10","had_draw":"3.30","had_away":"3.10",
           "hil_line":"2.5","hil_over":"1.90","hil_under":"1.90","chl_line":"9.5","chl_over":"1.85","chl_under":"1.95",
           "fetched_at_hkt":"2026-09-28T10:00+08:00","odds_updated_at":"2026-09-28T09:59+08:00"}]
    forms=[{"hkjc_event_id":"FB1","home_form6":"WWDLWW","away_form6":"LLDWLL","home_gf_avg":"1.8","home_ga_avg":"0.9","away_gf_avg":"0.8","away_ga_avg":"1.7","quality":"FOREBET_OK","source":"Forebet"}]\n    power=[{"hkjc_event_id":"FB1","home_rating":"88.2","away_rating":"82.1","coverage":"BOTH","source":"Opta Power Rankings"}]
    preds=[{"hkjc_event_id":"FB1","source":"APWIN","recommendation":"Home +0.25","market":"AH","match_score":"0.88","status":"OK"}]
    g=gs.build(rows,forms,power,preds)
    assert g["schema"]=="GS_SHADOW_V1"
    assert g["stats"]=={"matches":1,"teams":2,"markets":3,"forms":1,"model_signals":2,"why_chains":1,"edges":9}
    assert {n["type"] for n in g["nodes"]}=={"MATCH","TEAM","MARKET","SOURCE","FORM","MODEL_SIGNAL","PREDICTION"}
    assert any(e["relation"]=="PLAYS_IN" and e["side"]=="HOME" for e in g["edges"])
\n    assert g["why_chains"][0]["confidence"]=="EVIDENCE_RICH"\n    assert "recent_form_available" in g["why_chains"][0]["why_chain"]\n
    assert "model_signals:2" in g["why_chains"][0]["why_chain"]
