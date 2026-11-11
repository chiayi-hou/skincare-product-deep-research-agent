# Skincare, Beyond the Hype

An evidence-based skincare exploration agent built for IEOR 4570 Project 2 (Deep Research path).

Deploy url: [https://student-planning-agent-git-828235103430.europe-west1.run.app](https://skincare-product-deep-research-agent-git-828235103430.europe-west1.run.app/)

## Project overview

Skincare products often advertise benefits such as long-lasting hydration, wrinkle reduction, or brighter skin. People who care about their skin may not have the time to check product ingredient lists, read clinical papers, and investigate possible adverse reactions. This application helps users explore what a skincare product contains, what published research does and does not support, and what safety information is available.

The intended users are everyday skincare consumers who want understandable, source-linked answers rather than unsupported marketing claims. The agent is a research assistant, not a medical diagnostic service.

The central exploration question is: **How well do publicly available product records, chemical information, clinical literature, and adverse-event reports support specific claims about skincare ingredients and commercial products?**

## What users can ask

Users can enter a product name, ask what its ingredients do, question a marketed benefit, or ask about possible irritation and adverse-event reports. The interface includes a Chat view, an Activity Panel showing research progress, clickable source citations, and limited session conversation history. It also explains the project's purpose and how to use the agent.

When the user leaves out an essential product or ingredient name and the conversation does not resolve it, the Lead is instructed to request clarification before researching. Product records and scientific studies are not interchangeable: evidence for an ingredient does not automatically prove that a finished formulation works.

## Data sources and access

The agent queries external sources at runtime through Python tool wrappers in `tools/`. It does not rely on a static, pretrained summary of the products.

| Source | What the agent retrieves | Code / tools |
| --- | --- | --- |
| Open Beauty Facts | Product records, barcodes, raw ingredient/INCI lists | `tools/product_sources.py`: `beauty_search`, `beauty_product` |
| PubChem | Chemical identity, compound IDs, properties and annotations | `tools/ingredient_sources.py`: `lookup_ingredient`, `ingredient_annotations` |
| Wikipedia | General ingredient background and terminology | `tools/ingredient_sources.py`: `wiki_search`, `wiki_read` |
| PubMed | Biomedical literature search, abstracts, publication types, PMID and DOI | `tools/clinical_sources.py`: `pubmed_search`, `pubmed_papers` |
| PubMed Central (PMC) | Relevant available full-text excerpts | `tools/clinical_sources.py`: `pmc_fulltext` |
| OpenAlex | Backup paper metadata and, where available and justified, full text | `tools/clinical_sources.py`: `openalex_search`, `openalex_xml_availability`, `openalex_xml_read` |
| openFDA cosmetic adverse events | Reported adverse-event records and product-name matches | `tools/product_sources.py`: `fda_reports` |

Open Beauty Facts is crowdsourced and can be incomplete or outdated. Clinical studies may test different formulations or outcomes from the user's product. FDA adverse-event reports are not proof of causation or measures of incidence. Missing search results do not prove that no product, paper, or report exists.

To reproduce access, install project dependencies, configure the Google Cloud / Vertex AI credentials needed for the deployed models, and provide an OpenAlex API key if using its optional full-text capability. Other API-specific settings, if any, are described in the source modules. [VERIFY AND ADD ANY ADDITIONAL CONFIGURATION NEEDED FROM THE ACTUAL REPOSITORY.]

## Deep Research architecture

1. The **Lead** interprets the request, clarifies ambiguous targets, and delegates relevant subtasks.
2. **Product, Ingredient, and Clinical Researchers** investigate distinct questions in fresh contexts. Independent tasks can execute concurrently.
3. The Lead reviews their findings, assigns targeted follow-up work if necessary, and stops when the question is sufficiently answered or the research limit is reached.
4. The **Writer** produces a readable report using the current findings, including inline Markdown source links and explicit evidence limitations.

The implementation limits a run to six researchers. The Lead runs with `max_turns=12`, and individual Researchers run with `max_turns=14`. PubMed is the first choice for clinical evidence, PMC provides relevant full text when available, and OpenAlex is a backup. The optional OpenAlex XML download has additional guards.

The frontend streams progress through `GET /run` using server-sent events and displays activity in a separate panel. The app also provides `POST /chat`, which returns the Project 1-compatible JSON response shape (`response`, `session_id`, `tool_calls`). Tool-call records include `agent`, `name`, `args`, and `result`; this allows callers to inspect actions taken by the Lead and specialist Researchers. Large tool results may be truncated in the JSON log, with truncation explicitly marked. Conversation history is maintained for recent exchanges in an in-memory session store.

## Three sample queries for the grader

The three cases demonstrate product lookup, assessment of marketed efficacy claims, and ingredient/product safety research. All three model-only baselines were generated with `vertex_ai/gemini-3.5-flash` on November 10, 2026, using a single-turn user message, no system prompt, no tools, and no conversation history. The agent transcripts are actual saved outputs. The comparisons describe observable differences and acknowledge unverified claims; they do not establish that every statement in the retrieved answers is factually correct.

### Query 1: Understanding a product's ingredients

**Prompt:** What's in Clinique Moisture Surge 100H? I don't really understand skincare ingredients. Can you explain what they do?

**Expected answer:** Find the specific Clinique Moisture Surge 100H product record and explain the actual listed ingredients in accessible language, grouped by function. Avoid treating ingredient properties as proof of the finished product's performance, and acknowledge missing or incomplete product information.

**Source / API endpoints:** Open Beauty Facts product barcode `0192333066942` (`beauty_search`, `beauty_product`); PubChem compound records including CID `753`, `7896`, and `73984` (`lookup_ingredient`); Wikipedia background pages for sodium hyaluronate and aloe (`wiki_search`, `wiki_read`). The actual response also references PubChem CID `1738118`, while acknowledging acetyl glucosamine was not confirmed in the product label.

**Model-only baseline (same model; no tools; no system prompt):**

<details>
<summary>Expand full no-tools baseline response for Query 1</summary>

Skincare ingredient lists can look like high school chemistry homework, so it is completely normal to find them confusing! 

**Clinique Moisture Surge 100H** is a lightweight, gel-based moisturizer. Its main goal is to flood your skin with hydration and lock it in so it doesn't evaporate. 

To make it easy to understand, we can break the ingredients down into three categories: **The Hydrators** (the water-givers), **The Lock-it-ins** (the water-keepers), and **The Boosters** (the helpers).

Here is what is actually in that pink jar and what it does for your skin:

---

### 1. The Hydrators (Putting water *into* your skin)
These ingredients act like tiny, thirsty sponges that pull water into your skin.

*   **Hyaluronic Acid:** You have probably heard of this one! It is a naturally occurring molecule in our bodies that can hold up to 1,000 times its weight in water. 
    *   *What it does:* It acts like a magnet, drawing moisture from the air and deep within your skin to the surface, making your skin look plump and dewy.
*   **Activated Aloe Water:** This is pure water infused with Aloe Vera leaf extract, which has been "charged" by scientists to have positive and negative ions.
    *   *What it does:* This charge helps your skin absorb the water much better than regular water. 
*   **Aloe Bio-ferment:** Clinique takes the aloe plant and ferments it with lactobacillus (a friendly bacteria, similar to what's in yogurt). 
    *   *What it does:* Fermenting breaks the ingredients down into tiny pieces so they can penetrate deeper into your skin. It feeds your skin nutrients and helps it retain moisture over time.

---

### 2. The Lock-it-ins (Keeping the water from escaping)
If you just put water on your face, it will evaporate, leaving your skin drier than before. You need ingredients to lock it in.

*   **Dimethicone:** This is a very common cosmetic silicone. 
    *   *What it does:* It gives the moisturizer its silky, slippery "gel" feel. It sits on top of the skin to create a breathable, protective barrier, preventing moisture from escaping into the air.
*   **Squalane:** A lightweight moisturizing oil (derived from plants) that mimics your skin's natural oils.
    *   *What it does:* It softens and smooths the skin without feeling greasy or clogging pores.

---

### 3. The Boosters (Helping everything work better)
These ingredients help the hydrators do their job and keep your skin calm.

*   **Caffeine:** Just like coffee wakes you up, caffeine wakes up your skin.
    *   *What it does:* In this formula, caffeine acts as a "pump." It stimulates your skin's natural circulation, helping to pump moisture from the deeper layers of your skin up to the surface.
*   **Green Tea Extract (Camellia Sinensis):** 
    *   *What it does:* A powerful antioxidant that calms down redness, soothes irritation, and protects your skin from environmental damage (like pollution).

---

### The "Water Tank" Analogy: How it all works together

Imagine your skin is a dry sponge. 
1. **Hyaluronic Acid and Aloe Water** pour water into the sponge, filling it up.
2. **Caffeine** squeezes the sponge slightly to make sure the water is distributed evenly.
3. **Dimethicone and Squalane** put a plastic wrap over the sponge so the water can't evaporate.

### Is it right for you?
Because this formula is a **gel-cream** (made mostly of water and light silicones rather than heavy, thick oils), it is excellent for:
*   **Oily or Combination skin:** It hydrates deeply without feeling heavy or greasy.
*   **Dehydrated skin:** It is perfect for skin that feels tight and lacks water.
*   **Warm weather:** It feels cool and refreshing on the skin. 

*(Note: If you have extremely dry, flaky skin, you might need a cream with more heavy oils, but for most skin types, this formula is a great daily hydrator!)*

</details>

**Our agent's answer (saved test output):**

<details>
<summary>Expand full agent response for Query 1</summary>

### Direct Answer

Clinique Moisture Surge 100H Auto-Replenishing Hydrator is a gel-cream moisturizer formulated primarily with water, lightweight silicones, water-binding hydrators (humectants), and skin-soothing botanical ferments (Source: [Open Beauty Facts Product Record](https://world.openbeautyfacts.org/product/0192333066942)). In simple terms, it works by pulling moisture into the outer layers of your skin like a sponge and locking it in with a light, non-greasy protective seal.

---

### Key Ingredients and What They Do

The ingredients in this formula can be broken down into three main categories:

#### 1. Hydrating & Moisture-Binding Ingredients (Humectants)

Humectants act like water magnets. They draw moisture from the air or deeper skin layers into the surface to keep the skin looking plump and hydrated.

- **Glycerin:** A highly effective, standard skincare ingredient that binds moisture to the skin's surface to maintain hydration and support the skin barrier (Source: [PubChem CID 753](https://pubchem.ncbi.nlm.nih.gov/compound/753)).
- **Butylene Glycol:** A lightweight liquid that helps the skin retain moisture. It also serves as a solvent, helping the other ingredients mix together and absorb more effectively (Source: [PubChem CID 7896](https://pubchem.ncbi.nlm.nih.gov/compound/7896)).
- **Sodium Hyaluronate:** A salt form of hyaluronic acid. It is highly water-loving, forming a light gel-like layer on the skin to temporarily smooth texture and plump up fine lines (Source: [Wikipedia: Sodium hyaluronate](https://en.wikipedia.org/wiki/Sodium_hyaluronate)).
- **Hydrolyzed Sodium Hyaluronate:** Hyaluronic acid that has been broken down into smaller pieces. Because of its smaller size, it can penetrate past the skin's surface more easily to deliver hydration deeper into the upper layers of the skin (Source: [Wikipedia: Sodium hyaluronate](https://en.wikipedia.org/wiki/Sodium_hyaluronate)).
- **Hydroxyethyl Urea:** A derivative of urea that binds water inside the skin's outer layer to boost hydration without the skin irritation that regular urea can sometimes cause (Source: [PubChem CID 73984](https://pubchem.ncbi.nlm.nih.gov/compound/73984)).

#### 2. Softening & Moisture-Locking Ingredients (Emollients and Occlusives)

Once humectants pull moisture into the skin, these ingredients seal it in to keep it from evaporating.

- **Dimethicone:** A common silicone polymer that creates a breathable, water-resistant barrier. It prevents water loss and leaves the skin feeling soft and smooth without being thick or greasy.
- **Trisiloxane:** A very lightweight silicone that helps the moisturizer spread easily across your face and evaporates quickly, giving the product its weightless gel feel.

#### 3. Botanicals, Ferments, and Antioxidants

These ingredients help soothe the skin, support its defensive barrier, and provide environmental protection.

- **Aloe Barbadensis Leaf Water:** Water extracted from the aloe vera plant, rich in vitamins and complex sugars. It serves as a cooling, soothing base that leaves a light moisture film on the skin (Source: [Wikipedia: Aloe vera](https://en.wikipedia.org/wiki/Aloe_vera)).
- **Lactobacillus Ferment Lysate & Saccharomyces Lysate Extract:** Postbiotics derived from fermented beneficial bacteria and yeast. They provide amino acids and peptides that help soothe irritated skin and support a strong, healthy skin barrier.
- **Caffeine:** Included for its antioxidant and temporary skin-firming benefits. It can help support microcirculation to briefly reduce the appearance of puffiness.
- **Camellia Sinensis (Green Tea) Leaf Extract:** A rich source of natural antioxidants (polyphenols) that help defend the skin from environmental stressors like UV rays and pollution, while offering extra soothing benefits.
- **Acetyl Glucosamine:** A skin-brightening sugar that acts as a raw building block for the skin's natural hyaluronic acid synthesis (Sources: [PubChem CID 1738118](https://pubchem.ncbi.nlm.nih.gov/compound/1738118), [Wikipedia: N-Acetylglucosamine](https://en.wikipedia.org/wiki/N-Acetylglucosamine)). *Note: While analyzed for its properties, this specific ingredient is not listed on the verified product label for this formulation (Source: [Open Beauty Facts Product Record](https://world.openbeautyfacts.org/product/0192333066942)).*

---

### Limitations and Missing Evidence

- **No Independent Clinical Evidence:** Database searches in PubMed and OpenAlex for "Clinique Moisture Surge 100H" or its proprietary "Aloe Bio-ferment + HA Complex" yielded **0 clinical trials or peer-reviewed studies**.
- **Unverified Hydration Claims:** The "100-hour hydration" claim is proprietary to the manufacturer. While brands often conduct internal testing on consumers to measure skin moisture over time, these studies have not been published in independent, peer-reviewed scientific literature.
- **Ingredients vs. Finished Product:** Although individual ingredients like glycerin and sodium hyaluronate have excellent scientific evidence for hydrating skin, their actual performance in this specific product depends heavily on their overall concentration and the total formulation.

---

### Sources

- [Open Beauty Facts Product Record](https://world.openbeautyfacts.org/product/0192333066942)
- [Wikipedia: Aloe vera](https://en.wikipedia.org/wiki/Aloe_vera)
- [Wikipedia: Sodium hyaluronate](https://en.wikipedia.org/wiki/Sodium_hyaluronate)
- [Wikipedia: N-Acetylglucosamine](https://en.wikipedia.org/wiki/N-Acetylglucosamine)
- [PubChem CID 753 (Glycerin)](https://pubchem.ncbi.nlm.nih.gov/compound/753)
- [PubChem CID 7896 (Butylene Glycol)](https://pubchem.ncbi.nlm.nih.gov/compound/7896)
- [PubChem CID 73984 (Hydroxyethyl Urea)](https://pubchem.ncbi.nlm.nih.gov/compound/73984)
- [PubChem CID 1738118 (Acetyl Glucosamine)](https://pubchem.ncbi.nlm.nih.gov/compound/1738118)

</details>

**Comparison:** The baseline gives a fluent consumer-friendly explanation, but it supplies formulation-specific details and detailed claims about "activated aloe water," fermentation, and caffeine without checking a product database or citing sources. Our agent instead retrieves a specific Open Beauty Facts product record and links ingredient explanations to PubChem and background sources. It also distinguishes ingredient-level evidence from the finished product's unverified 100-hour claim. However, the agent still includes acetyl glucosamine even though it says this ingredient is not on the verified label, and several mechanism or safety-benefit statements rely only on chemical/background sources or lack direct citations. The tool-enabled answer is more traceable, not error-free.

### Query 2: Marketing claim versus evidence

**Prompt:** Olay Retinol24 says its retinol and vitamin B3 can help reduce wrinkles and dark spots. Does that stuff actually work, or is it just marketing?

**Expected answer:** Investigate the marketed product and the relevant scientific literature. Separate human clinical evidence on retinoids or niacinamide from trials of particular multi-ingredient products, and from independently verified tests of this exact commercial formulation. Clearly note absent or indirect evidence rather than making universal claims.

**Sources:** Open Beauty Facts records for the Olay Retinol24 Night Moisturiser (`https://world.openbeautyfacts.org/product/4902430917872`) and Night Serum (`https://world.openbeautyfacts.org/product/4902430917896`), plus clinical articles retrieved through `pubmed_search` and `pubmed_papers`, including PubMed identifiers `27391637` and `20374604` in the saved response. The final comparison should report what was actually returned by the test run and distinguish formulation-specific from indirect evidence.

**Model-only baseline (same model; no tools; no system prompt):**

<details>
<summary>Expand full no-tools baseline response for Query 2</summary>

The short answer is: **Yes, it actually works.** It is not just marketing hype. 

The combination of **Retinol** and **Vitamin B3 (Niacinamide)** is one of the most scientifically backed duos in dermatology for treating wrinkles and dark spots. 

However, because this is an over-the-counter (OTC) drugstore product, there are some caveats regarding *how well* it works compared to prescription treatments, and how long it takes to see results.

Here is a breakdown of the science, why this specific formulation works, and what you should realistically expect.

---

### 1. The Science: Why the Ingredients Work

Olay Retinol24 relies on two heavy-hitters that dermatologists love:

#### **Retinol (Vitamin A)**
*   **What it does for wrinkles:** Retinol penetrates deep into the skin to stimulate collagen and elastin production (which plumps the skin and reduces fine lines). It also speeds up cell turnover, meaning dead skin cells shed faster, revealing smoother skin.
*   **What it does for dark spots:** By accelerating cell turnover, retinol helps "shed" hyperpigmented skin cells faster, fading dark spots and evening out skin tone.

#### **Vitamin B3 (Niacinamide)**
*   **What it does for dark spots:** Niacinamide prevents pigment (melanin) from transferring to the surface of your skin cells. It is highly effective at fading dark spots and acne scars.
*   **What it does for wrinkles & irritation:** It strengthens the skin barrier, boosts hydration, and reduces redness. 

#### **The Synergy (Why they are paired together)**
Retinol is notoriously irritating and drying. Niacinamide (Vitamin B3) is highly soothing and anti-inflammatory. By combining them, **Vitamin B3 helps buffer the skin against the harsh, drying side effects of the retinol.**

---

### 2. Is Olay’s Formulation Good?

Olay Retinol24 is highly regarded by cosmetic chemists and dermatologists for several reasons:

*   **Fragrance-Free:** The standard Retinol24 cream is fragrance-free. This is crucial because fragrance combined with retinol is a recipe for skin irritation.
*   **Bio-available Retinoid Complex:** Olay uses a proprietary blend of pure retinol and *retinyl propionate* (a gentler retinoid derivative). This allows the product to penetrate the skin effectively without causing the massive peeling or redness often associated with prescription retinoids.
*   **Affordability & Accessibility:** It delivers high-quality, stable ingredients at a drugstore price point.

---

### 3. The Catch: Marketing vs. Reality

While the product works, marketing campaigns often exaggerate *how fast* and *how dramatically* it works. Here is the reality check:

*   **Olay doesn't disclose the percentage:** Olay does not list the exact percentage of retinol in the product (it is estimated to be around 0.1% to 0.3%). This is standard for drugstore brands. It is strong enough to work, but it is much weaker than prescription-strength Retin-A (tretinoin). 
*   **The Timeline:** Marketing might promise results in "24 hours" (which is mostly just temporary hydration). In reality:
    *   **Moisture & Glow:** 1 to 7 days.
    *   **Dark Spots fading:** 4 to 8 weeks.
    *   **Fine Lines & Wrinkles:** 12 to 24 weeks (3 to 6 months) of consistent use.
*   **Packaging Issue:** The Olay Retinol24 cream comes in a jar. Retinol degrades when exposed to air and light. Every time you open the jar, the product loses a tiny bit of its potency. *Tip: If you buy this line, look for the Olay Retinol24 Max Serum (which comes in a dropper/pump) rather than the jar cream, as it keeps the retinol stable for longer.*

---

### How to use it for best results:

1.  **Use it at night:** Retinol is degraded by sunlight, so it should only be applied before bed.
2.  **Wear sunscreen during the day:** Retinol makes your skin more sensitive to the sun. If you don't wear sunscreen (SPF 30+), the sun will reverse all the progress you make on your wrinkles and dark spots.
3.  **Ease into it:** Start by using it 2 to 3 nights a week, and gradually increase to every night once your skin tolerates it.

### The Verdict
Olay Retinol24 is **not** just marketing. It is a well-formulated, effective entry-level retinoid product. It will help fade dark spots and smooth fine lines, but you must be patient and use it consistently for at least two to three months to see real structural changes in your skin.

</details>

**Our agent's answer (saved test output):**

<details>
<summary>Expand full agent response for Query 2</summary>

### Direct Answer

Whether Olay Retinol24 "actually works" depends on whether you look at the **finished formulation** or the **individual active ingredients**:

- **The Marketing / Finished Product:** There are **no published, peer-reviewed clinical trials** evaluating the exact commercial "Olay Retinol24" finished formulations (such as the night moisturizer or serums) to prove their specific real-world efficacy.
- **The Science / Active Ingredients:** The product relies on a dual-retinoid blend (retinol and retinyl propionate) combined with vitamin B3 (niacinamide). General clinical and dermatological research strongly supports the ability of these individual ingredients to reduce wrinkles and fade dark spots.

---

### Supporting Findings

#### 1. Product Formulations and Key Actives

Based on ingredient databases, several products in the Olay Retinol24 line utilize the same core active ingredients:

- **Olay Regenerist Retinol 24 Night Moisturiser:** Contains water, dimethicone, glycerin, niacinamide (vitamin B3), retinyl propionate, retinol, and palmitoyl pentapeptide-4 (Source: [Open Beauty Facts - Olay Regenerist Retinol 24 Night Moisturiser](https://world.openbeautyfacts.org/product/4902430917872)).
- **Olay Retinol 24 Night Serum:** Contains a similar base with niacinamide, retinyl propionate, retinol, and palmitoyl pentapeptide-4 (Source: [Open Beauty Facts - Olay Retinol 24 Night Serum](https://world.openbeautyfacts.org/product/4902430917896)).
- **Olay Regenerist Retinol 24 Max Night Serum:** Contains niacinamide, retinyl propionate, and retinol, though the quantitative difference in active concentrations is not publicly disclosed (Source: [Open Beauty Facts - Olay Regenerist Retinol 24 Max Night Serum](https://world.openbeautyfacts.org/product/4987176193070)).

#### 2. Chemical Properties and Proposed Mechanisms

The active ingredients in Olay Retinol24 are well-documented to target aging and hyperpigmentation through distinct pathways:

- **Retinol:** A vitamin A alcohol (Source: [PubChem CID 445354](https://pubchem.ncbi.nlm.nih.gov/compound/445354)) that converts into retinoic acid in the skin. It binds to cellular receptors to regulate gene expression, promote epidermal cell turnover, and stimulate collagen synthesis, which helps minimize fine lines and wrinkles.
- **Retinyl Propionate:** A vitamin A ester (Source: [PubChem CID 6394572](https://pubchem.ncbi.nlm.nih.gov/compound/6394572)) that serves as a more stable, slower-converting retinoid. It is often utilized in cosmetic formulas to minimize irritation.
- **Niacinamide (Vitamin B3):** A cellular precursor (Source: [PubChem CID 936](https://pubchem.ncbi.nlm.nih.gov/compound/936)) that reduces the transfer of pigment (melanosomes) to surface skin cells to fade dark spots. It also strengthens the skin's barrier and helps mitigate the irritation, dryness, and redness typically caused by retinoids.

#### 3. Indirect Clinical Evidence on Retinol & Niacinamide

While Olay Retinol24 itself has not been directly studied in published trials, clinical studies on similar ingredient combinations support their anti-aging benefits:

- **Retinol + Niacinamide Combination:** A 10-week, open-label human study evaluated a nightly cream combining 0.5% retinol with 4.4% niacinamide (along with resveratrol and hexylresorcinol) (Source: [PMID: 27391637](https://pubmed.ncbi.nlm.nih.gov/27391637/)). Researchers observed statistically significant improvements in skin smoothness and radiance by week 2, and in wrinkles, hyperpigmentation, and skin tone evenness by week 4 (Source: [PMID: 27391637](https://pubmed.ncbi.nlm.nih.gov/27391637/)).
- **Expert Consensus:** An international consensus review noted that retinoids are universally recognized for anti-aging efficacy, while niacinamide is widely recommended for all skin types to support skin barrier maintenance and combat aging concerns (Source: [PMID: 38206152](https://pubmed.ncbi.nlm.nih.gov/38206152/)).

#### 4. Manufacturer (Procter & Gamble) Research on Related Blends

Although Procter & Gamble (Olay's parent company) has not published clinical trials on the exact *triple* combination of niacinamide, retinol, and retinyl propionate, they have published research on closely related ingredient blends:

- **Niacinamide + Retinyl Propionate Clinical Trial:** A randomized, controlled clinical study compared a cosmetic regimen containing 5% niacinamide, peptides, and 0.3% retinyl propionate (without retinol) to a prescription 0.02% tretinoin cream (Source: [PMID: 20374604](https://doi.org/10.1111/j.1365-2133.2009.09436.x)). After 8 weeks, the cosmetic regimen significantly improved the appearance of wrinkles relative to tretinoin, with comparable results at 24 weeks and significantly fewer side effects (Source: [PMID: 20374604](https://doi.org/10.1111/j.1365-2133.2009.09436.x)).
- **In Vitro Synergy:** An laboratory (*in vitro*) cell study found that combining retinyl propionate with niacinamide and carob (*Ceratonia siliqua*) extract generated a higher retinoid response (receptor activation and gene expression) than using retinyl propionate alone (Source: [PMID: 33048363](https://doi.org/10.1111/ics.12669)).

---

### Uncertainties, Limitations, and Missing Evidence

- **No Direct Testing:** There is a lack of independent clinical trials evaluating Olay Retinol24 finished products. Efficacy results from studies on other formulations (like those containing 0.5% retinol) cannot be directly applied to Olay Retinol24 because the exact concentrations of retinol, retinyl propionate, and niacinamide in Olay's formulas are proprietary trade secrets and remain undisclosed (Source: [Open Beauty Facts - Olay Regenerist Retinol 24 Night Moisturiser](https://world.openbeautyfacts.org/product/4902430917872)).
- **In Vitro vs. In Vivo:** Laboratory cell studies (such as the retinoid synergy study) do not guarantee identical results on living, human skin.
- **Safety Concerns:** No adverse event reports specifically naming "Olay Retinol24" were found in the openFDA database, and crowdsourced product databases contain no safety logs (Source: [openFDA Cosmetic Events API](https://open.fda.gov/apis/cosmetic/event/)). However, general Olay brand search results show occasional spontaneous reports of localized skin irritation (erythema, rash, burning), which are common, unverified side effects associated with standard topical retinoid use (Source: [openFDA Cosmetic Events API](https://open.fda.gov/apis/cosmetic/event/)).

---

### Sources

- **Product Records:**
  - [Open Beauty Facts - Olay Regenerist Retinol 24 Night Moisturiser 50g](https://world.openbeautyfacts.org/product/4902430917872)
  - [Open Beauty Facts - Olay Retinol 24 Night Serum](https://world.openbeautyfacts.org/product/4902430917896)
  - [Open Beauty Facts - Olay Regenerist Retinol 24 Max Night Serum 30mL](https://world.openbeautyfacts.org/product/4987176193070)
- **Chemical Data:**
  - [PubChem CID 445354 (Retinol)](https://pubchem.ncbi.nlm.nih.gov/compound/445354)
  - [PubChem CID 6394572 (Retinyl Propionate)](https://pubchem.ncbi.nlm.nih.gov/compound/6394572)
  - [PubChem CID 936 (Niacinamide)](https://pubchem.ncbi.nlm.nih.gov/compound/936)
- **Scientific Studies:**
  - [PMID: 27391637 - Efficacy and Tolerability of a Skin Brightening/Anti-Aging Cosmeceutical Containing Retinol 0.5%, Niacinamide, Hexylresorcinol, and Resveratrol](https://pubmed.ncbi.nlm.nih.gov/27391637/)
  - [PMID: 38206152 - International Consensus on Anti-Aging Dermocosmetics and Skin Care for Clinical Practice](https://pubmed.ncbi.nlm.nih.gov/38206152/)
  - [PMID: 20374604 - Wrinkle reduction benefits of a cosmetic niacinamide/peptide/retinyl propionate product regimen vs. tretinoin](https://doi.org/10.1111/j.1365-2133.2009.09436.x)
  - [PMID: 33048363 - Enhanced retinoid response by retinyl propionate with niacinamide in vitro](https://doi.org/10.1111/ics.12669)
- **Safety Databases:**
  - [openFDA Cosmetic Events API](https://open.fda.gov/apis/cosmetic/event/)

</details>

**Comparison:** The no-tools baseline confidently concludes that Olay Retinol24 works and gives specific retinol concentration estimates, result timelines, and packaging advice without cited data. The agent retrieves specific Olay product records and names human studies (e.g., PMID `27391637` and `20374604`), differentiating evidence for similar ingredient combinations from direct testing of the commercial product. It appropriately notes unknown concentrations and limited finished-product evidence. Some of the agent's ingredient mechanism statements and broad claims about the absence of trials still need independent verification, so citations should not be mistaken for conclusive product-level proof.

### Query 3: Product safety and potential irritation

**Prompt:** I've heard retinol can irritate your skin. Is Olay Retinol24 actually safe to use? Could any of its ingredients cause problems?

**Expected answer:** Identify the correct Olay Retinol24 formulation and discuss potential irritation and sensitization risks from retinoids and other listed ingredients. Distinguish ingredient-level clinical evidence from evidence about the finished product. Report any product-matched FDA adverse-event records cautiously, without implying that reports establish causation or incidence rates. State limitations when exact concentrations, formulations, or matching records cannot be verified.

**Sources / API endpoints used in the saved agent answer:**

- Open Beauty Facts, Olay Regenerist Retinol 24 Night Moisturiser, barcode `4902430917872`: `https://world.openbeautyfacts.org/product/4902430917872`, via `beauty_search` / `beauty_product`.
- PubChem compound records: Retinol CID `445354`, Retinyl Propionate CID `6394572`, Niacinamide CID `936`, via `lookup_ingredient`.
- PubMed articles: PMID `28733999`, `38628085`, `17121065`, and `23007255`, via `pubmed_search` / `pubmed_papers`.
- openFDA cosmetic event data: `https://open.fda.gov/apis/cosmetic/event/`, via `fda_reports`.

**Model-only baseline (same model; no tools; no system prompt):**

<details>
<summary>Expand full no-tools baseline response for Query 3</summary>

Yes, **Olay Regenerist Retinol 24 Night Moisturizer** is generally considered safe for the vast majority of users. In fact, it was specifically formulated to address the exact concern you have: **retinol irritation.** 

Olay designed this product to deliver the anti-aging benefits of retinol while minimizing the redness, dryness, and peeling (often called "retinization") that traditional retinoids cause.

However, because it contains active ingredients, there are still potential side effects and specific ingredients that could cause issues for certain skin types. Here is a detailed breakdown of how it works, what ingredients to watch out for, and how to use it safely.

---

### Why Olay Retinol 24 is Gentler Than Other Retinols

Olay uses a specific formulation strategy to keep the product stable and gentle:

1. **The Retinoid Blend (Retinol + Retinyl Propionate):** Instead of using a high concentration of pure retinol, Olay uses a blend of pure Retinol and **Retinyl Propionate** (a retinol ester). Retinyl propionate is a milder, more stable derivative. It penetrates the skin slowly, which significantly reduces the risk of sudden irritation.
2. **Niacinamide (Vitamin B3):** This is one of the main ingredients in the formula. Niacinamide is a powerful anti-inflammatory that strengthens the skin barrier and hydrates the skin. It acts as a "buffer," actively soothing the skin while the retinol does its work.
3. **Fragrance-Free and Dye-Free:** (Note: This applies to the standard *Olay Retinol 24* in the blue jar). Fragrance is the #1 cause of skincare-related allergic contact dermatitis. By omitting fragrance, Olay makes this product much safer for sensitive skin.

---

### Could any ingredients cause problems?

While the formula is safe and dermatologically tested, certain ingredients can still cause issues depending on your skin type:

#### 1. The Retinol Duo (Retinol & Retinyl Propionate)
* **The Risk:** Mild irritation, dryness, flaking, or "purging" (temporary increase in breakouts as dead skin cells shed).
* **Who might have trouble:** If you have extremely sensitive skin, rosacea, or eczema, even this gentle retinol blend might trigger a flare-up. 
* *Note:* Retinoids are **not recommended** for women who are pregnant or breastfeeding.

#### 2. Dimethicone (Silicone)
* **The Risk:** Dimethicone gives the cream its silky, smooth texture and locks in moisture. However, some people with highly acne-prone skin find that heavy silicones can trap sebum and cause breakouts.
* **Who might have trouble:** People prone to fungal acne or those who know their skin reacts poorly to silicones.

#### 3. Tapioca Starch
* **The Risk:** Used to give the cream a matte finish so it doesn’t feel greasy. While generally safe, it can occasionally clog pores in individuals who are highly prone to comedones (blackheads/whiteheads).

---

### Is it "Safe"? (Side Effects vs. Danger)
There is a difference between a product being **unsafe** (toxic or damaging) and a product causing **temporary side effects**. 

Olay Retinol 24 is **cosmetically safe** and thoroughly tested. However, you may still experience mild side effects during the first 2 to 4 weeks of use, such as:
* Slight tightness or dryness
* Mild flaking around the mouth or nose
* A temporary tingling sensation upon application

These are normal signs of your skin adapting to retinol, not an allergic reaction or "damage." 

---

### How to use it safely to prevent irritation:

If you want to try Olay Retinol 24, follow these steps to minimize any chance of irritation:

1. **Patch Test First:** Apply a pea-sized amount to your inner jawline for 2–3 nights to see if your skin reacts before putting it on your entire face.
2. **Ease into it:** Do not use it every night at first. Start by using it **two nights a week** (e.g., Monday and Thursday). If your skin tolerates it, increase to every other night, and eventually every night.
3. **Use Sunscreen:** Retinol makes your skin more sensitive to UV rays. You **must** wear a broad-spectrum SPF 30 or higher during the day while using this product.
4. **Don't Mix with other "Actives":** On the nights you use Olay Retinol 24, do not use other harsh ingredients like salicylic acid (BHA), glycolic acid (AHA), or Vitamin C, as this will overload your skin barrier. 

### Summary
If you are new to retinol, **Olay Retinol 24 is one of the safest, most user-friendly entry points on the drugstore market.** Unless you have eczema, rosacea, or are pregnant, it is highly unlikely to cause severe problems, and any mild dryness can usually be managed by starting slowly.

</details>

**Our agent's answer (saved test output):**

The full answer below is preserved from the actual agent test. It is **not independently fact-checked**; source matches, exact product formulations, and the interpretations of ingredient ordering and openFDA reports should be reviewed before treating individual claims as established facts.

<details>
<summary>Expand full agent response for Query 3</summary>

#### Direct Answer

Olay Regenerist Retinol 24 Night Moisturizer contains active retinoids and preservatives that carry a known risk of skin irritation (such as redness, peeling, and burning) and allergic reactions. However, it is formulated without added fragrances and includes barrier-supporting ingredients, such as niacinamide and a gentler, slower-release retinoid ester (retinyl propionate), which clinical research indicates can help mitigate skin irritation.

While the product is generally designed to improve skin tolerance, individual sensitivity varies. Reports of adverse reactions including burning, itching, swelling, hives, redness, and ophthalmic migraine have been submitted to the FDA regarding this product line.

---

#### Supporting Findings

##### 1. Retinoid Profiles & Skin Irritation Risk

The formulation contains two retinoids, which have differing irritation profiles:

- **Retinol:** This is the parent alcohol form of vitamin A (Source: [PubChem Retinol CID 445354](https://pubchem.ncbi.nlm.nih.gov/compound/445354)). It is well-documented to cause "retinoid dermatitis"—characterized by redness, dryness, peeling, and burning—especially when starting therapy or at higher concentrations (Source: [PubChem Retinol CID 445354](https://pubchem.ncbi.nlm.nih.gov/compound/445354)).
- **Retinyl Propionate:** This is an ester of retinol and propionic acid (Source: [PubChem Retinyl Propionate CID 6394572](https://pubchem.ncbi.nlm.nih.gov/compound/6394572)). Because it requires an additional enzymatic step to convert to its active form, it behaves as a slower-release retinoid, resulting in a milder, lower acute irritation profile compared to free retinol (Source: [PubChem Retinyl Propionate CID 6394572](https://pubchem.ncbi.nlm.nih.gov/compound/6394572)). In a clinical trial, a product containing retinyl propionate and climbazole demonstrated significant anti-aging improvements with minimal irritation, producing significantly less irritation in patch tests than a 0.1% retinol control (Source: [PMID: 28733999](https://pubmed.ncbi.nlm.nih.gov/28733999/)).

In this Olay formulation, retinyl propionate is positioned higher up on the ingredient list than retinol, suggesting the formula relies more heavily on the milder ester (Source: [Open Beauty Facts - Olay Regenerist Retinol 24 Night Moisturiser Face Cream 50g](https://world.openbeautyfacts.org/product/4902430917872)).

##### 2. The Role of Niacinamide (Vitamin B3) in Mitigating Irritation

Niacinamide is a water-soluble form of vitamin B3 (Source: [PubChem Niacinamide CID 936](https://pubchem.ncbi.nlm.nih.gov/compound/936)). It is clinically shown to upregulate lipid and ceramide synthesis, reduce transepidermal water loss (TEWL), and offer anti-inflammatory benefits to strengthen the skin barrier (Source: [PubChem Niacinamide CID 936](https://pubchem.ncbi.nlm.nih.gov/compound/936)).

Its clinical efficacy in reducing retinoid-induced irritation is documented with some nuances:

- **In Combination Formulas:** Clinical studies show that utilizing moisturizers containing niacinamide alongside other barrier-enhancing vitamins (such as panthenol and tocopheryl acetate) mitigates the side effects and barrier compromise associated with early retinoid use (Source: [PMID: 17121065](https://pubmed.ncbi.nlm.nih.gov/17121065/)). Similarly, a combination of niacinamide (4% vitamin PP) and Myrtacine was shown to significantly reduce the dryness, redness, and stinging associated with retinoid dermatitis (Source: [PMID: 23007255](https://pubmed.ncbi.nlm.nih.gov/23007255/)).
- **As an Isolated Ingredient:** In a direct 5-day occlusive patch test, 3% niacinamide alone did not provide statistically significant relief against acute retinol-induced erythema and discomfort, whereas physiological lipids did (Source: [PMID: 38628085](https://pubmed.ncbi.nlm.nih.gov/38628085/)).

##### 3. Preservatives, Allergens, and Other Ingredients

- **Preservatives:** The moisturizer contains **DMDM Hydantoin** (a formaldehyde-releasing preservative) and **Iodopropynyl Butylcarbamate** (a broad-spectrum preservative) (Source: [Open Beauty Facts - Olay Regenerist Retinol 24 Night Moisturiser Face Cream 50g](https://world.openbeautyfacts.org/product/4902430917872)). Both of these are known potential sensitizers or irritants for individuals with highly sensitive or allergy-prone skin.
- **Fragrance:** No added fragrance ingredients, essential oils, or "Parfum" are listed in this specific formulation, which lowers the potential for fragrance-related contact allergies (Source: [Open Beauty Facts - Olay Regenerist Retinol 24 Night Moisturiser Face Cream 50g](https://world.openbeautyfacts.org/product/4902430917872)).

##### 4. Reported Adverse Events (openFDA)

Spontaneous consumer and manufacturer reports submitted to the FDA for "Olay Regenerist Retinol 24" products include the following documented symptoms (Source: [openFDA Cosmetic Adverse Events API](https://open.fda.gov/apis/cosmetic/event/)):

- Burning sensation
- Pruritus (itching)
- Swelling
- Urticaria (hives)
- Erythema (redness)
- Ophthalmic migraine

---

#### Uncertainties, Limitations, and Missing Evidence

- **Low Ingredient Concentrations:** In the retrieved formulation, both Niacinamide and Retinol are positioned near the very bottom of the ingredient list, below the preservatives DMDM Hydantoin and Iodopropynyl Butylcarbamate (Source: [Open Beauty Facts - Olay Regenerist Retinol 24 Night Moisturiser Face Cream 50g](https://world.openbeautyfacts.org/product/4902430917872)). Because exact concentrations are proprietary and not disclosed, it is uncertain whether niacinamide and retinol are present in high enough concentrations in this finished product to replicate the positive or negative effects observed in clinical trials.
- **Formulation Variability:** The ingredient list is obtained from crowdsourced data, which may contain parsing errors or vary by regional markets and manufacturing dates (Source: [Open Beauty Facts - Olay Regenerist Retinol 24 Night Moisturiser Face Cream 50g](https://world.openbeautyfacts.org/product/4902430917872)).
- **Lack of Isolation in Clinical Trials:** Most of the clinical trials evaluating irritation mitigation or reduction tested niacinamide and retinyl propionate in combination with other active components (e.g., climbazole, panthenol, or Myrtacine) (Sources: [PMID: 28733999](https://pubmed.ncbi.nlm.nih.gov/28733999/), [PMID: 17121065](https://pubmed.ncbi.nlm.nih.gov/17121065/), [PMID: 23007255](https://pubmed.ncbi.nlm.nih.gov/23007255/)). Consequently, the exact protective or irritating effects of these ingredients cannot be perfectly isolated for the Olay formulation.
- **Causality of FDA Reports:** Spontaneous reports in the openFDA database are based on consumer or manufacturer allegations. They do not establish scientific causality, confirm product defects, or represent verified incidence rates (Source: [openFDA Cosmetic Adverse Events API](https://open.fda.gov/apis/cosmetic/event/)).

---

#### Sources

- **Product & Ingredients:**
  - [Open Beauty Facts - Olay Regenerist Retinol 24 Night Moisturiser Face Cream 50g](https://world.openbeautyfacts.org/product/4902430917872)
- **Chemical Compounds (PubChem):**
  - [PubChem Retinol CID 445354](https://pubchem.ncbi.nlm.nih.gov/compound/445354)
  - [PubChem Retinyl Propionate CID 6394572](https://pubchem.ncbi.nlm.nih.gov/compound/6394572)
  - [PubChem Niacinamide CID 936](https://pubchem.ncbi.nlm.nih.gov/compound/936)
- **Clinical Studies (PubMed):**
  - [PMID: 28733999](https://pubmed.ncbi.nlm.nih.gov/28733999/) - *Retinyl propionate and climbazole combination...*
  - [PMID: 38628085](https://pubmed.ncbi.nlm.nih.gov/38628085/) - *Mitigation of retinol-induced skin irritation by physiologic lipids...*
  - [PMID: 17121065](https://pubmed.ncbi.nlm.nih.gov/17121065/) - *Facilitating facial retinization through barrier improvement...*
  - [PMID: 23007255](https://pubmed.ncbi.nlm.nih.gov/23007255/) - *Efficacy and tolerability of topical 0.2% Myrtacine® and 4% vitamin PP...*
- **Regulatory Database:**
  - [openFDA Cosmetic Adverse Events API](https://open.fda.gov/apis/cosmetic/event/)

</details>

**Comparison:** The no-tools baseline describes the moisturizer as broadly safe and makes specific formulation, tolerability, and usage claims without consulting or citing product records, clinical studies, or adverse-event data. The agent retrieves a product record, cites specific PubMed studies on irritation and related formulations, and reports possible adverse-event signals from openFDA while correctly warning that spontaneous reports cannot prove causation. The agent nevertheless makes potentially overconfident inferences about ingredient order and concentrations, and its FDA reference is an API overview rather than a direct link to particular reports; these are limitations of the saved output, not independently verified findings.

## Local setup

This project uses `uv` and Python. From the repository root:

```bash
uv sync
uv run python app.py
```

The local frontend is served at `http://127.0.0.1:8000/` by the `__main__` entry point in `app.py`. The interactive API reference is at `http://127.0.0.1:8000/docs`. The exact environment configuration for the cloud models depends on the project's Google Cloud credentials and deployment settings; do not commit secrets or `.env` files.

### API usage

The website uses `GET /run?question=...` for streamed SSE research progress. For a single JSON response, use `POST /chat` with a request body like:

```json
{
  "message": "Does niacinamide help with acne?",
  "session_id": null
}
```

The response has `response`, `session_id`, and `tool_calls`; each tool call includes its originating `agent`, `name`, `args`, and `result`. Supply the returned `session_id` in a subsequent request to continue the conversation. Sessions are stored in process memory and may expire or be lost on restart.


## Deployment and submission

Deployment target: Google Cloud Run with continuous deployment from GitHub.

- Cloud Run URL: [INSERT VERIFIED DEPLOYMENT URL]
- GitHub repository: [INSERT REPOSITORY URL]
- Cloud Run request timeout: [INSERT VERIFIED SETTING; graders allow up to five minutes per answer]
- Authors: [INSERT ALL TEAM MEMBERS' UNIs OR EMAILS]

The repository root must contain `app.py`, `pyproject.toml`, `uv.lock`, `README.md`, and `submission.json`. The submission file must include `deploy_url`, `authors`, and `path: "research"`. The deployed service should be reachable during grading.

If hosting behind multiple Cloud Run instances, note that this implementation uses in-memory session state, so conversation continuity is not guaranteed across separate instances.

## Limitations

The system can only support claims with evidence retrieved from the accessible APIs. Ingredient lists may differ across regions and reformulations. A substance's chemical mechanism is not necessarily a clinically demonstrated result at a cosmetic concentration. A trial of a multi-ingredient moisturizer cannot establish which component produced an outcome. Spontaneous cosmetic event reports may be incomplete and cannot establish causality or adverse-event rates. Where available research is inconclusive, the agent should say so.
