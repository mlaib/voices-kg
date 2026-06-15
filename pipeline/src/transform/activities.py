"""Activity, mode, cause, and historical event classification."""
from __future__ import annotations

import re

ACTIVITY_PATTERNS = {
    "deportation": [r"\bdeport", r"\btransport(ed|ation)?\b", r"\bsent to\b.*camp"],
    "forced_labor": [r"\bforced labor\b", r"\bslave labor\b", r"\blabor camp\b", r"\bworked? in.*camp\b"],
    "arrest": [r"\barrest(ed)?\b", r"\bdetain(ed)?\b", r"\bcaptured\b", r"\btaken (away|prisoner)\b"],
    "escape": [r"\bescape[ds]?\b", r"\bfled\b", r"\bran away\b", r"\bhid(e|ing|den)?\b"],
    "liberation": [r"\bliberat(ed|ion)\b", r"\bfreed?\b", r"\breleas(ed|e)\b"],
    "killing": [r"\bkill(ed|ing)?\b", r"\bshot\b", r"\bexecut(ed|ion)\b", r"\bmurder(ed)?\b", r"\bgas(sed|sing)\b"],
    "migration": [r"\bmoved? to\b", r"\bimmigrat(ed|ion)\b", r"\bemigrat(ed|ion)\b", r"\bleft for\b"],
    "education": [r"\bschool\b", r"\bstud(y|ied|ying)\b", r"\bgraduat(ed|ion)\b", r"\buniversity\b"],
    "family_life": [r"\bmarried\b", r"\bborn\b", r"\bfamily\b", r"\bchildren\b", r"\bwedding\b"],
    "hiding": [r"\bin hiding\b", r"\bhidden\b", r"\bhide\b", r"\bshelter(ed)?\b"],
    "resistance": [r"\bresistance\b", r"\bpartisan\b", r"\bfight(ing)?\b.*against\b", r"\bupris(ing|e)\b"],
    "medical": [r"\bhospital\b", r"\bsick\b", r"\bill(ness)?\b", r"\bdoctor\b", r"\btyphus\b"],
    "selection": [r"\bselection\b", r"\bselected\b", r"\bchose\b.*life|death"],
    "testimony": [r"\btestif(y|ied)\b", r"\bwitness(ed|ing)?\b", r"\btestimon(y|ies)\b"],
}

MODE_PATTERNS = {
    "train": [r"\bby train\b", r"\btrain\b", r"\brailway\b", r"\bcattle car\b"],
    "truck": [r"\bby truck\b", r"\btruck\b", r"\blorry\b"],
    "foot": [r"\bon foot\b", r"\bwalk(ed|ing)?\b", r"\bmarch(ed|ing)?\b"],
    "wagon": [r"\bwagon\b", r"\bcart\b"],
    "ship": [r"\bby ship\b", r"\bboat\b", r"\bvessel\b", r"\bsail(ed)?\b"],
    "car": [r"\bby car\b", r"\bautomobile\b"],
}

CAUSE_PATTERNS = {
    "antisemitic_policy": [r"\banti[- ]?semit", r"\banti[- ]?jew", r"\bnazi\b", r"\bdecree\b",
                           r"\bnuremberg\b", r"\bjewish law\b"],
    "war_operation": [r"\binvasion\b", r"\bwar\b", r"\bfront\b", r"\bbomb(ed|ing)?\b",
                      r"\boccupation\b", r"\bsurrender\b"],
    "survival_need": [r"\bhunger\b", r"\bstarv(ing|ation)\b", r"\bsurviv(e|al)\b", r"\bfood\b"],
    "family_reason": [r"\bfamily\b", r"\bmother\b", r"\bfather\b", r"\bchildren\b", r"\bparent\b"],
    "economic": [r"\bjob\b", r"\bwork\b", r"\bpoverty\b", r"\bmoney\b"],
}

HISTORICAL_EVENT_PATTERNS = {
    "Kristallnacht": [r"\bkristallnacht\b", r"\bnight of broken glass\b", r"\bnovember (pogrom|1938)\b"],
    "Shoah_Deportations": [r"\bdeport", r"\btransport.*camp\b"],
    "Camp_Liberation": [r"\bliberat(ed|ion)\b", r"\bfreed\b"],
    "Ghettoization": [r"\bghetto\b"],
    "Forced_Marches": [r"\bforced march\b", r"\bdeath march\b"],
    "Invasion_Poland": [r"\binvad(ed|ing)?\s+poland\b", r"\bseptember 1939\b"],
    "Wannsee_Conference": [r"\bwannsee\b"],
    "Nuremberg_Trials": [r"\bnuremberg trial\b"],
    "DDay_Liberation": [r"\bd[- ]?day\b", r"\bnormandy\b"],
    "End_of_War": [r"\bend of.*war\b", r"\bvictory\b", r"\bsurrender\b.*1945"],
}


def _match(text: str, patterns: dict[str, list[str]]) -> list[str]:
    t = text.lower()
    return [name for name, pats in patterns.items()
            if any(re.search(p, t) for p in pats)]


def classify_activities(what_text: str) -> list[str]:
    return _match(what_text, ACTIVITY_PATTERNS)


def classify_modes(what_text: str) -> list[str]:
    return _match(what_text, MODE_PATTERNS)


def classify_causes(what_text: str) -> list[str]:
    return _match(what_text, CAUSE_PATTERNS)


def classify_historical_events(what_text: str) -> list[str]:
    return _match(what_text, HISTORICAL_EVENT_PATTERNS)
