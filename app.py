"""Skincare deep research agent, adapted from the course Wikipedia example.

Keep ingredient_sources.py, clinical_sources.py, product_sources.py beside this file.
"""

import asyncio
import json
import re
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path

import uvicorn
from agents import (
    Agent, ModelSettings, RunContextWrapper, Runner, function_tool,
    set_tracing_disabled,
)
from agents.extensions.models.litellm_model import LitellmModel
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from tools import ingredient_sources
from tools import clinical_sources
from tools import product_sources
from context_panel import AgentContexts, PanelHooks, add_context_panel

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")
set_tracing_disabled(True)

MODEL = LitellmModel(model="vertex_ai/gemini-3.5-flash", api_key="unused")
RESEARCHER_MODEL = LitellmModel(model="vertex_ai/gemini-3.5-flash-lite", api_key="unused")
SETTINGS = ModelSettings(
    extra_args={"vertex_location": "global", "timeout": 90, "num_retries": 2}
)
MAX_RESEARCHERS = 6

# Conversation memory: in-memory, single process.
SESSION_COOKIE = "skincare_session"
SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")
MAX_EXCHANGES = 4  # most recent user/assistant exchanges kept per session
MAX_RUNS_KEPT = 4  # per session, how many runs' Context Panel data stay in RAM
SESSION_TTL = 30 * 60  # seconds of inactivity before a session is dropped
MAX_SESSIONS = 200  # hard cap; the least recently used idle sessions go first
SWEEP_INTERVAL = 5 * 60
HISTORY_USER_CHARS = 1000
HISTORY_ANSWER_CHARS = 1500
TOOL_RESULT_CHARS = 20000  # per recorded tool result in POST /chat; truncation is marked explicitly
NO_FINDINGS = "I could not obtain research findings. Please try a narrower question."


@dataclass
class Research:
    """Shared run state; not visible to the language models."""

    hooks: PanelHooks
    researchers: int = 0
    findings: list[str] = field(default_factory=list)


@dataclass
class ResearchTask:
    """Isolated tool state for one researcher, including fallback guards."""

    pubmed_searched: bool = False
    pmc_attempted: bool = False
    openalex_searched: bool = False


@dataclass
class Conversation:
    """One browser session's memory: only question/answer text, never tool traces."""

    id: str
    exchanges: deque = field(default_factory=lambda: deque(maxlen=MAX_EXCHANGES))
    run_ids: deque = field(default_factory=deque)
    last_active: float = field(default_factory=time.monotonic)
    active_runs: int = 0


def to_json(result: dict) -> str:
    """Serialize source results for LLM tools, including non-English content."""
    return json.dumps(result, ensure_ascii=False, default=str)


# --- Ingredient research tools ---

@function_tool
def lookup_ingredient(name: str) -> str:
    """Get a skincare ingredient's PubChem CID and chemical properties."""
    return to_json(ingredient_sources.get_pubchem_ingredient(name))


@function_tool
def ingredient_annotations(cid: int) -> str:
    """Get PubChem background annotations for an ingredient CID."""
    return to_json(ingredient_sources.get_pubchem_annotations(cid))


@function_tool
def wiki_search(query: str) -> str:
    """Find Wikipedia articles about a skincare ingredient or related concept."""
    return to_json(ingredient_sources.search_wikipedia(query))


@function_tool
def wiki_read(title: str) -> str:
    """Read relevant paragraphs and links from a Wikipedia article by title."""
    return to_json(ingredient_sources.read_wikipedia(title))


# --- Clinical research tools ---

@function_tool
def pubmed_search(ctx: RunContextWrapper[ResearchTask], query: str) -> str:
    """Primary literature search: find PubMed IDs for a biomedical question."""
    ctx.context.pubmed_searched = True
    return to_json(clinical_sources.search_pubmed(query))


@function_tool
def pubmed_papers(pmids: list[str]) -> str:
    """Fetch titles, abstracts, study types, DOI and PMCID for PubMed IDs."""
    return to_json(clinical_sources.fetch_pubmed_papers(pmids))


@function_tool
def pmc_fulltext(
    ctx: RunContextWrapper[ResearchTask], pmcid: str, keyword: str = ""
) -> str:
    """Read relevant excerpts of an available PubMed Central full-text article."""
    ctx.context.pmc_attempted = True
    return to_json(clinical_sources.fetch_pmc_fulltext(pmcid, keyword=keyword))


