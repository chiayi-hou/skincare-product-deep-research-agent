"""Offline tests for POST /chat and GET /run. Run: .venv/bin/python tests/test_chat_api.py

The real Runner, hooks, tools and FastAPI app run; only the LLMs (scripted FakeModel) and the
external source APIs (stubbed) are replaced, so NO live Gemini/PubChem/PubMed/... is exercised.
"""
import asyncio, json, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import httpx
from agents import ModelResponse, Usage
from agents.models.interface import Model
from fastapi.testclient import TestClient
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

import app as A

CALLS = []  # (role) of every model call, to prove the Writer did/didn't run


def msg(text):
    return ResponseOutputMessage(id="m", role="assistant", status="completed", type="message",
                                 content=[ResponseOutputText(text=text, type="output_text", annotations=[])])


def call(i, tool, **args):
    return ResponseFunctionToolCall(arguments=json.dumps(args), call_id=f"c{i}", name=tool, type="function_call")


def flat(input_):
    return json.dumps(input_, default=str) if not isinstance(input_, str) else input_


class FakeModel(Model):
    async def get_response(self, system_instructions, input, model_settings, tools, output_schema,
                           handoffs, tracing, **kw):
        text, sys_ = flat(input), system_instructions or ""
        has_output = "function_call_output" in text
        if "Lead Research Coordinator" in sys_:
            CALLS.append("lead")
            current = re.search(r"Current question: (.*?)(\"|\\n|$)", text)
            q = current.group(1) if current else ""
            if "this product" in q and "CeraVe" not in text:
                out = [msg("Which product are you referring to?")]
            elif has_output:
                out = [msg("DONE")]
            else:
                tok = re.search(r"TOK\w+", q)
                tok = tok.group(0) if tok else "x"
                out = [call(1, "research", specialty="ingredient", task=f"{tok} ingredient"),
                       call(2, "research", specialty="clinical", task=f"{tok} clinical"),
                       call(3, "research", specialty="product", task=f"{tok} product")]
        elif "final writer" in sys_:
            CALLS.append("writer")
            out = [msg("REPORT: " + q_of(text))]
        else:  # researchers
            CALLS.append("researcher")
            tok = re.search(r"TOK\w+", text)
            tok = tok.group(0) if tok else "x"
            if has_output:
                out = [msg(f"findings for {tok}")]
            elif "ingredient researcher" in sys_:
                out = [call(1, "lookup_ingredient", name=tok), call(2, "wiki_search", query=tok)]
            elif "clinical-evidence" in sys_:
                out = [call(1, "pubmed_search", query=tok), call(2, "openalex_search", query=tok)]
            else:
                out = [call(1, "beauty_search", query=tok), call(2, "fda_reports", product_name=tok)]
        return ModelResponse(output=out, usage=Usage(), response_id=None)

    def stream_response(self, *a, **k):
        raise NotImplementedError


def q_of(text):
    m = re.search(r"Current question: (.*?)(\\n|\\\"|$)", text)
    return m.group(1) if m else ""


async def slow(result):
    await asyncio.sleep(0.05)
    return result


def install_fakes():
    fm = FakeModel()
    A.lead.model = A.writer.model = fm
    for t in A.researcher_templates.values():
        t.model = fm
    echo = lambda tag: (lambda x, *a, **k: {"tool": tag, "echo": x})
    A.ingredient_sources.get_pubchem_ingredient = echo("pubchem")
    A.ingredient_sources.search_wikipedia = echo("wiki")
    A.clinical_sources.search_pubmed = echo("pubmed")
    A.clinical_sources.search_openalex = echo("openalex")
    A.product_sources.search_beauty_products = echo("obf")
    A.product_sources.search_fda_cosmetic_reports = echo("fda")


install_fakes()
RESEARCH_TOOLS = {"lookup_ingredient", "wiki_search", "pubmed_search", "openalex_search",
                  "beauty_search", "fda_reports"}


def test_a_clear_question(c):
    CALLS.clear()
    r = c.post("/chat", json={"message": "Does niacinamide help with acne? TOKA", "session_id": None})
    assert r.status_code == 200, r.text
    b = r.json()
    assert list(b) == ["response", "session_id", "tool_calls"]
    assert b["response"].startswith("REPORT") and re.fullmatch(r"[A-Za-z0-9_-]{8,64}", b["session_id"])
    tc = b["tool_calls"]
    assert all(set(t) == {"agent", "name", "args", "result"} and t["agent"] for t in tc)
    names = {(t["agent"].split()[0], t["name"]) for t in tc}
    assert {("Lead", "research")} <= names
    assert {n for _, n in names} - {"research"} == RESEARCH_TOOLS, names
    assert sum(t["name"] == "research" for t in tc) == 3
    assert len(tc) == 3 + 6  # no duplicates, nothing invented
    pm = next(t for t in tc if t["name"] == "pubmed_search")
    assert pm["agent"].startswith("Clinical Researcher") and pm["args"] == {"query": "TOKA"}
    assert json.loads(pm["result"]) == {"tool": "pubmed", "echo": "TOKA"}
    assert CALLS.count("writer") == 1
    return b["session_id"]


