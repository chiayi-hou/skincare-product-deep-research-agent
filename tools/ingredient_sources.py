"""Ingredient background: PubChem PUG REST/PUG View and Wikipedia REST API."""

import re
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov"
WIKIPEDIA = "https://en.wikipedia.org"
WIKI_API = f"{WIKIPEDIA}/w/rest.php/v1"

# Replace with a real contact address before deploying.
HEADERS = {"User-Agent": "SkincareResearchAgent/0.1 (contact: ch4123@columbia.edu)"}
TIMEOUT = 30


def _get_json(url: str, params: dict | None = None) -> dict | list:
    response = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def get_pubchem_ingredient(name: str) -> dict:
    """Find a compound and return CID, basic properties and PubChem URL.

    Chemical properties do not establish clinical skincare effectiveness.
    """
    try:
        name_encoded = quote(name.strip(), safe="")
        ids = _get_json(f"{PUBCHEM}/rest/pug/compound/name/{name_encoded}/cids/JSON")
        cids = ids.get("IdentifierList", {}).get("CID", [])
        if not cids:
            return {"ingredient": name, "error": "No PubChem compound found"}
        cid = cids[0]
        fields = "MolecularFormula,MolecularWeight,IUPACName,XLogP"
        props = _get_json(
            f"{PUBCHEM}/rest/pug/compound/cid/{cid}/property/{fields}/JSON"
        )
        properties = props.get("PropertyTable", {}).get("Properties", [{}])[0]
        return {
            "ingredient": name,
            "cid": cid,
            "properties": properties,
            "source": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
            "note": "These are chemical properties, not proof of clinical efficacy.",
        }
    except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
        return {"ingredient": name, "error": str(exc)}


def _pubchem_section_text(sections: list, limit: int) -> list[dict]:
    found = []
    for section in sections:
        heading = section.get("TOCHeading", "")
        for item in section.get("Information", []):
            for part in item.get("Value", {}).get("StringWithMarkup", []):
                text = part.get("String", "").strip()
                if text and len(found) < limit:
                    found.append({"section": heading, "text": text[:1800]})
        if len(found) < limit:
            found.extend(_pubchem_section_text(section.get("Section", []), limit - len(found)))
        if len(found) >= limit:
            break
    return found


def get_pubchem_annotations(cid: int, heading: str = "Pharmacology and Biochemistry", limit: int = 6) -> dict:
    """Get PubChem descriptive annotations; availability varies by compound."""
    try:
        payload = _get_json(
            f"{PUBCHEM}/rest/pug_view/data/compound/{cid}/JSON",
            params={"heading": heading},
        )
        snippets = _pubchem_section_text(payload.get("Record", {}).get("Section", []), max(1, min(limit, 12)))
        return {"cid": cid, "heading": heading, "annotations": snippets,
                "source": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"}
    except (requests.RequestException, ValueError, KeyError) as exc:
        return {"cid": cid, "heading": heading, "annotations": [], "error": str(exc)}


def search_wikipedia(query: str, limit: int = 5) -> dict:
    """Search encyclopedia pages; search matches are not automatically relevant."""
    try:
        data = _get_json(f"{WIKI_API}/search/page", {"q": query, "limit": min(max(limit, 1), 10)})
        pages = [
            {"title": x.get("title"), "description": x.get("description"),
             "url": f"{WIKIPEDIA}/wiki/{quote(x.get('key', ''), safe='()_')}"}
            for x in data.get("pages", [])
        ]
        return {"query": query, "pages": pages}
    except (requests.RequestException, ValueError) as exc:
        return {"query": query, "error": str(exc), "pages": []}


def read_wikipedia(title: str, max_paragraphs: int = 12, max_links: int = 15) -> dict:
    """Read selected Wikipedia article and a limited number of linked pages."""
    try:
        key = quote(title.strip().replace(" ", "_"), safe="()")
        data = _get_json(f"{WIKI_API}/page/{key}/with_html")
        soup = BeautifulSoup(data.get("html", ""), "html.parser")
        for node in soup.select("script, style, sup.reference, ol.references, table, figure"):
            node.decompose()
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        paragraphs = [p for p in paragraphs if p]
        links, seen = [], set()
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if href.startswith("./"):
                href = "/wiki/" + href[2:]
            link = urljoin(WIKIPEDIA, href).split("#", 1)[0]
            if not link.startswith(f"{WIKIPEDIA}/wiki/") or link in seen:
                continue
            if ":" in link.split("/wiki/", 1)[1]:
                continue
            seen.add(link)
            links.append({"text": a.get_text(" ", strip=True), "url": link})
            if len(links) >= max_links:
                break
        return {"title": data.get("title", title),
                "updated": data.get("latest", {}).get("timestamp"),
                "paragraphs": paragraphs[:max_paragraphs], "links": links,
                "source": f"{WIKIPEDIA}/wiki/{key}",
                "note": "Wikipedia is background context, not clinical evidence."}
    except (requests.RequestException, ValueError) as exc:
        return {"title": title, "error": str(exc)}