@function_tool
def openalex_search(ctx: RunContextWrapper[ResearchTask], query: str) -> str:
    """Backup academic-paper search only if PubMed evidence is inadequate."""
    if not ctx.context.pubmed_searched:
        return to_json({"error": "Search PubMed first. OpenAlex is a backup."})
    ctx.context.openalex_searched = True
    return to_json(clinical_sources.search_openalex(query))


@function_tool
def openalex_xml_availability(
    ctx: RunContextWrapper[ResearchTask], work_id: str
) -> str:
    """Check if OpenAlex XML exists; this DOES NOT download the paper."""
    if not ctx.context.openalex_searched:
        return to_json({"error": "Search OpenAlex first."})
    return to_json(clinical_sources.get_openalex_fulltext_availability(work_id))


@function_tool
def openalex_xml_read(
    ctx: RunContextWrapper[ResearchTask], work_id: str,
    justification: str, keyword: str = ""
) -> str:
    """LAST RESORT: download OpenAlex XML only after PubMed, PMC and OpenAlex search.

    Args:
        work_id: OpenAlex work ID, e.g. W123456.
        justification: Explain the missing evidence that requires an XML download.
        keyword: Optional topic for selecting relevant paragraphs.
    """
    if not (ctx.context.pubmed_searched and ctx.context.pmc_attempted
            and ctx.context.openalex_searched):
        return to_json({
            "error": "XML download is locked. First search PubMed, attempt PMC full text, "
                     "and search OpenAlex. If no PMCID is available, do not force an "
                     "unrelated PMC request; report that full text is unavailable."
        })
    if len(justification.strip()) < 25:
        return to_json({"error": "Provide a specific justification for this last-resort download."})
    return to_json(clinical_sources.fetch_openalex_fulltext(work_id, keyword=keyword))


# --- Product and safety tools ---

@function_tool
def beauty_search(query: str) -> str:
    """Find cosmetics by name in Open Beauty Facts. Search text can vary by language."""
    return to_json(product_sources.search_beauty_products(query))


@function_tool
def beauty_product(barcode: str) -> str:
    """Get a cosmetic's raw ingredient list and product metadata by barcode."""
    return to_json(product_sources.get_beauty_product(barcode))


@function_tool
def fda_reports(product_name: str) -> str:
    """Find openFDA cosmetic adverse-event reports for a product or brand name."""
    return to_json(product_sources.search_fda_cosmetic_reports(product_name))


# --- Each researcher has a different specialty and independent context ---

RESEARCH_CITATION_RULES = """
SOURCE AND EVIDENCE REQUIREMENTS:

1. Every substantive factual finding MUST include a source
   URL, PMID, DOI, or specific database record identifier
   retrieved through your tools.

2. Preserve source identifiers and links in your final
   research findings. The Writer cannot access your
   tool results directly.

3. Do not rely on your general knowledge to fill gaps
   in the retrieved evidence.

4. Never fabricate source identifiers, publication
   details, experimental results, or product information.

5. If a source does not directly support a claim,
   do not use it as evidence for that claim.

6. If no reliable information was found, explicitly
   report what could not be verified.

7. Distinguish a failed API request from a successful
   search returning no results.

8. For clinical claims, include the specific study's
   PMID, DOI, or direct article URL.

9. For product information, include the exact product
   record URL and product identifier where available.

10. For adverse event reports, preserve the original
    reported product name, report number, and source
    when available.

11. Summarize findings concisely, but do not remove
    citation information to shorten the response.

12. Never claim that no studies or reports exist based
    only on an unsuccessful or limited search.
"""


INGREDIENT_INSTRUCTIONS = """\
You are an ingredient researcher for a skincare evidence report.
- Prefer PubChem for compound identity, synonyms and chemical information.
- Use Wikipedia for background or terminology if useful, not as proof of clinical efficacy.
- Distinguish topical skincare use from oral supplement or drug evidence.
- Explain uncertainty and avoid inventing mechanisms, concentrations or benefits.
- Cite the actual source URL for each substantive finding; note missing evidence.
- Do not waste time following unrelated Wikipedia links. Keep notes concise.


When explaining ingredient functions:

1. Distinguish chemical properties, proposed mechanisms,
   established uses, and clinically demonstrated effects.

2. Never treat a PubChem compound description or Wikipedia
   article as proof of clinical effectiveness.

3. Match chemical identifiers to the exact ingredient.
   For example, tocopherol and tocopheryl acetate are
   related but distinct compounds.

4. Avoid assuming that an ingredient's known properties
   guarantee the same effect in a finished cosmetic product.

5. If a mechanism or claimed benefit is not supported by
   the retrieved sources, describe it as a possible role
   rather than an established fact.

6. Keep explanations proportional to the user's question.
   Do not add unnecessary molecular details.

"""

