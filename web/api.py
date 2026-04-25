from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from runtime.dbconn import connect
from runtime.enforce_station import enforce_once
from runtime.station_cli import station_start, action_performed, prompt_delivered, response_received, probe_request, navigate
from runtime.station_runtime import request_fact, request_facts_by_prefix


app = FastAPI(title="OCE OSCE Simulator API", version="0.1.0")


class StartStationRequest(BaseModel):
    attempt_id: str
    exam_station_id: Optional[str] = None


class ActionRequest(BaseModel):
    action_key: str


class PromptDeliveredRequest(BaseModel):
    prompt_id: str
    order_index: int
    prompt_type: str


class ResponseRequest(BaseModel):
    attempt_id: str
    prompt_id: str
    text: str


class FactRequest(BaseModel):
    case_id: str
    kind: str  # history|exam|investigation
    key: str
    requested_action_key: str


class FactsByPrefixRequest(BaseModel):
    case_id: str
    kind: str
    key_prefix: str
    requested_action_key: str
    limit: int = 50


class ProbeRequest(BaseModel):
    kind: str = "clarification"


class NavigateRequest(BaseModel):
    to_order_index: int
    action: str = "go_to_prompt"


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True}


@app.post("/station/start")
def station_start_route(req: StartStationRequest) -> Dict[str, Any]:
    with connect() as conn:
        conn.autocommit = True
        station_run_id = station_start(conn, attempt_id=req.attempt_id, exam_station_id=req.exam_station_id)
        return {"station_run_id": station_run_id}


@app.post("/station/{station_run_id}/enforce")
def station_enforce_route(station_run_id: str) -> Dict[str, Any]:
    with connect() as conn:
        conn.autocommit = True
        return enforce_once(conn, station_run_id=station_run_id, emit_legacy=True)


@app.post("/station/{station_run_id}/action")
def station_action_route(station_run_id: str, req: ActionRequest) -> Dict[str, Any]:
    with connect() as conn:
        conn.autocommit = True
        try:
            action_performed(conn, station_run_id=station_run_id, action_key=req.action_key)
        except SystemExit as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"ok": True}


@app.post("/station/{station_run_id}/prompt-delivered")
def station_prompt_route(station_run_id: str, req: PromptDeliveredRequest) -> Dict[str, Any]:
    with connect() as conn:
        conn.autocommit = True
        prompt_delivered(conn, station_run_id=station_run_id, prompt_id=req.prompt_id, order_index=req.order_index, prompt_type=req.prompt_type)
        return {"ok": True}


@app.post("/station/{station_run_id}/response")
def station_response_route(station_run_id: str, req: ResponseRequest) -> Dict[str, Any]:
    with connect() as conn:
        conn.autocommit = True
        response_id = response_received(conn, station_run_id=station_run_id, attempt_id=req.attempt_id, prompt_id=req.prompt_id, response_text=req.text)
        return {"response_id": response_id}


@app.post("/station/{station_run_id}/probe-request")
def station_probe_route(station_run_id: str, req: ProbeRequest) -> Dict[str, Any]:
    with connect() as conn:
        conn.autocommit = True
        return probe_request(conn, station_run_id=station_run_id, kind=req.kind)


@app.post("/station/{station_run_id}/navigate")
def station_nav_route(station_run_id: str, req: NavigateRequest) -> Dict[str, Any]:
    with connect() as conn:
        conn.autocommit = True
        return navigate(conn, station_run_id=station_run_id, to_order_index=req.to_order_index, action=req.action)


@app.post("/station/{station_run_id}/fact")
def station_fact_route(station_run_id: str, req: FactRequest) -> Dict[str, Any]:
    with connect() as conn:
        conn.autocommit = True
        fact = request_fact(
            conn,
            station_run_id=station_run_id,
            case_id=req.case_id,
            kind=req.kind,
            key=req.key,
            requested_action_key=req.requested_action_key,
        )
        return {"fact": (fact.__dict__ if fact else None)}


@app.post("/station/{station_run_id}/facts-by-prefix")
def station_facts_prefix_route(station_run_id: str, req: FactsByPrefixRequest) -> Dict[str, Any]:
    with connect() as conn:
        conn.autocommit = True
        facts = request_facts_by_prefix(
            conn,
            station_run_id=station_run_id,
            case_id=req.case_id,
            kind=req.kind,
            key_prefix=req.key_prefix,
            requested_action_key=req.requested_action_key,
            limit=req.limit,
        )
        return {"facts": [f.__dict__ for f in facts]}

