---
name: onboarding_extract
version: v2
purpose: Extract a Company Profile from crawled website text — few-shot strategy.
consumed_by: backend/graph/nodes/onboarding.py::extract_node (opt-in via version)
schema: backend/graph/nodes/onboarding.py::CompanyProfileDraft
---

You extract structured Company Profiles from website copy. Study the two worked examples below, then extract a profile from the target site with the same rigor.

## Example A — Wine estate (owned-heavy)

Site: **Weingut Muster** — Rheinhessen family estate, five generations, steep-slope organic viticulture. Homepage copy talks about vintages, terroir, hand-picked, cellar tours, no marketing hype.

Extraction:

```json
{{
  "identity":   {{"summary": "5th-generation Rheinhessen family estate producing steep-slope, hand-picked, organic Riesling and Pinot Noir; direct-to-consumer and regional restaurants.", "products": ["Riesling 2023", "Pinot Noir", "cellar tours"]}},
  "market":     {{"segments": ["direct-to-consumer wine", "regional restaurants"], "geo": ["Rheinhessen, DE"], "icp": "wine enthusiasts and regional restaurateurs looking for craft steep-slope Riesling"}},
  "positioning":{{"value_prop": "Steep-slope, organic, hand-picked wine from a 5th-generation family estate.", "differentiators": ["organic", "5th-generation family", "steep-slope"]}},
  "voice":      {{"tone": ["warm", "earthy", "unpretentious"], "vocabulary": ["vintage", "terroir", "hand-picked"], "do": ["tell the family story", "lean into seasonality"], "dont": ["corporate jargon", "hype", "discount language"]}},
  "content_pillars": [
    {{"name": "product", "description": "wine releases + tasting notes for current vintages"}},
    {{"name": "place", "description": "the vineyard, seasons, terroir"}},
    {{"name": "people", "description": "family history + craft"}},
    {{"name": "events", "description": "tastings, cellar tours"}}
  ],
  "content_mix": 0.8
}}
```

**Why 0.8:** the business IS the story. External industry news barely enters — the customer follows the estate for the estate.

## Example B — Logistics startup (external-heavy)

Site: **RouteRight** — warehouse routing API for mid-size 3PLs. Copy is direct/technical/no-hype, talks about pick rate, throughput, 2-week integration, no forklift retrofit.

Extraction:

```json
{{
  "identity":   {{"summary": "Warehouse routing API for mid-size 3PLs — pick-rate optimization without forklift retrofit; 2-week integration.", "products": ["warehouse routing API", "fleet analytics"]}},
  "market":     {{"segments": ["mid-size 3PLs", "e-commerce fulfilment"], "geo": ["DACH", "EU"], "icp": "ops lead at a 50-500 person 3PL evaluating automation options"}},
  "positioning":{{"value_prop": "Route your warehouse without a forklift retrofit — 2-week integration.", "differentiators": ["no forklift retrofit", "2-week integration"]}},
  "voice":      {{"tone": ["direct", "technical", "no-hype"], "vocabulary": ["pick rate", "throughput", "integration"], "do": ["show numbers", "reference real ops metrics"], "dont": ["buzzwords", "AI-will-change-everything takes", "generic industry commentary"]}},
  "content_pillars": [
    {{"name": "industry", "description": "warehouse automation news + competitive moves"}},
    {{"name": "proof", "description": "customer results with concrete pick-rate numbers"}},
    {{"name": "opinion", "description": "where the market is going + why forklift-retrofit models lose"}}
  ],
  "content_mix": 0.3
}}
```

**Why 0.3:** a technical startup grows credibility through industry commentary more than through announcing its own product moves. Content mostly comes from outside the company, filtered through their perspective.

## Now extract from the target site

Use the same JSON shape. Ground every field in the crawled copy — no invented products, geographies, or claims. Colors + branding are handled elsewhere; you only produce the profile below.

**Business URL:** {url}

**Crawled pages (page title on first line, then extracted text):**

{pages}

Return only the JSON. No prose, no markdown fences.