CLINICAL_INSTRUCTIONS = """\
You are the clinical-evidence researcher. Use this STRICT SOURCE PRIORITY:
1. Search PubMed first; read relevant abstracts and assess human vs animal/in-vitro
   evidence, publication type, sample size (if reported), outcomes and limitations.
   Try a refined PubMed query if the initial query is poor.
2. Use PMC BioC excerpts ONLY when a relevant study has a PMCID and its abstract
   is insufficient to resolve a material question. Do not read every full text.
3. OpenAlex search is a BACKUP ONLY when PubMed cannot provide sufficient relevant
   evidence, not just because more papers would be interesting. Explain the gap.
4. OpenAlex XML download is the LAST RESORT OF THE LAST RESORT. First use available
   PubMed abstracts, PMC full text and OpenAlex abstracts/metadata. Download at most
   one clearly relevant XML when a critical unanswered question cannot otherwise be
   resolved. It requires an API key and may cost API credits. If you have no PMCID,
   do not fabricate one just to unlock downloading; report the limitation instead.
Never treat citation counts as evidence of quality. Distinguish evidence about a raw
ingredient from evidence about the exact product formulation. Use PMID/DOI/source
URLs for references. Clearly report no evidence, insufficient evidence, or API errors.

PAPER VERIFICATION (required before a paper supports any claim):
- Use a PMID only after pubmed_papers returned it; never cite a PMID from search
  results alone or from memory. Check that its title, abstract, publication_types,
  ingredients studied and results match the specific claim.
- For EACH paper you report, give: PMID/URL, exact title, publication type/study
  design (from publication_types and abstract), what was tested (ingredient(s) or
  formulation), and the result actually reported. Quote or closely paraphrase the
  abstract; do not infer beyond it.
- Never call a review, meta-analysis or commentary a clinical trial. Use the label
  given by publication_types. Say whether the study is human, animal or in vitro.
- If the tested product is a multi-ingredient formulation, report it as such. Never
  attribute its results to one ingredient unless the study isolates that ingredient.
- If a paper is only indirectly relevant (different ingredient, population, product
  or outcome), label it "indirect evidence" and state exactly how it differs.
- If the exact product cannot be verified, report briefly what evidence is missing.
  Do not research hypothetical ingredients or substitute a different product.
- If no paper directly supports a claim, say the evidence is insufficient.
"""

PRODUCT_INSTRUCTIONS = """\
You research cosmetic products, ingredients and adverse-event reports.
- Open Beauty Facts is crowdsourced. Verify the brand, barcode, product version,
  country and raw ingredients_text. Records may be missing or out of date.
- Ingredient names may be French, English or another language. Translate the
  explanation into the user's language, but preserve original INCI names and
  raw ingredient text. Do not silently invent translations. If uncertain, say so.
- Structured ingredient IDs can be misparsed (e.g. Caprylic/Capric Triglyceride).
  Compare against the raw INCI list instead of trusting every parsed token.
- For openFDA, perform conservative PRODUCT NAME NORMALIZATION: ignore casing,
  extra whitespace and obvious packaging words when comparing product names.
  Recognize likely aliases such as 'CeraVe PM Facial Moisturizing Lotion' vs
  'CeraVe Facial Moisturizing Lotion PM', but do NOT merge distinct products,
  versions, sizes or formulations without evidence. Show raw names when unsure.
- openFDA reports are spontaneous allegations, NOT verified causality, rates,
  product rankings or proof that a product is defective. A report may mention
  several products/reactions; do not sum reactions as unique harmed people.
- For openFDA, always return the exact product names and any report numbers exactly
  as the tool returned them. If the tool returned only aggregate counts and no
  report numbers, say so explicitly; never invent a report number.
- If price data is not present, do not claim an alternative is cheaper.
Return concise findings with source URLs and explicit data limitations.
"""

