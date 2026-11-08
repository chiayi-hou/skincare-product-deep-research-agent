"""Clinical literature: PubMed ESearch/EFetch, PMC BioC full-text."""

import os
import re
import xml.etree.ElementTree as ET

import requests

from tools.common import HEADERS

NCBI = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
BIOC = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi"
TIMEOUT = 45

# OpenAlex is an optional fallback for PubMed/PMC research.
# Metadata search can work without a key; downloading OpenAlex-hosted TEI XML
# requires OPENALEX_API_KEY and counts against the OpenAlex API budget.
OPENALEX_WORKS = "https://api.openalex.org/works"
OPENALEX_CONTENT = "https://content.openalex.org/works"


def search_pubmed(query: str, limit: int = 5) -> dict:
    """Find PubMed identifiers by a biomedical search query."""
    try:
        response = requests.get(
            f"{NCBI}/esearch.fcgi",
            params={"db": "pubmed", "term": query, "retmode": "json",
                    "retmax": min(max(limit, 1), 10), "sort": "relevance", "tool": "SkincareResearchAgent"},
            headers=HEADERS, timeout=TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()["esearchresult"]
        return {"query": query, "total": int(result["count"]),
                "pmids": result["idlist"], "source": "https://pubmed.ncbi.nlm.nih.gov/"}
    except (requests.RequestException, ValueError, KeyError) as exc:
        return {"query": query, "error": str(exc), "pmids": []}


def fetch_pubmed_papers(pmids: list[str], max_abstract_chars: int = 2500) -> dict:
    """Get paper metadata, abstract, DOI, PMCID, and publication types."""
    if not pmids:
        return {"papers": [], "error": "No PMIDs supplied"}
    pmids = pmids[:10]
    try:
        response = requests.get(
            f"{NCBI}/efetch.fcgi",
            params={"db": "pubmed", "id": ",".join(pmids), "retmode": "xml",
                    "tool": "SkincareResearchAgent"},
            headers=HEADERS, timeout=TIMEOUT,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        papers = []
        for record in root.findall(".//PubmedArticle"):
            pmid = record.findtext(".//MedlineCitation/PMID")
            title_node = record.find(".//Article/ArticleTitle")
            title = "".join(title_node.itertext()).strip() if title_node is not None else ""
            abstract_parts = []
            for node in record.findall(".//Article/Abstract/AbstractText"):
                value = "".join(node.itertext()).strip()
                label = node.get("Label")
                if value:
                    abstract_parts.append(f"{label}: {value}" if label else value)
            identifiers = {x.get("IdType"): x.text for x in record.findall(".//PubmedData/ArticleIdList/ArticleId")}
            pub_types = [x.text for x in record.findall(".//PublicationTypeList/PublicationType") if x.text]
            papers.append({"pmid": pmid, "pmcid": identifiers.get("pmc"),
                           "doi": identifiers.get("doi"), "title": title,
                           "abstract": "\n".join(abstract_parts)[:max_abstract_chars],
                           "publication_types": pub_types,
                           "source": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"})
        return {"papers": papers}
    except (requests.RequestException, ET.ParseError, ValueError) as exc:
        return {"papers": [], "error": str(exc)}


def fetch_pmc_fulltext(pmcid: str, keyword: str = "", max_passages: int = 15) -> dict:
    """Read BioC full text and return selected passages, not entire paper to the LLM.

    With a keyword, prefer matching passages. Otherwise return first body passages.
    Section labels may be imperfect, and PMCID alone does not guarantee BioC access.
    """
    try:
        pmcid = pmcid.strip().upper()
        if not pmcid.startswith("PMC") or not pmcid[3:].isdigit():
            return {"pmcid": pmcid, "error": "Expected a PMCID such as PMC8389214"}
        response = requests.get(
            f"{BIOC}/BioC_json/{pmcid}/unicode", headers=HEADERS, timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        collections = data if isinstance(data, list) else [data]
        documents = [doc for collection in collections for doc in collection.get("documents", [])]
        if not documents:
            return {"pmcid": pmcid, "error": "No BioC full-text document available"}
        passages = documents[0].get("passages", [])
        candidates = [p for p in passages if p.get("infons", {}).get("section_type") not in
                      {"REF", "ACK_FUND", "COMP_INT"} and p.get("text", "").strip()]
        if keyword:
            terms = keyword.lower().split()
            candidates.sort(key=lambda p: sum(t in p.get("text", "").lower() for t in terms), reverse=True)
        return {"pmcid": pmcid, "total_passages": len(passages),
                "returned_passages": [
                    {"section": p.get("infons", {}).get("section_type", "UNKNOWN"),
                     "text": p.get("text", "")[:1800]}
                    for p in candidates[:min(max_passages, 30)]
                ],
                "source": f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/",
                "note": "Results are excerpts, not a clinical quality assessment."}
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        return {"pmcid": pmcid, "error": str(exc)}


def _openalex_auth() -> dict:
    key = os.getenv("OPENALEX_API_KEY", "").strip()
    return {"api_key": key} if key else {}


def _openalex_abstract(index: dict | None) -> str | None:
    """Reconstruct readable abstract text from OpenAlex inverted index."""
    if not index:
        return None
    positioned = [(pos, token) for token, locations in index.items()
                  for pos in locations]
    return " ".join(token for _, token in sorted(positioned)) or None


def _openalex_work_id(work_id: str) -> str | None:
    """Accept W123 or https://openalex.org/W123; reject arbitrary URLs."""
    value = work_id.strip().rstrip("/").split("/")[-1]
    return value if re.fullmatch(r"W\d+", value, flags=re.IGNORECASE) else None


def search_openalex(query: str, limit: int = 5) -> dict:
    """Backup literature search. Returns structured metadata and full-text availability.

    Search results do not imply clinical effectiveness. XML is NOT downloaded here.
    """
    query = query.strip()
    if not query:
        return {"query": query, "total": 0, "papers": [], "error": "Empty query"}
    try:
        params = {"search": query, "per_page": min(max(limit, 1), 10),
                  "select": ("id,display_name,publication_year,doi,cited_by_count,ids,"
                             "abstract_inverted_index,best_oa_location,primary_location,"
                             "has_content,content_urls")}
        params.update(_openalex_auth())
        response = requests.get(OPENALEX_WORKS, params=params,
                                headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
        papers = []
        for work in data.get("results", []):
            best_oa = work.get("best_oa_location") or {}
            location = work.get("primary_location") or {}
            content = work.get("has_content") or {}
            urls = work.get("content_urls") or {}
            papers.append({
                "openalex_id": work.get("id"),
                "title": work.get("display_name"),
                "year": work.get("publication_year"),
                "doi": work.get("doi"),
                "pmid": (work.get("ids") or {}).get("pmid"),
                "citation_count": work.get("cited_by_count"),
                "abstract": _openalex_abstract(work.get("abstract_inverted_index")),
                "journal": (location.get("source") or {}).get("display_name"),
                "open_access_url": best_oa.get("pdf_url") or best_oa.get("landing_page_url"),
                "license": best_oa.get("license"),
                "has_fulltext_xml": bool(content.get("grobid_xml")),
                "has_fulltext_pdf": bool(content.get("pdf")),
                "fulltext_xml_url": urls.get("grobid_xml"),
                "source": work.get("id"),
            })
        return {"query": query, "total": (data.get("meta") or {}).get("count", 0),
                "papers": papers, "source": "https://openalex.org/",
                "note": "Metadata search only. Full-text download requires an API key. "
                        "Citation count is not a study-quality measure."}
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        return {"query": query, "papers": [], "error": str(exc)}


def get_openalex_fulltext_availability(work_id: str) -> dict:
    """Check whether OpenAlex has XML/PDF full text without downloading it."""
    identifier = _openalex_work_id(work_id)
    if identifier is None:
        return {"work_id": work_id, "error": "Expected OpenAlex ID W123 or https://openalex.org/W123"}
    try:
        params = {"select": "id,display_name,has_content,content_urls,best_oa_location"}
        params.update(_openalex_auth())
        response = requests.get(f"{OPENALEX_WORKS}/{identifier}", params=params,
                                headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        work = response.json()
        content = work.get("has_content") or {}
        urls = work.get("content_urls") or {}
        return {"work_id": work.get("id"), "title": work.get("display_name"),
                "has_xml": bool(content.get("grobid_xml")),
                "has_pdf": bool(content.get("pdf")),
                "xml_url": urls.get("grobid_xml"), "pdf_url": urls.get("pdf"),
                "license": (work.get("best_oa_location") or {}).get("license")}
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        return {"work_id": identifier, "error": str(exc)}


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _extract_tei_sections(xml_bytes: bytes) -> list[dict]:
    """Read TEI sections, accommodating standard and legacy GROBID XML layouts."""
    root = ET.fromstring(xml_bytes)
    text_nodes = [node for node in root.iter() if _xml_local_name(node.tag) == "text"]
    if not text_nodes:
        return []
    sections = []
    for text_node in text_nodes:
        # Ignore front matter and bibliography: select body if available.
        bodies = [child for child in text_node if _xml_local_name(child.tag) == "body"]
        containers = bodies or [text_node]
        for container in containers:
            for div in container.iter():
                if _xml_local_name(div.tag) != "div":
                    continue
                head = next((" ".join(el.itertext()).strip() for el in div
                             if _xml_local_name(el.tag) == "head"), "")
                for paragraph in div.iter():
                    if _xml_local_name(paragraph.tag) != "p":
                        continue
                    # Avoid duplicated nested paragraphs.
                    content = " ".join(" ".join(paragraph.itertext()).split())
                    if content:
                        sections.append({"section": head or "BODY", "text": content})
            # Some TEI bodies consist of <p> elements without <div>.
            if not any(_xml_local_name(n.tag) == "div" for n in container.iter()):
                for paragraph in container.iter():
                    if _xml_local_name(paragraph.tag) == "p":
                        content = " ".join(" ".join(paragraph.itertext()).split())
                        if content:
                            sections.append({"section": "BODY", "text": content})
    return sections


def fetch_openalex_fulltext(work_id: str, keyword: str = "",
                            max_passages: int = 15) -> dict:
    """Read limited TEI XML excerpts for an OpenAlex work, if accessible.

    Uses availability metadata first. Only downloads XML when available and when
    OPENALEX_API_KEY is set. Do not call for every search result: each download
    counts against the OpenAlex usage budget. XML may contain extraction errors.
    """
    identifier = _openalex_work_id(work_id)
    if identifier is None:
        return {"work_id": work_id, "error": "Invalid OpenAlex work ID"}
    if not os.getenv("OPENALEX_API_KEY", "").strip():
        return {"work_id": identifier, "error": "Set OPENALEX_API_KEY to download full text"}
    availability = get_openalex_fulltext_availability(identifier)
    if availability.get("error"):
        return availability
    if not availability.get("has_xml"):
        return {"work_id": identifier, "available": False,
                "pdf_available": availability.get("has_pdf", False),
                "error": "No OpenAlex GROBID XML available for this work"}
    # Do not trust remote URLs from metadata as arbitrary download targets.
    url = f"{OPENALEX_CONTENT}/{identifier}.grobid-xml"
    try:
        # Stream to avoid unbounded response memory for unusually large XML files.
        with requests.get(url, params=_openalex_auth(), headers=HEADERS,
                          timeout=60, stream=True) as response:
            response.raise_for_status()
            chunks = []
            size = 0
            for chunk in response.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > 8 * 1024 * 1024:
                    return {"work_id": identifier, "error": "XML exceeds 8 MB safety limit"}
                chunks.append(chunk)
        sections = _extract_tei_sections(b"".join(chunks))
        if not sections:
            return {"work_id": identifier, "error": "No readable body paragraphs in XML"}
        if keyword.strip():
            terms = keyword.lower().split()
            sections.sort(key=lambda p: sum(term in p["text"].lower() for term in terms),
                          reverse=True)
        return {"work_id": identifier, "available": True,
                "total_passages": len(sections),
                "returned_passages": [
                    {"section": p["section"], "text": p["text"][:1800]}
                    for p in sections[:min(max(max_passages, 1), 30)]
                ],
                "source": f"https://openalex.org/{identifier}",
                "license": availability.get("license"),
                "note": "Machine-extracted XML excerpts; not a full critical appraisal. "
                        "Respect the original article license."}
    except (requests.RequestException, ET.ParseError, ValueError, TypeError) as exc:
        return {"work_id": identifier, "error": str(exc)}
