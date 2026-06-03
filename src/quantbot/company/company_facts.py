"""Extract a small, well-defined set of fundamentals from SEC companyfacts.

Pure transforms -- no network, no broker. Input is the parsed JSON from
:func:`quantbot.company.sec_edgar.fetch_company_facts`.

Philosophy: **do not overclaim.** XBRL tagging varies by filer and over time,
so each friendly field maps to an ORDERED list of candidate US-GAAP concepts;
we use the first one actually present and record exactly which tag was used.
If nothing matches, the field is reported as unavailable rather than guessed.
"""

from __future__ import annotations

import pandas as pd

# friendly field -> ordered candidate US-GAAP concept tags (first match wins)
TARGET_CONCEPTS: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "total_debt": [
        "LongTermDebt",
        "LongTermDebtNoncurrent",
        "DebtLongtermAndShorttermCombinedAmount",
    ],
    # V6.2.1 additions: small set of standard US-GAAP concepts useful for
    # semiconductor (and other sector) catalysts. Same first-match policy —
    # if no candidate tag is present for a filer, the field is reported as
    # unavailable (never inferred).
    "gross_profit": ["GrossProfit"],
    "cost_of_revenue": [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
    ],
    "rd_expense": [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    ],
    "operating_income": ["OperatingIncomeLoss"],
    "inventory_net": ["InventoryNet"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
}

OBS_COLUMNS = ["field", "concept_tag", "unit", "end", "start", "val",
               "fy", "fp", "form", "accession"]
AVAIL_COLUMNS = ["field", "candidate_tags", "matched_tag", "available",
                 "n_observations", "unit"]


def _gaap_facts(facts_json: dict | None) -> dict:
    if not isinstance(facts_json, dict):
        return {}
    facts = facts_json.get("facts")
    if not isinstance(facts, dict):
        return {}
    gaap = facts.get("us-gaap")
    return gaap if isinstance(gaap, dict) else {}


def _tag_latest_end(gaap: dict, tag: str) -> str:
    """Return the latest ``end`` ISO date string across all units / observations
    for ``tag`` in the GAAP map. Empty string if no observations are present.

    Used by :func:`_first_matching_tag` to prefer the candidate tag whose most
    recent observation is the freshest — necessary because some filers switch
    concept tags over time (e.g. NVDA moved from
    ``RevenueFromContractWithCustomerExcludingAssessedTax`` to ``Revenues``
    after FY2022, leaving the older tag's observations stale in companyfacts).
    """
    node = gaap.get(tag)
    if not isinstance(node, dict) or not isinstance(node.get("units"), dict):
        return ""
    latest = ""
    for obs_list in node["units"].values():
        if not isinstance(obs_list, list):
            continue
        for obs in obs_list:
            if isinstance(obs, dict):
                end = str(obs.get("end") or "")
                if end > latest:
                    latest = end
    return latest


def _first_matching_tag(gaap: dict, candidates: list[str]) -> str | None:
    """Return the candidate tag to use for a friendly field.

    Selection policy (V6.2.1):
      1. Filter to candidates that actually have at least one observation.
      2. Among those, pick the candidate whose most recent ``end`` date is the
         freshest. Ties broken by candidate-list order (earlier candidate wins).
      3. If no candidate has any observations, return None.

    Earlier behaviour returned the FIRST candidate with any data, which silently
    produced stale series when a filer switched concept tags between candidates
    (e.g. NVDA revenue stuck at FY2022 while the modern tag carried FY2023+).
    The new selection still returns a single tag and never mixes observations
    from multiple tags into one field.
    """
    present: list[tuple[str, str, int]] = []  # (latest_end, tag, order_idx)
    for idx, tag in enumerate(candidates):
        node = gaap.get(tag)
        if not isinstance(node, dict) or not isinstance(node.get("units"), dict):
            continue
        if not any(node["units"].values()):
            continue
        present.append((_tag_latest_end(gaap, tag), tag, idx))
    if not present:
        return None
    # Sort by (latest_end DESC, order_idx ASC). Python sorts are stable, so we
    # apply a secondary sort first, then primary.
    present.sort(key=lambda x: x[2])              # tie-break: list order
    present.sort(key=lambda x: x[0], reverse=True)  # primary: freshest end
    return present[0][1]


def extract_company_facts(facts_json: dict | None) -> pd.DataFrame:
    """Long-form observations for every target field that is present.

    One row per (field, reported observation). Empty frame if nothing matches.
    """
    gaap = _gaap_facts(facts_json)
    if not gaap:
        return pd.DataFrame(columns=OBS_COLUMNS)

    rows: list[dict] = []
    for field, candidates in TARGET_CONCEPTS.items():
        tag = _first_matching_tag(gaap, candidates)
        if tag is None:
            continue
        units = gaap[tag].get("units", {})
        for unit, observations in units.items():
            if not isinstance(observations, list):
                continue
            for obs in observations:
                if not isinstance(obs, dict) or "val" not in obs:
                    continue
                rows.append({
                    "field": field,
                    "concept_tag": tag,
                    "unit": unit,
                    "end": obs.get("end", ""),
                    "start": obs.get("start", ""),
                    "val": obs.get("val"),
                    "fy": obs.get("fy"),
                    "fp": obs.get("fp", ""),
                    "form": obs.get("form", ""),
                    "accession": obs.get("accn", ""),
                })
    if not rows:
        return pd.DataFrame(columns=OBS_COLUMNS)
    df = pd.DataFrame(rows, columns=OBS_COLUMNS)
    df["end"] = pd.to_datetime(df["end"], errors="coerce")
    df["start"] = pd.to_datetime(df["start"], errors="coerce")
    return df


def company_facts_availability(facts_json: dict | None) -> pd.DataFrame:
    """One row per target field: present? which tag? how many observations?"""
    gaap = _gaap_facts(facts_json)
    rows = []
    for field, candidates in TARGET_CONCEPTS.items():
        tag = _first_matching_tag(gaap, candidates) if gaap else None
        n_obs, unit = 0, ""
        if tag is not None:
            units = gaap[tag].get("units", {})
            for u, obs in units.items():
                if isinstance(obs, list):
                    n_obs += len(obs)
                    unit = unit or u
        rows.append({
            "field": field,
            "candidate_tags": ", ".join(candidates),
            "matched_tag": tag or "",
            "available": tag is not None,
            "n_observations": n_obs,
            "unit": unit,
        })
    return pd.DataFrame(rows, columns=AVAIL_COLUMNS)


def latest_annual_facts(extracted: pd.DataFrame) -> pd.DataFrame:
    """Latest annual (10-K, full-year) value per field for a compact summary.

    Falls back to the latest observation of any form if no 10-K/FY row exists
    for a field. Empty input -> empty output.
    """
    if extracted is None or extracted.empty:
        return pd.DataFrame(columns=["field", "concept_tag", "unit", "end",
                                     "val", "fy", "fp", "form"])
    rows = []
    for field, grp in extracted.groupby("field"):
        annual = grp[(grp["form"].astype(str).str.upper().str.startswith("10-K"))
                     & (grp["fp"].astype(str).str.upper() == "FY")]
        pick_from = annual if not annual.empty else grp
        pick = pick_from.sort_values("end").iloc[-1]
        rows.append({
            "field": field,
            "concept_tag": pick["concept_tag"],
            "unit": pick["unit"],
            "end": pick["end"].date().isoformat() if pd.notna(pick["end"]) else "",
            "val": pick["val"],
            "fy": pick["fy"],
            "fp": pick["fp"],
            "form": pick["form"],
        })
    return pd.DataFrame(rows).sort_values("field").reset_index(drop=True)