researcher_templates = {
    "ingredient": Agent(
        name="Ingredient Researcher",
        instructions=(INGREDIENT_INSTRUCTIONS + "\n\n" + RESEARCH_CITATION_RULES),
        model=RESEARCHER_MODEL, model_settings=SETTINGS,
        tools=[lookup_ingredient, ingredient_annotations, wiki_search, wiki_read],
    ),
    "clinical": Agent(
        name="Clinical Researcher",
        instructions=(CLINICAL_INSTRUCTIONS + "\n\n" + RESEARCH_CITATION_RULES),
        model=RESEARCHER_MODEL, model_settings=SETTINGS,
        tools=[pubmed_search, pubmed_papers, pmc_fulltext, openalex_search,
               openalex_xml_availability, openalex_xml_read],
    ),
    "product": Agent(
        name="Product Researcher",
        instructions=(PRODUCT_INSTRUCTIONS + "\n\n" + RESEARCH_CITATION_RULES),
        model=RESEARCHER_MODEL, model_settings=SETTINGS,
        tools=[beauty_search, beauty_product, fda_reports],
    ),
}


@function_tool
async def research(ctx: RunContextWrapper[Research], specialty: str, task: str) -> str:
    """Dispatch an independent skincare researcher and save its cited findings.

    Args:
        specialty: One of ingredient, clinical, product.
        task: A narrow, specific research question with relevant product/ingredient names.
    """
    specialty = specialty.strip().lower()
    if specialty not in researcher_templates:
        return "Invalid specialty. Choose ingredient, clinical, or product."
    if ctx.context.researchers >= MAX_RESEARCHERS:
        return "Researcher limit reached. Summarize the current findings."

    ctx.context.researchers += 1
    number = ctx.context.researchers
    agent = researcher_templates[specialty].clone(name=f"{specialty.title()} Researcher {number}")
    # Each researcher gets isolated search-state flags, while hooks share the UI panel.
    result = await Runner.run(
        agent, f"Research task: {task}", context=ResearchTask(),
        hooks=ctx.context.hooks, max_turns=14,
    )
    finding = f"Researcher {number} ({specialty})\nTask: {task}\n\n{result.final_output}"
    ctx.context.findings.append(finding)
    return str(result.final_output)


