# -*- coding: utf-8 -*-
"""Method lexicon (heuristic fallback)

This file is intentionally conservative:
- Used as a *fallback* when the LLM returns empty/ambiguous method fields.
- Also used to enrich prompts (examples), without forcing enums too narrowly.

You can extend this list freely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

# High-level categories (kept broad; model can still return novel method_terms)
METHOD_CATEGORIES: List[str] = [
    "Anterograde tracer",
    "Retrograde tracer",
    "Viral tracing",
    "Transsynaptic tracing",
    "Optogenetics",
    "Chemogenetics",
    "Electrophysiology",
    "Calcium imaging",
    "fMRI",
    "Diffusion MRI / tractography",
    "EM connectomics",
    "Light microscopy / histology",
    "Immunohistochemistry",
    "Tissue clearing",
    "Lesion / inactivation",
    "Stimulation (electrical/magnetic)",
    "Behavioral / correlation",
    "Other / unspecified",
]

# Keyword bank (lowercased substrings). Each entry: (keyword, category, canonical_term)
KEYWORDS: List[Tuple[str, str, str]] = [
    # Classic tracers
    ("bda", "Anterograde tracer", "BDA (biotinylated dextran amine)"),
    ("pha-l", "Anterograde tracer", "PHA-L"),
    ("phaseolus vulgaris leucoagglutinin", "Anterograde tracer", "PHA-L"),
    ("wga-hrp", "Anterograde tracer", "WGA-HRP"),
    ("wga hrp", "Anterograde tracer", "WGA-HRP"),
    ("ctb", "Retrograde tracer", "CTB (cholera toxin B)"),
    ("cholera toxin b", "Retrograde tracer", "CTB"),
    ("fluorogold", "Retrograde tracer", "Fluoro-Gold"),
    ("fast blue", "Retrograde tracer", "Fast Blue"),
    ("retrobeads", "Retrograde tracer", "RetroBeads"),
    ("diamidino yellow", "Retrograde tracer", "Diamidino Yellow"),

    # Viral / transsynaptic
    ("aav", "Viral tracing", "AAV"),
    ("adeno-associated virus", "Viral tracing", "AAV"),
    ("lentivirus", "Viral tracing", "Lentivirus"),
    ("cav-2", "Viral tracing", "CAV-2"),
    ("canine adenovirus", "Viral tracing", "CAV-2"),
    ("rabies", "Transsynaptic tracing", "Rabies virus"),
    ("rvdG", "Transsynaptic tracing", "Rabies ΔG"),
    ("hsv", "Viral tracing", "HSV"),
    ("herpes simplex", "Viral tracing", "HSV"),
    ("prv", "Transsynaptic tracing", "PRV (pseudorabies virus)"),

    # Opto / chemo
    ("chr2", "Optogenetics", "ChR2"),
    ("channelrhodopsin", "Optogenetics", "Channelrhodopsin"),
    ("archt", "Optogenetics", "ArchT"),
    ("halorhodopsin", "Optogenetics", "Halorhodopsin"),
    ("opto", "Optogenetics", "Optogenetics"),
    ("dread", "Chemogenetics", "DREADDs"),
    ("hM3Dq".lower(), "Chemogenetics", "hM3Dq"),
    ("hM4Di".lower(), "Chemogenetics", "hM4Di"),
    ("clozapine-n-oxide", "Chemogenetics", "CNO"),

    # Electrophysiology
    ("patch clamp", "Electrophysiology", "Patch clamp"),
    ("whole-cell", "Electrophysiology", "Whole-cell recording"),
    ("extracellular", "Electrophysiology", "Extracellular recording"),
    ("neuropixels", "Electrophysiology", "Neuropixels"),
    ("tetrode", "Electrophysiology", "Tetrodes"),

    # Imaging
    ("two-photon", "Calcium imaging", "Two-photon imaging"),
    ("2-photon", "Calcium imaging", "Two-photon imaging"),
    ("gcamp", "Calcium imaging", "GCaMP"),
    ("miniscope", "Calcium imaging", "Miniscope"),
    ("fmri", "fMRI", "fMRI"),
    ("bold", "fMRI", "BOLD fMRI"),
    ("dti", "Diffusion MRI / tractography", "DTI"),
    ("diffusion mri", "Diffusion MRI / tractography", "Diffusion MRI"),
    ("tractography", "Diffusion MRI / tractography", "Tractography"),
    ("mrtrix", "Diffusion MRI / tractography", "MRtrix"),
    ("fsl", "Diffusion MRI / tractography", "FSL"),

    # Microscopy / histology
    ("immunohistochemistry", "Immunohistochemistry", "Immunohistochemistry"),
    ("immunostaining", "Immunohistochemistry", "Immunostaining"),
    ("confocal", "Light microscopy / histology", "Confocal microscopy"),
    ("light sheet", "Light microscopy / histology", "Light-sheet microscopy"),
    ("lightsheet", "Light microscopy / histology", "Light-sheet microscopy"),
    ("electron microscopy", "EM connectomics", "Electron microscopy"),
    ("serial block-face", "EM connectomics", "Serial block-face EM"),
    ("sbem", "EM connectomics", "SBEM"),
    ("fIB-SEM".lower(), "EM connectomics", "FIB-SEM"),

    # Clearing
    ("clari", "Tissue clearing", "CLARITY-family clearing"),
    ("idis", "Tissue clearing", "iDISCO-family clearing"),
    ("cub", "Tissue clearing", "CUBIC-family clearing"),
    ("shrinkage", "Tissue clearing", "Clearing/shrinkage"),

    # Lesions / inactivation / stimulation
    ("muscimol", "Lesion / inactivation", "Muscimol inactivation"),
    ("lidocaine", "Lesion / inactivation", "Lidocaine inactivation"),
    ("ttx", "Lesion / inactivation", "TTX"),
    ("lesion", "Lesion / inactivation", "Lesion"),
    ("microstimulation", "Stimulation (electrical/magnetic)", "Microstimulation"),
    ("tms", "Stimulation (electrical/magnetic)", "TMS"),
]

def infer_method(text: str) -> tuple[str, list[str]]:
    """Infer (category, terms) from raw paper text using substring matching."""
    t = (text or "").lower()
    found_terms: list[str] = []
    found_cats: dict[str, int] = {}
    for kw, cat, term in KEYWORDS:
        if kw in t:
            found_terms.append(term)
            found_cats[cat] = found_cats.get(cat, 0) + 1
    if not found_terms:
        return "Other / unspecified", []
    # choose most frequent category
    best_cat = max(found_cats.items(), key=lambda x: x[1])[0]
    # de-dup while preserving order
    seen = set()
    dedup_terms = []
    for x in found_terms:
        if x not in seen:
            seen.add(x)
            dedup_terms.append(x)
    return best_cat, dedup_terms