def test_b_vague(c):
    CALLS.clear()
    r = c.post("/chat", json={"message": "Is this product good for my skin?"})
    b = r.json()
    assert r.status_code == 200 and b["response"] == "Which product are you referring to?"
    assert b["tool_calls"] == [] and CALLS == ["lead"], CALLS  # no researchers, no writer
    return b["session_id"]


def test_c_followup(c, sid):
    CALLS.clear()
    r = c.post("/chat", json={"message": "CeraVe moisturizer TOKC", "session_id": sid})
    b = r.json()
    assert b["session_id"] == sid and b["response"].startswith("REPORT") and b["tool_calls"]
    ex = list(A.conversations[sid].exchanges)
    assert [u for u, _ in ex] == ["Is this product good for my skin?", "CeraVe moisturizer TOKC"], ex
    assert ex[0][1] == "Which product are you referring to?"  # clarification kept as history
    # unknown/new session_id is not confused with an old one
    assert A.conversations[sid] is not None


def test_d_run_sse(c):
    CALLS.clear()
    with c.stream("GET", "/run", params={"question": "niacinamide TOKD"}) as r:
        events = [json.loads(l[6:]) for l in r.iter_lines() if l.startswith("data: ")]
        cookie = r.headers.get("set-cookie", "")
    types = [e["type"] for e in events]
    assert types[0] == "start" and types[-1] == "done" and "activity" in types and "context" in types
    assert events[-1]["markdown"].startswith("REPORT") and "skincare_session" in cookie
    assert any(e.get("text") == "called research" for e in events if e["type"] == "activity")
    # /run clarification: actual question returned, no writer, kept in session memory
    CALLS.clear()
    with c.stream("GET", "/run", params={"question": "Is this product good for my skin?"}) as r:
        ev = [json.loads(l[6:]) for l in r.iter_lines() if l.startswith("data: ")]
    assert ev[-1] == {"type": "done", "markdown": "Which product are you referring to?"}, ev[-1]
    assert CALLS == ["lead"]


async def test_e_concurrency():
    async def slow_echo(*a, **k):
        pass
    orig = A.clinical_sources.search_pubmed
    def delayed(x, *a, **k):
        time.sleep(0.02)
        return orig(x)
    A.clinical_sources.search_pubmed = delayed
    transport = httpx.ASGITransport(app=A.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t", timeout=30) as ac:
        toks = [f"TOKE{i}" for i in range(6)]
        rs = await asyncio.gather(*[ac.post("/chat", json={"message": f"q {t}"}) for t in toks])
    A.clinical_sources.search_pubmed = orig
    for t, r in zip(toks, rs):
        tc = r.json()["tool_calls"]
        assert len(tc) == 9, len(tc)
        assert all(t in json.dumps(x["args"]) and t in x["result"] for x in tc), (t, tc)
    assert len({r.json()["session_id"] for r in rs}) == 6


def test_f_failed_tool_and_cleanup(c):
    # a tool that raises: on_tool_end gets the SDK's error text, not a fake success
    orig = A.ingredient_sources.search_wikipedia
    def boom(*a, **k): raise RuntimeError("wiki down")
    A.ingredient_sources.search_wikipedia = boom
    b = c.post("/chat", json={"message": "q TOKF"}).json()
    A.ingredient_sources.search_wikipedia = orig
    w = next(t for t in b["tool_calls"] if t["name"] == "wiki_search")
    assert "error" in w["result"].lower() and not w["result"].startswith("{"), w
    assert all(s.active_runs == 0 for s in A.conversations.values())
    assert len(A.run_contexts) <= 4 * len(A.conversations)  # /chat stores no panel data


if __name__ == "__main__":
    with TestClient(A.app) as c:
        test_a_clear_question(c)
        sid = test_b_vague(c)
        test_c_followup(c, sid)
        test_d_run_sse(c)
        test_f_failed_tool_and_cleanup(c)
    asyncio.run(test_e_concurrency())
    print("all offline tests passed (live LLM/API paths NOT exercised)")