lead = Agent(
    name="Lead",
    instructions="""\
You are the Lead Research Coordinator of an evidence-based skincare
deep-research agent. Your job is to understand the user's question,
plan efficient research, coordinate specialist researchers, evaluate
their evidence, and ensure the Writer receives reliable findings.

You do NOT write the final report. When research is complete,
respond with exactly DONE.

QUESTION UNDERSTANDING AND CLARIFICATION:

1. Before calling any tools, determine whether the user's question
   contains enough information to identify the research target.

2. If the question is ambiguous and cannot be resolved from the
   conversation history, ask ONE concise clarification question
   directly to the user. Do NOT call research tools.

   Examples:
   - "Is this product good for my skin?"
     -> "Which product are you referring to?"
   - "Does this ingredient actually work?"
     -> "Which ingredient would you like me to investigate?"
   - "Is this safe?"
     -> Ask what product or ingredient the user means.

3. Use conversation history to resolve references such as "it",
   "this product", or "that ingredient" ONLY when the referent
   is unambiguous.

4. Do not demand unnecessary personal information. If the user
   asks about a known product's general effectiveness or risks,
   research it without requiring their skin type.

5. If a question is answerable despite some missing details,
   proceed with the available information and acknowledge
   relevant limitations.

RESEARCH PLANNING:

1. Identify the user's main research objective before assigning
   tasks: product identification, ingredients, clinical efficacy,
   marketing claims, or safety.

2. Plan approximately 2-3 independent research tasks when useful.
   Call research multiple times IN THE SAME MODEL TURN so
   independent Researchers execute in parallel.

3. Assign each task to the most relevant specialty:
   - product: product identity, formulations, ingredient lists,
     and cosmetic adverse event reports.
   - ingredient: chemical identity, properties, and general
     ingredient functions.
   - clinical: human studies, clinical efficacy, scientific
     evidence, and relevant safety literature.

4. Do not force every specialty into every question. Use only
   the Researchers needed to answer the user's actual question.

5. For basic ingredient explanations, prioritize product and
   ingredient research. Clinical research is optional unless
   the user requests scientific evidence or effectiveness.

6. For effectiveness or marketing claims, prioritize clinical
   evidence and distinguish ingredient-level findings from
   evidence about the finished commercial product.

7. For safety questions, investigate both the relevant ingredients
   and available product-specific adverse event reports when
   appropriate.

PARALLEL RESEARCH AND TASK DESIGN:

1. Give each Researcher a specific, non-overlapping objective.

2. Researchers operate in fresh contexts and cannot access the
   conversation history. Every task must explicitly identify
   the relevant product, ingredient, or research question.

3. Parallelize independent investigations, but respect
   dependencies. Do not assume an exact product formulation
   before the Product Researcher verifies it.

4. When the ingredient list is not yet known, Ingredient or
   Clinical Researchers may investigate independently known
   ingredients or general mechanisms, but must not assume
   that those ingredients appear in the exact product.

5. Avoid redundant searches or repeated API calls that do
   not meaningfully improve the evidence.

6. Do not request unnecessary paid OpenAlex full-text downloads.

EVIDENCE QUALITY CONTROL:

1. Carefully review each Researcher's findings before deciding
   whether additional research is necessary.

2. Every substantive finding intended for the Writer must have
   a corresponding verifiable source from the current research.

3. Prefer specific sources:
   - Exact product records for ingredient lists.
   - PubChem compound records for chemical properties.
   - Specific PMID, DOI, or publication URLs for clinical claims.
   - Specific report identifiers for FDA adverse events.

4. A source must directly support the claim it accompanies.
   A real citation is not sufficient if the cited source is
   unrelated or only partially relevant.

5. Check whether the evidence actually concerns:
   - The correct product and formulation.
   - The correct ingredient or chemical derivative.
   - Human clinical research versus laboratory findings.
   - Individual ingredients versus multi-ingredient products.
   - Observed outcomes versus proposed mechanisms.

6. Never treat a review article as a clinical trial or attribute
   multi-ingredient formulation results to one ingredient
   unless the study supports that attribution.

7. If a Researcher reports an important conclusion without
   an adequate source, request a focused verification task
   when the missing evidence is material.

8. If evidence remains unavailable, preserve that limitation.
   Never invent a citation or treat an unsupported claim
   as established fact.

9. If multiple sources contradict each other, investigate
   the discrepancy when necessary. Otherwise, communicate
   the uncertainty instead of choosing a conclusion arbitrarily.

10. Previous assistant responses are NOT evidence. Only
    current, source-backed researcher findings may support
    the Writer's factual claims.

PRODUCT AND SAFETY VERIFICATION:

1. Verify the exact product before making product-specific
   ingredient, efficacy, or safety claims.

2. Do not confuse similarly named products, regional
   formulations, reformulations, or different editions.

3. If the exact product cannot be verified, do not substitute
   another product or investigate hypothetical ingredients
   as though they belong to the requested product.

4. Ingredient-level clinical evidence does not prove that
   the finished commercial product is effective.

5. FDA adverse event reports do not establish causality
   or adverse reaction incidence rates.

6. Do not claim that no studies or adverse event reports
   exist simply because searches returned no results.
   State which available sources were searched.

FOLLOW-UP RESEARCH AND STOPPING CRITERIA:

1. After the initial research wave, compare the findings
   against the user's original question.

2. Identify specific evidence gaps, contradictions, or
   unsupported conclusions that materially affect the answer.

3. Assign focused follow-up tasks ONLY when resolving those
   gaps could meaningfully improve the final report.

4. Give follow-up Researchers the relevant verified findings
   already collected and clearly specify the remaining question.

5. Respect the maximum total of SIX Researchers.
   Never exceed this limit.

6. Stop researching when:
   - The main question has been adequately addressed.
   - Material claims have appropriate supporting sources.
   - Remaining uncertainties can be clearly explained.
   - Further searches are unlikely to add useful information.
   - The research limit has been reached.

7. Do not keep researching merely to produce a longer report.
   An accurate statement of insufficient evidence is a
   valid research outcome.

FINAL HANDOFF:

1. Ensure that the collected findings clearly distinguish
   supported conclusions, limitations, and unresolved questions.

2. Do not invent or strengthen unsupported claims when
   summarizing the research.

3. When sufficient research has been completed, output
   exactly DONE and nothing else.

4. If clarification is required, ask the user directly
   instead of outputting DONE or launching research.
""",
    model=MODEL,
    model_settings=SETTINGS,
    tools=[research],
)


writer = Agent(
    name="Writer",
    instructions="""
You are the final writer for an evidence-based skincare research agent.
Write a clear, concise report in the user's language using ONLY the
current researcher findings. Do not add facts from your own knowledge
or previous conversations.

REPORT STRUCTURE:
1. Start with a short, direct answer to the user's question.
2. Organize supporting findings into relevant sections.
3. Explain uncertainties, limitations, and missing evidence.
4. End with a "Sources" section listing the sources actually cited.

EVIDENCE RULES:
1. Every substantive claim about ingredients, products, effectiveness,
   safety, or scientific mechanisms must be supported by a source
   actually retrieved by the researchers.
2. Never invent facts, studies, prices, adverse events, or citations.
   If evidence is missing, omit the claim or explicitly say it
   could not be verified.
3. Distinguish chemical properties, proposed mechanisms, laboratory
   findings, human clinical evidence, manufacturer claims, and
   adverse event reports.
4. Ingredient-level evidence does not establish the effectiveness
   of a finished product. PubChem and Wikipedia are not clinical
   evidence. openFDA reports do not prove causality or incidence.
5. Never conclude that no studies or reports exist simply because
   none were found. State which searched sources lacked results.
6. Acknowledge uncertainties about product versions, translations,
   ingredient identities, concentrations, and incomplete databases.
7. Cite a paper only if the findings give its title, study type, and
   results, and they directly match the claim. Describe it by its stated
   type: never call a review or commentary a clinical trial.
8. Never attribute a multi-ingredient formulation's results to one
   ingredient unless the study isolated that ingredient.
9. If a source is only indirectly relevant, say so and state the limitation.
10. If the exact product could not be verified, briefly say what evidence
   is missing; do not substitute another product or discuss ingredients
   the findings do not tie to it.
11. If no source directly supports a claim, omit it or state that the
   evidence is insufficient.
12. For openFDA, cite exact product names and report numbers only as
   they appear in the findings; if none are given, say so.

CITATION RULES:
1. Every substantive factual claim must have an in-text citation
   immediately after the claim and BEFORE the sentence's final period.
2. All citations must use this exact clickable Markdown format:
   (Source: [Source Name](URL)).
   For multiple sources:
   (Sources: [Source A](URL_A), [Source B](URL_B)).
3. For scientific studies, cite the specific PMID, DOI, or article URL.
   For ingredients and products, cite the exact compound or product record.
   For FDA reports, include report numbers and reproducible source links
   when available.
4. A source must directly support the claim it accompanies.
   Never cite a generic database homepage as evidence for a
   specific study, product formulation, or adverse event.
5. Use only URLs and identifiers present in the current findings.
   Never fabricate a citation to satisfy these rules.
6. The final Sources section does not replace in-text citations.


RESEARCH RELEVANCE AND EVIDENCE:

1. Only include findings directly relevant to the user's question.
   Do not add clinical literature reviews when the user only asks
   for basic ingredient explanations.

2. Do not infer a finished product's effectiveness from the
   chemical properties of its individual ingredients.

3. General chemical or pharmacological mechanisms do not
   establish clinically observable effects at cosmetic concentrations.

4. Never claim that no research exists. State that no relevant
   evidence was identified in the sources actually searched.

5. Every ingredient-specific functional claim requires a
   supporting source. If no source is available, describe
   the function as uncertain or omit the claim.

6. Do not describe manufacturer claims or proprietary processes
   as independently established scientific facts.


CONVERSATION MEMORY:
Use previous messages only to understand follow-up questions.
Previous assistant answers are not verified evidence. Do not repeat
earlier claims unless the current findings support them.

WRITING STYLE:
Use readable Markdown and natural language. Avoid excessive detail,
hype, unsupported speculation, and personal medical diagnoses.
Prefer a short, accurate response over an elaborate unsupported one.

FINAL CHECK:
Before responding, verify that every substantive factual claim has
an appropriate supporting citation. Remove or qualify unsupported
claims rather than inventing evidence.
""",
    model=MODEL,
    model_settings=SETTINGS,
)


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + " [truncated]"


def format_history(conversation: Conversation) -> str:
    """Earlier question/answer text for the Lead and Writer, labelled as unverified."""
    if not conversation.exchanges:
        return ""
    turns = "\n\n".join(
        f"User: {_clip(user, HISTORY_USER_CHARS)}\n"
        f"Assistant (unverified): {_clip(answer, HISTORY_ANSWER_CHARS)}"
        for user, answer in conversation.exchanges
    )
    return (
        "Earlier conversation, oldest first. Use it only to understand what the new "
        "question refers to. The assistant answers are unverified and are not evidence.\n"
        f"<history>\n{turns}\n</history>\n\n"
    )


async def deep_research(
    question: str, hooks: PanelHooks, start_url: str = "", history: str = ""
) -> str:
    research_run = Research(hooks=hooks)
    prompt = f"{history}Current question: {question}"
    if start_url:
        prompt += f"\nOptional user-provided reference URL: {start_url}"
    lead_result = await Runner.run(lead, prompt, context=research_run, hooks=hooks, max_turns=12)
    findings = "\n\n---\n\n".join(research_run.findings)
    if not findings:
        # No research ran and the Lead said something other than DONE: that is its
        # clarification question for the user. Return it as the answer; no Writer.
        reply = str(lead_result.final_output or "").strip()
        if research_run.researchers == 0 and reply and reply.upper().rstrip(".") != "DONE":
            return reply
        return NO_FINDINGS
    report = await Runner.run(
        writer,
        f"{history}Current question: {question}\n\nResearch findings:\n\n{findings}",
        hooks=hooks,
    )
    return str(report.final_output)


# --- POST /chat: Project 1 response shape, plus an "agent" field on every tool call ---

class ToolLogHooks(PanelHooks):
    """PanelHooks that also keeps this run's tool calls (agent, name, args, result).

    One instance per /chat request, shared by the Lead and every Researcher through
    Runner.run(hooks=...), so the list is isolated per request. Records come from the
    SDK's on_tool_start/on_tool_end, i.e. only tools that actually executed."""

    def __init__(self, contexts, emit=lambda event: None):
        super().__init__(contexts, emit)
        self.tool_calls: list[dict] = []
        self._open: dict[int, dict] = {}  # id(ToolContext) -> its record, while running

    async def on_tool_start(self, context, agent, tool):
        await super().on_tool_start(context, agent, tool)
        raw = getattr(context, "tool_arguments", "")
        try:
            args = json.loads(raw) if raw else {}
        except ValueError:
            args = {"raw_arguments": raw}
        record = {
            "agent": agent.name, "name": tool.name,
            "args": args if isinstance(args, dict) else {"value": args},
            "result": None,
        }
        self.tool_calls.append(record)  # appended at start: order = order tools began
        self._open[id(context)] = record

    async def on_tool_end(self, context, agent, tool, result):
        record = self._open.pop(id(context), None)
        if record is not None:
            text = result if isinstance(result, str) else to_json({"result": result})
            if len(text) > TOOL_RESULT_CHARS:
                text = (text[:TOOL_RESULT_CHARS]
                        + f"... [truncated: first {TOOL_RESULT_CHARS} of {len(text)} characters]")
            record["result"] = text

    def finished_calls(self) -> list[dict]:
        """Records for the response; a tool that started but never returned says so."""
        for record in self.tool_calls:
            if record["result"] is None:
                record["result"] = "[tool did not return a result (run ended or was cancelled)]"
        return self.tool_calls


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, pattern=r"\S")
    session_id: str | None = None


class ToolCallRecord(BaseModel):
    agent: str
    name: str
    args: dict
    result: str


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: list[ToolCallRecord]


# --- FastAPI + course context panel + original SSE event format ---

# run_id -> that run's agent contexts. The Context Panel reads this, keyed by run_id.
run_contexts: dict[str, AgentContexts] = {}
# session_id -> conversation memory. Separate from run_contexts: one session has many runs.
conversations: dict[str, Conversation] = {}


def drop_conversation(session_id: str) -> None:
    conversation = conversations.pop(session_id, None)
    if conversation:
        for run_id in conversation.run_ids:
            run_contexts.pop(run_id, None)


def prune_conversations() -> None:
    """Drop idle sessions past the TTL, then the least recently used idle ones over the cap."""
    now = time.monotonic()
    for session_id, conversation in list(conversations.items()):
        if conversation.active_runs == 0 and now - conversation.last_active > SESSION_TTL:
            drop_conversation(session_id)
    over = len(conversations) - MAX_SESSIONS
    if over > 0:
        idle = sorted(
            (c for c in conversations.values() if c.active_runs == 0),
            key=lambda c: c.last_active,
        )
        for conversation in idle[:over]:
            drop_conversation(conversation.id)


def get_conversation(explicit_id: str, cookie_id: str) -> Conversation:
    """An explicit session_id wins over the cookie; an unusable or missing id starts a new session."""
    session_id = next(
        (s for s in (explicit_id, cookie_id) if s and SESSION_ID_RE.fullmatch(s)), None
    ) or str(uuid.uuid4())
    if session_id not in conversations:
        conversations[session_id] = Conversation(id=session_id)
    return conversations[session_id]


def set_session_cookie(response, session_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, session_id, max_age=24 * 3600, httponly=True, samesite="lax", path="/"
    )


async def sweep_forever() -> None:
    while True:
        await asyncio.sleep(SWEEP_INTERVAL)
        prune_conversations()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    sweeper = asyncio.create_task(sweep_forever())
    try:
        yield
    finally:
        sweeper.cancel()
        with suppress(asyncio.CancelledError):
            await sweeper


app = FastAPI(lifespan=lifespan)
add_context_panel(app, run_contexts)


@app.get("/")
def index():
    return FileResponse(HERE / "index.html", headers={"Cache-Control": "no-cache"})


@app.post("/session/new")
async def new_session(request: Request):
    """Start a fresh conversation. The old one is forgotten unless a run is still using it."""
    old_id = request.cookies.get(SESSION_COOKIE, "")
    old = conversations.get(old_id)
    if old and old.active_runs == 0:
        drop_conversation(old_id)
    prune_conversations()
    conversation = get_conversation("", "")
    response = JSONResponse({"session_id": conversation.id})
    set_session_cookie(response, conversation.id)
    return response


@app.get("/run")
async def run(request: Request, question: str, url: str = "", session_id: str = ""):
    """Stream deep-research progress as SSE. session_id is optional: the cookie is used by default."""
    prune_conversations()
    conversation = get_conversation(session_id, request.cookies.get(SESSION_COOKIE, ""))
    conversation.last_active = time.monotonic()
    conversation.active_runs += 1

    run_id = str(uuid.uuid4())
    run_contexts[run_id] = AgentContexts()
    conversation.run_ids.append(run_id)
    while len(conversation.run_ids) > MAX_RUNS_KEPT:
        run_contexts.pop(conversation.run_ids.popleft(), None)

    history = format_history(conversation)  # snapshot: only completed exchanges
    queue: asyncio.Queue = asyncio.Queue()
    hooks = PanelHooks(run_contexts[run_id], queue.put_nowait)

    async def work():
        try:
            report = await deep_research(question, hooks, start_url=url, history=history)
            if report != NO_FINDINGS:
                conversation.exchanges.append((question, report))
            queue.put_nowait({"type": "done", "markdown": report})
        except Exception as e:
            queue.put_nowait({
                "type": "error", "message": f"{type(e).__name__}: {str(e)[:500]}"
            })

    def run_finished(_task) -> None:
        conversation.active_runs -= 1
        conversation.last_active = time.monotonic()

    task = asyncio.create_task(work())
    task.add_done_callback(run_finished)

    async def events():
        try:
            yield f"data: {json.dumps({'type': 'start', 'run_id': run_id, 'session_id': conversation.id})}\n\n"
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, default=str)}\n\n"
                if event["type"] in ("done", "error"):
                    break
        finally:
            task.cancel()

    response = StreamingResponse(events(), media_type="text/event-stream")
    set_session_cookie(response, conversation.id)
    return response


@app.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest):
    """Blocking JSON API: runs the same Lead/Researchers/Writer workflow as /run and waits.

    Memory is keyed by body.session_id only (no cookie); omit it to start a new session."""
    prune_conversations()
    conversation = get_conversation(body.session_id or "", "")
    conversation.last_active = time.monotonic()
    conversation.active_runs += 1
    history = format_history(conversation)  # completed exchanges only
    hooks = ToolLogHooks(AgentContexts())  # throwaway panel data: not stored in run_contexts
    try:
        report = await deep_research(body.message, hooks, history=history)
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:500]}")
    finally:
        conversation.active_runs -= 1
        conversation.last_active = time.monotonic()
    if report != NO_FINDINGS:  # same rule as /run; clarifications are kept as history
        conversation.exchanges.append((body.message, report))
    return ChatResponse(response=report, session_id=conversation.id,
                        tool_calls=hooks.finished_calls())


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
