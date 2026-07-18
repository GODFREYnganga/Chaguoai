# src/who_mec_engine.py
"""
ChaguoAI — WHO Medical Eligibility Criteria (MEC) Engine.

Source authorities:
    - WHO Medical Eligibility Criteria for Contraceptive Use, 6th Edition (2025)
      https://www.who.int/publications/i/item/9789240115583
    - Kenya National Family Planning Guideline for Healthcare Providers,
      7th Edition (2025), Ministry of Health Kenya, DRMNCAH
    - Family Planning: A Global Handbook for Providers, 2022 Edition
      WHO and Johns Hopkins Bloomberg School of Public Health

Clinical mandate:
    This engine is the FIRST and ONLY safety gate in the ChaguoAI pipeline.
    No ML model, no LLM, and no user preference can override a Category 4
    result from this engine. A Category 3 result can only be overridden by
    an explicit, documented clinical judgment from a qualified provider.

    The engine follows the WHO two-level approach:
        Category 1 — No restriction. Method can be used.
        Category 2 — Advantages generally outweigh risks. Method can be used.
        Category 3 — Risks usually outweigh advantages. Method generally
                      should NOT be used without clinical judgment.
        Category 4 — Unacceptable health risk. Method MUST NOT be used.

    In this implementation:
        Safe to recommend:     Category 1 or 2 (max_category <= 2)
        Refer to provider:     Category 3 (max_category == 3)
        Absolute exclusion:    Category 4 (max_category == 4)

Versioning:
    This file must be reviewed and updated whenever a new edition of the
    WHO MEC is published. Current baseline: WHO MEC 6th Edition, 2025.

Author: ChaguoAI Team
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import json


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class UserProfile:
    """
    Structured profile collected from the user during intake.

    Every field maps directly to one of the 13 intake questions
    defined in the ChaguoAI intake specification. Fields default
    to None (unknown) rather than False (known negative) so the
    engine can distinguish missing information from negative answers.

    Clinical note: Unknown is not the same as absent. A woman who
    does not answer the hypertension question is NOT confirmed
    normotensive. The engine handles this conservatively.
    """

    # ── DEMOGRAPHICS ───────────────────────────────────────────
    age_years: Optional[int] = None
    number_of_children: Optional[int] = None

    # ── REPRODUCTIVE STATUS ────────────────────────────────────
    # last_period_timing: 'within_4_weeks', 'over_4_weeks_ago', 'unknown'
    last_period_timing: Optional[str] = None

    # pregnancy_status: 'not_pregnant', 'possibly_pregnant', 'pregnant'
    pregnancy_status: Optional[str] = None

    # postpartum_days: number of days since delivery (None if not postpartum)
    postpartum_days: Optional[int] = None

    # ── BREASTFEEDING ──────────────────────────────────────────
    breastfeeding: Optional[bool] = None
    breastfeeding_exclusively: Optional[bool] = None
    # baby_age_months: age of youngest baby in months (for LAM assessment)
    baby_age_months: Optional[float] = None

    # ── HEALTH CONDITIONS (direct from WHO MEC criteria) ───────
    hypertension: Optional[bool] = None
    # systolic_bp_mmhg: if known. Used to distinguish mild vs severe.
    systolic_bp_mmhg: Optional[int] = None
    diastolic_bp_mmhg: Optional[int] = None

    diabetes: Optional[bool] = None
    # diabetes_with_vascular_complications: nephropathy, retinopathy, neuropathy
    diabetes_with_vascular_complications: Optional[bool] = None

    heart_disease: Optional[bool] = None
    # ischemic_heart_disease: history of MI, angina
    ischemic_heart_disease: Optional[bool] = None
    # history_of_stroke: CVA or TIA
    history_of_stroke: Optional[bool] = None

    # migraine_with_aura: visual disturbances, numbness, speech difficulty
    migraine_with_aura: Optional[bool] = None
    # migraine_without_aura: true migraine, no focal neurological symptoms
    migraine_without_aura: Optional[bool] = None

    # liver_disease: jaundice, hepatitis, cirrhosis, liver tumour
    liver_disease: Optional[bool] = None
    # active_viral_hepatitis: acute or flare
    active_viral_hepatitis: Optional[bool] = None

    # deep_vein_thrombosis or pulmonary_embolism — current or past
    history_of_vte: Optional[bool] = None
    # current_vte: on anticoagulation
    current_vte: Optional[bool] = None

    # breast_cancer: current or past
    breast_cancer_current: Optional[bool] = None
    breast_cancer_past_5_years: Optional[bool] = None

    # cervical_cancer: awaiting treatment
    cervical_cancer: Optional[bool] = None

    # uterine_fibroids_distorting_cavity: relevant for IUD insertion
    fibroids_distorting_cavity: Optional[bool] = None

    # pelvic_inflammatory_disease in past 3 months
    recent_pid: Optional[bool] = None

    # kidney_disease: severe
    severe_kidney_disease: Optional[bool] = None

    # epilepsy: on enzyme-inducing antiepileptic drugs
    epilepsy_on_enzyme_inducing_aeds: Optional[bool] = None

    # ── STI / HIV ──────────────────────────────────────────────
    hiv_positive: Optional[bool] = None
    # hiv_stage: 'stage_1_2' (asymptomatic/mild), 'stage_3_4' (severe/advanced)
    hiv_stage: Optional[str] = None
    # art_regimen: 'nrti', 'nnrti_efavirenz', 'nnrti_no_efavirenz',
    #              'protease_inhibitor', 'integrase_inhibitor', 'none', 'unknown'
    art_regimen: Optional[str] = None
    # prep_use: taking pre-exposure prophylaxis
    prep_use: Optional[bool] = None
    # high_sti_risk: multiple partners, partner with STI, etc.
    high_sti_risk: Optional[bool] = None

    # ── LIFESTYLE / CONTEXT ────────────────────────────────────
    smoker: Optional[bool] = None

    # fertility_intention: 'within_2_years', 'later', 'no_more', 'undecided'
    fertility_intention: Optional[str] = None

    # partner_supports_contraception: affects continuation, not MEC eligibility
    partner_supports_contraception: Optional[bool] = None

    # previous_method: standardized method name from method name map
    previous_method: Optional[str] = None
    # previous_side_effects: experienced side effects with prior method
    previous_side_effects: Optional[bool] = None

    # facility_access: 'easy', 'sometimes_hard', 'very_hard'
    facility_access: Optional[str] = None


@dataclass
class MethodResult:
    """
    MEC assessment result for one contraceptive method.
    """
    method_name: str
    method_display_name: str
    max_mec_category: int
    # The conditions that triggered the highest category
    limiting_conditions: list[str] = field(default_factory=list)
    # Clinical note for provider or system
    clinical_note: str = ""
    # Whether a provider should be consulted before use
    requires_provider_judgment: bool = False
    # Whether this method is absolutely contraindicated
    is_contraindicated: bool = False


@dataclass
class MECResult:
    """
    Complete MEC assessment for all methods, given a user profile.
    """
    # Methods safe to recommend (Category 1 or 2)
    recommended_methods: list[MethodResult] = field(default_factory=list)
    # Methods requiring provider judgment (Category 3)
    provider_judgment_methods: list[MethodResult] = field(default_factory=list)
    # Methods absolutely contraindicated (Category 4)
    contraindicated_methods: list[MethodResult] = field(default_factory=list)
    # Global flags
    refer_immediately: bool = False
    refer_reason: str = ""
    # Conditions identified in the profile that triggered any restriction
    flagged_conditions: list[str] = field(default_factory=list)


# ============================================================
# METHOD DEFINITIONS
# ============================================================

# Internal method keys used throughout the engine
# Display names are human-readable for output
METHOD_DISPLAY_NAMES = {
    "coc":          "Combined Oral Contraceptive (COC)",
    "patch":        "Contraceptive Patch",
    "cvr":          "Combined Vaginal Ring (CVR)",
    "cic":          "Combined Injectable Contraceptive",
    "pop":          "Progestogen-Only Pill (POP/Mini-pill)",
    "dmpa_im":      "Injectable — DMPA Intramuscular (Depo-Provera)",
    "dmpa_sc":      "Injectable — DMPA Subcutaneous",
    "net_en":       "Injectable — NET-EN (Norethisterone Enanthate)",
    "implant_lng":  "Implant — LNG (Jadelle/Sino-implant)",
    "implant_etg":  "Implant — ETG (Implanon/Nexplanon)",
    "cu_iud":       "Copper IUD (Non-hormonal)",
    "lng_iud":      "LNG-IUD (Hormonal IUD / Mirena)",
    "ecp_lng":      "Emergency Contraceptive Pill — Levonorgestrel",
    "ecp_upa":      "Emergency Contraceptive Pill — Ulipristal Acetate (UPA)",
    "ecp_coc":      "Emergency Contraceptive — Combined Pill (Yuzpe)",
    "e_iud":        "Copper IUD for Emergency Contraception",
    "male_condom":  "Male Condom",
    "female_condom":"Female Condom",
    "diaphragm":    "Diaphragm",
    "lam":          "Lactational Amenorrhoea Method (LAM)",
    "fab":          "Fertility Awareness-Based Methods (FAB)",
    "withdrawal":   "Withdrawal (Coitus Interruptus)",
    "female_ster":  "Female Sterilization (BTL)",
    "male_ster":    "Vasectomy (Male Sterilization)",
}

# Group methods for easier display
COMBINED_HORMONAL_METHODS = ["coc", "patch", "cvr", "cic"]
PROGESTOGEN_ONLY_PILL = ["pop"]
PROGESTOGEN_ONLY_INJECTABLES = ["dmpa_im", "dmpa_sc", "net_en"]
IMPLANTS = ["implant_lng", "implant_etg"]
IUDS = ["cu_iud", "lng_iud"]
BARRIER_METHODS = ["male_condom", "female_condom", "diaphragm"]
EMERGENCY_CONTRACEPTION = ["ecp_lng", "ecp_upa", "ecp_coc", "e_iud"]
NON_METHOD = ["lam", "fab", "withdrawal", "female_ster", "male_ster"]

ALL_METHODS = list(METHOD_DISPLAY_NAMES.keys())


# ============================================================
# CORE MEC ASSESSMENT FUNCTIONS
# ============================================================

def _classify_blood_pressure(systolic: Optional[int],
                              diastolic: Optional[int],
                              hypertension_reported: Optional[bool]) -> str:
    """
    Classify blood pressure category per WHO MEC 6th Edition Table 5.
    Returns: 'normal', 'mild' (140-159 / 90-99), 'severe' (>=160 / >=100),
             'reported_unknown_severity', or 'not_applicable'

    WHO MEC distinguishes:
        - BP adequately controlled (Category 3 for CHC)
        - 140-159/90-99 mmHg (Category 3 for CHC)
        - >=160/>=100 mmHg (Category 4 for CHC, Category 2 for POP/DMPA)
    """
    if systolic is not None and diastolic is not None:
        if systolic >= 160 or diastolic >= 100:
            return "severe"
        if systolic >= 140 or diastolic >= 90:
            return "mild"
        return "normal"
    if hypertension_reported:
        return "reported_unknown_severity"
    return "not_applicable"


def _compute_postpartum_status(postpartum_days: Optional[int],
                                breastfeeding: Optional[bool]) -> dict:
    """
    Compute detailed postpartum status used by multiple MEC rules.

    WHO MEC uses these postpartum windows:
        < 21 days postpartum
        21 to < 42 days postpartum (with/without VTE risk factors)
        42 days to < 6 months postpartum
        >= 6 months postpartum (or not postpartum)

    For breastfeeding:
        < 6 weeks postpartum and breastfeeding
        6 weeks to < 6 months postpartum and breastfeeding
        >= 6 months postpartum and breastfeeding

    For IUD insertion:
        < 48 hours postpartum
        48 hours to < 4 weeks postpartum
        >= 4 weeks postpartum
    """
    if postpartum_days is None:
        return {
            "is_postpartum": False,
            "under_21_days": False,
            "21_to_42_days": False,
            "42_days_to_6_months": False,
            "over_6_months": False,
            "under_48_hours": False,
            "48h_to_4_weeks": False,
            "over_4_weeks": True,
            "bf_under_6_weeks": False,
            "bf_6_weeks_to_6_months": False,
            "bf_over_6_months": False,
        }

    pp_weeks = postpartum_days / 7

    is_bf = breastfeeding is True
    bf_under_6_weeks = is_bf and pp_weeks < 6
    bf_6_weeks_to_6_months = is_bf and 6 <= pp_weeks < 26
    bf_over_6_months = is_bf and pp_weeks >= 26

    return {
        "is_postpartum": True,
        "under_21_days": postpartum_days < 21,
        "21_to_42_days": 21 <= postpartum_days < 42,
        "42_days_to_6_months": 42 <= postpartum_days < 182,
        "over_6_months": postpartum_days >= 182,
        "under_48_hours": postpartum_days < 2,
        "48h_to_4_weeks": 2 <= postpartum_days < 28,
        "over_4_weeks": postpartum_days >= 28,
        "bf_under_6_weeks": bf_under_6_weeks,
        "bf_6_weeks_to_6_months": bf_6_weeks_to_6_months,
        "bf_over_6_months": bf_over_6_months,
    }


def _assess_method(method_key: str, profile: UserProfile,
                   pp: dict, bp: str) -> MethodResult:
    """
    Compute the MEC category for one contraceptive method.

    Implements WHO MEC 6th Edition (2025) criteria for all conditions
    collected in the UserProfile. Returns a MethodResult with the
    maximum category and the conditions that triggered it.

    Structure:
        For each MEC condition in the profile, determine the category
        for this specific method. Track the maximum category and the
        conditions that contributed to it.
    """
    max_cat = 1
    limiting = []
    clinical_notes = []

    def _update(cat: int, condition_label: str, note: str = ""):
        nonlocal max_cat, limiting
        if cat > max_cat:
            max_cat = cat
            limiting = [condition_label]
            if note:
                clinical_notes.append(note)
        elif cat == max_cat and cat > 1:
            limiting.append(condition_label)
            if note:
                clinical_notes.append(note)

    # ── PREGNANCY ─────────────────────────────────────────────
    # Pregnancy is a Category 4 for all hormonal and IUD methods.
    # Source: WHO MEC 6th Ed, Section 5 (all method tables).
    if profile.pregnancy_status == "pregnant":
        if method_key not in ["male_condom", "female_condom", "diaphragm"]:
            _update(4, "Known or suspected pregnancy",
                    "Pregnancy is an absolute contraindication for this method.")

    # ── AGE ────────────────────────────────────────────────────
    # WHO MEC 6th Ed: Menarche to < 18 years for CHC: Category 2
    # Menarche to < 18 years for DMPA: Category 2 (bone density concern)
    # Source: WHO MEC 6th Ed Table 5, Age row.
    if profile.age_years is not None:
        age = profile.age_years
        if age < 18:
            if method_key in COMBINED_HORMONAL_METHODS:
                _update(2, "Age under 18 (menarche to < 18)",
                        "Benefits generally outweigh risks for CHCs in adolescents.")
            if method_key in ["dmpa_im", "dmpa_sc"]:
                _update(2, "Age under 18 (bone density concern with DMPA)",
                        "DMPA use in adolescents: concern for bone density; "
                        "benefits generally outweigh risks.")
        if age >= 40:
            if method_key in COMBINED_HORMONAL_METHODS:
                _update(2, "Age 40 and over",
                        "WHO MEC: Women 40 years and older can generally use CHCs "
                        "(Category 2).")

    # ── SMOKING + AGE ──────────────────────────────────────────
    # Source: WHO MEC 6th Ed, Table 5, Smoking row.
    # < 35 years + smoker: Category 2 for CHC
    # >= 35 years + smoker: Category 4 for CHC (absolute contraindication)
    if profile.smoker and profile.age_years is not None:
        if method_key in COMBINED_HORMONAL_METHODS:
            if profile.age_years >= 35:
                _update(4, "Smoker aged 35 or older",
                        "ABSOLUTE CONTRAINDICATION: Smoking aged 35+ with CHC "
                        "carries unacceptable cardiovascular risk.")
            else:
                _update(2, "Smoker under age 35",
                        "Smoking under 35 with CHC: benefits generally outweigh risks.")

    # ── POSTPARTUM — NON-BREASTFEEDING ─────────────────────────
    # Source: WHO MEC 6th Ed, Postpartum (non-breastfeeding) row.
    if pp["is_postpartum"] and not (profile.breastfeeding is True):
        if method_key in COMBINED_HORMONAL_METHODS:
            if pp["under_21_days"]:
                _update(4, "Less than 21 days postpartum (non-breastfeeding)",
                        "VTE risk is highest in first 21 days postpartum. "
                        "CHCs are absolutely contraindicated.")
            elif pp["21_to_42_days"]:
                # With VTE risk factors: Category 3; without: Category 2
                # Conservatively applying Category 3 without specific VTE info
                _update(3, "21 to 42 days postpartum (non-breastfeeding)",
                        "Category 3: Elevated VTE risk. Avoid CHC unless "
                        "provider confirms absence of other VTE risk factors.")
            elif pp["42_days_to_6_months"]:
                _update(2, "42 days to 6 months postpartum",
                        "Benefits generally outweigh risks for CHC use.")

    # ── POSTPARTUM — BREASTFEEDING ─────────────────────────────
    # Source: WHO MEC 6th Ed, Postpartum (breastfeeding) row.
    # Detailed breastfeeding + method matrix:
    if pp["bf_under_6_weeks"]:
        if method_key in COMBINED_HORMONAL_METHODS:
            _update(4, "Breastfeeding under 6 weeks postpartum",
                    "CHCs may suppress lactation and expose infant to estrogen. "
                    "ABSOLUTELY CONTRAINDICATED under 6 weeks while breastfeeding.")
        if method_key in ["pop"] + PROGESTOGEN_ONLY_INJECTABLES + IMPLANTS:
            _update(2, "Breastfeeding under 6 weeks postpartum",
                    "WHO MEC 6th Ed: Progestogen-only methods can generally be "
                    "used under 6 weeks postpartum while breastfeeding (Category 2).")
        if method_key == "cu_iud":
            if pp["under_48_hours"]:
                _update(1, "Breastfeeding, under 48 hours postpartum — Cu-IUD",
                        "Cu-IUD can be inserted within 48 hours postpartum "
                        "without restriction (Category 1).")
            elif pp["48h_to_4_weeks"]:
                _update(3, "Breastfeeding, 48h to 4 weeks postpartum — Cu-IUD",
                        "Category 3: IUD insertion between 48h and 4 weeks "
                        "postpartum carries elevated expulsion risk.")
            else:
                _update(1, "Breastfeeding, over 4 weeks — Cu-IUD",
                        "Cu-IUD can be used without restriction (Category 1).")
        if method_key == "lng_iud":
            if pp["under_48_hours"]:
                _update(2, "Breastfeeding, under 48 hours — LNG-IUD",
                        "LNG-IUD can generally be inserted under 48h (Category 2).")
            elif pp["48h_to_4_weeks"]:
                _update(3, "Breastfeeding, 48h to 4 weeks — LNG-IUD",
                        "Category 3: LNG-IUD insertion between 48h and 4 weeks.")
            else:
                _update(1, "Breastfeeding, over 4 weeks — LNG-IUD",
                        "LNG-IUD without restriction (Category 1).")

    elif pp["bf_6_weeks_to_6_months"]:
        if method_key in COMBINED_HORMONAL_METHODS:
            _update(3, "Breastfeeding 6 weeks to 6 months postpartum",
                    "CHCs: Category 3. Estrogen may reduce milk supply. "
                    "Progestogen-only methods preferred.")
        if method_key in ["pop"] + PROGESTOGEN_ONLY_INJECTABLES + IMPLANTS:
            _update(1, "Breastfeeding 6 weeks to 6 months",
                    "Progestogen-only methods: no restriction (Category 1).")

    elif pp["bf_over_6_months"]:
        if method_key in COMBINED_HORMONAL_METHODS:
            _update(2, "Breastfeeding over 6 months",
                    "CHCs: Category 2 after 6 months breastfeeding. "
                    "Benefits generally outweigh risks.")
        if method_key in ["pop"] + PROGESTOGEN_ONLY_INJECTABLES + IMPLANTS:
            _update(1, "Breastfeeding over 6 months",
                    "Progestogen-only: no restriction (Category 1).")

    # ── LACTATIONAL AMENORRHOEA METHOD (LAM) SPECIFIC RULES ───
    # LAM works ONLY when: < 6 months postpartum AND exclusively
    # breastfeeding AND menses have not returned.
    # Source: WHO MEC 6th Ed, LAM section.
    if method_key == "lam":
        if (profile.baby_age_months is not None and
                profile.baby_age_months >= 6):
            _update(4, "Baby age 6 months or older — LAM not effective",
                    "LAM CEASES to provide protection when baby reaches 6 months. "
                    "Switch to another method immediately.")
        if not (profile.breastfeeding_exclusively is True):
            _update(4, "Not exclusively breastfeeding — LAM not effective",
                    "LAM requires exclusive breastfeeding. Any supplemental "
                    "feeds or pacifiers reduce effectiveness to unacceptable level.")
        if not pp["is_postpartum"]:
            _update(4, "Not postpartum — LAM does not apply",
                    "LAM is only valid in the postpartum period.")

    # ── HYPERTENSION ───────────────────────────────────────────
    # Source: WHO MEC 6th Ed, Table 5, Hypertension section.
    # History of hypertension where BP CANNOT be evaluated: Category 3 for CHC.
    # BP adequately controlled on antihypertensives: Category 3 for CHC.
    # BP 140-159 / 90-99: Category 3 for CHC.
    # BP >= 160 / >= 100: Category 4 for CHC; Category 2 for POP, DMPA; Category 2 for implants.
    if bp == "severe":
        if method_key in COMBINED_HORMONAL_METHODS:
            _update(4, "Severe hypertension (BP ≥ 160/100 mmHg)",
                    "ABSOLUTE CONTRAINDICATION: Severe hypertension with CHC "
                    "carries unacceptable stroke and MI risk.")
        if method_key in ["pop"] + PROGESTOGEN_ONLY_INJECTABLES + IMPLANTS:
            _update(2, "Severe hypertension",
                    "Progestogen-only methods: advantages generally outweigh "
                    "risks in severe hypertension (Category 2).")
        if method_key in ["cu_iud", "lng_iud"]:
            _update(1, "Severe hypertension — IUD",
                    "IUDs: no restriction for hypertension (Category 1).")

    elif bp in ("mild", "reported_unknown_severity"):
        if method_key in COMBINED_HORMONAL_METHODS:
            _update(3, "Hypertension (mild or unknown severity)",
                    "Category 3: Mild hypertension with CHC. Provider judgment "
                    "required. Progestogen-only or IUD preferred.")
        if method_key in ["pop"] + PROGESTOGEN_ONLY_INJECTABLES + IMPLANTS:
            _update(2, "Hypertension",
                    "Progestogen-only methods with hypertension (Category 2).")

    # ── DIABETES ───────────────────────────────────────────────
    # Source: WHO MEC 6th Ed, Diabetes section.
    # Diabetes without vascular complications:
    #   CHC: Category 2 (non-insulin dependent) to Category 2 (insulin dependent)
    # Diabetes WITH nephropathy, retinopathy, neuropathy, or other vascular disease:
    #   CHC: Category 3-4
    #   Progestogen-only: Category 2
    #   IUD: Category 1
    if profile.diabetes:
        if profile.diabetes_with_vascular_complications:
            if method_key in COMBINED_HORMONAL_METHODS:
                _update(3, "Diabetes with vascular complications",
                        "Category 3/4: Diabetes with nephropathy, retinopathy, "
                        "or neuropathy. CHCs may worsen vascular disease.")
            if method_key in ["pop"] + PROGESTOGEN_ONLY_INJECTABLES + IMPLANTS:
                _update(2, "Diabetes with vascular complications",
                        "Progestogen-only methods: generally acceptable (Category 2).")
            if method_key in ["cu_iud", "lng_iud"]:
                _update(1, "Diabetes with vascular complications — IUD",
                        "IUDs: no restriction (Category 1).")
        else:
            if method_key in COMBINED_HORMONAL_METHODS:
                _update(2, "Diabetes (no vascular complications)",
                        "CHC: advantages generally outweigh risks for diabetes "
                        "without vascular complications (Category 2).")
            if method_key in ["pop"] + PROGESTOGEN_ONLY_INJECTABLES + IMPLANTS:
                _update(2, "Diabetes (no vascular complications)",
                        "Progestogen-only: acceptable (Category 2).")

    # ── MIGRAINE ───────────────────────────────────────────────
    # Source: WHO MEC 6th Ed, Headaches/Migraine section.
    # Migraine WITH aura at any age:
    #   CHC: Category 4 (absolute contraindication — stroke risk)
    #   POP: Category 2
    #   DMPA: Category 2
    #   Implants: Category 2
    # Migraine WITHOUT aura, age < 35:
    #   CHC: Category 2
    # Migraine WITHOUT aura, age >= 35:
    #   CHC: Category 3
    if profile.migraine_with_aura:
        if method_key in COMBINED_HORMONAL_METHODS:
            _update(4, "Migraine with aura",
                    "ABSOLUTE CONTRAINDICATION: Migraine with aura + CHC "
                    "carries severely elevated ischemic stroke risk. "
                    "This applies at any age.")
        if method_key in ["pop"] + PROGESTOGEN_ONLY_INJECTABLES + IMPLANTS:
            _update(2, "Migraine with aura",
                    "Progestogen-only methods: generally acceptable with "
                    "migraine with aura (Category 2).")

    elif profile.migraine_without_aura:
        if method_key in COMBINED_HORMONAL_METHODS:
            if profile.age_years is not None and profile.age_years >= 35:
                _update(3, "Migraine without aura, age 35 or older",
                        "Category 3: Migraine without aura in women 35+. "
                        "Increasing stroke risk warrants caution with CHC.")
            else:
                _update(2, "Migraine without aura, age under 35",
                        "CHC with migraine without aura under 35: "
                        "benefits generally outweigh risks (Category 2).")

    # ── CARDIOVASCULAR DISEASE ─────────────────────────────────
    # Source: WHO MEC 6th Ed, Heart disease sections.
    # Ischemic heart disease (MI, angina — current or history):
    #   CHC: Category 4 (current); Category 3/4 (history)
    # Stroke (CVA/TIA):
    #   CHC: Category 4
    # Multiple cardiovascular risk factors:
    #   CHC: Category 3/4 depending on combination
    if profile.ischemic_heart_disease:
        if method_key in COMBINED_HORMONAL_METHODS:
            _update(4, "Ischemic heart disease (current or history)",
                    "ABSOLUTE CONTRAINDICATION: CHC with ischemic heart disease. "
                    "Use progestogen-only or non-hormonal methods.")
        if method_key in ["pop"] + PROGESTOGEN_ONLY_INJECTABLES + IMPLANTS:
            _update(2, "Ischemic heart disease",
                    "Progestogen-only: generally acceptable (Category 2). "
                    "Monitor carefully.")

    if profile.history_of_stroke:
        if method_key in COMBINED_HORMONAL_METHODS:
            _update(4, "History of stroke or TIA",
                    "ABSOLUTE CONTRAINDICATION: CHC after stroke. "
                    "Estrogen increases thrombotic stroke risk.")
        if method_key in ["pop"] + PROGESTOGEN_ONLY_INJECTABLES + IMPLANTS:
            _update(2, "History of stroke",
                    "Progestogen-only: generally acceptable after stroke (Category 2).")

    if profile.heart_disease and not profile.ischemic_heart_disease:
        if method_key in COMBINED_HORMONAL_METHODS:
            _update(4, "Known heart disease",
                    "CHC contraindicated with known cardiac disease. "
                    "Refer to provider for specialist assessment.")

    # ── VTE (Venous Thromboembolism) ───────────────────────────
    # Source: WHO MEC 6th Ed, DVT/PE sections.
    # Current DVT/PE on anticoagulation:
    #   CHC: Category 4
    # History of DVT/PE (not current):
    #   CHC: Category 4
    # Progestogen-only with VTE:
    #   POP: Category 2
    #   DMPA: Category 2
    #   Implants: Category 2
    if profile.current_vte:
        if method_key in COMBINED_HORMONAL_METHODS:
            _update(4, "Current DVT/PE on anticoagulation",
                    "ABSOLUTE CONTRAINDICATION: Active VTE + CHC "
                    "unacceptably increases thrombotic risk.")
        if method_key in ["pop"] + PROGESTOGEN_ONLY_INJECTABLES + IMPLANTS:
            _update(2, "Current DVT/PE",
                    "Progestogen-only: generally acceptable (Category 2).")

    elif profile.history_of_vte:
        if method_key in COMBINED_HORMONAL_METHODS:
            _update(4, "History of DVT or PE",
                    "ABSOLUTE CONTRAINDICATION: Prior VTE + CHC.")
        if method_key in ["pop"] + PROGESTOGEN_ONLY_INJECTABLES + IMPLANTS:
            _update(2, "History of DVT or PE",
                    "Progestogen-only: generally acceptable (Category 2).")

    # ── LIVER DISEASE ──────────────────────────────────────────
    # Source: WHO MEC 6th Ed, Liver conditions sections.
    # Viral hepatitis (acute/flare):
    #   CHC, POP, implants: Category 3/4
    # Cirrhosis (compensated): Category 3 for CHC; Category 1 for Cu-IUD
    # Cirrhosis (decompensated): Category 4 for CHC
    # Benign liver tumour (focal nodular hyperplasia): Category 2
    # Hepatocellular carcinoma: Category 4 for all hormonal methods
    if profile.active_viral_hepatitis:
        if method_key in COMBINED_HORMONAL_METHODS:
            _update(4, "Active viral hepatitis (acute or flare)",
                    "ABSOLUTE CONTRAINDICATION: Active hepatitis + CHC. "
                    "Liver cannot metabolize estrogen safely.")
        if method_key in ["pop"] + PROGESTOGEN_ONLY_INJECTABLES + IMPLANTS:
            _update(3, "Active viral hepatitis",
                    "Category 3: Progestogen-only methods in active hepatitis. "
                    "Provider judgment required.")

    elif profile.liver_disease:
        if method_key in COMBINED_HORMONAL_METHODS:
            _update(4, "Liver disease",
                    "Category 4: CHC with liver disease. "
                    "All hormonal methods metabolized by liver.")
        if method_key in ["pop"] + PROGESTOGEN_ONLY_INJECTABLES + IMPLANTS:
            _update(3, "Liver disease",
                    "Category 3: Progestogen-only methods with liver disease. "
                    "Provider assessment required.")
        if method_key == "cu_iud":
            _update(1, "Liver disease — Cu-IUD",
                    "Cu-IUD: no restriction with liver disease (Category 1). "
                    "Non-hormonal and preferred option.")

    # ── BREAST CANCER ──────────────────────────────────────────
    # Source: WHO MEC 6th Ed, Breast cancer section.
    # Current breast cancer:
    #   All hormonal methods: Category 4
    # Past breast cancer (> 5 years disease-free):
    #   All hormonal methods: Category 3
    #   IUDs: Category 1 (Cu-IUD), Category 2 (LNG-IUD with caution)
    if profile.breast_cancer_current:
        if method_key in (COMBINED_HORMONAL_METHODS + ["pop"] +
                          PROGESTOGEN_ONLY_INJECTABLES + IMPLANTS + ["lng_iud"]):
            _update(4, "Current breast cancer",
                    "ABSOLUTE CONTRAINDICATION: Active breast cancer with any "
                    "hormonal method. Hormones may stimulate tumour growth.")
        if method_key == "cu_iud":
            _update(1, "Current breast cancer — Cu-IUD",
                    "Cu-IUD: no restriction (Category 1). Non-hormonal.")

    elif profile.breast_cancer_past_5_years:
        if method_key in (COMBINED_HORMONAL_METHODS + ["pop"] +
                          PROGESTOGEN_ONLY_INJECTABLES + IMPLANTS):
            _update(3, "History of breast cancer (past, disease-free > 5 years)",
                    "Category 3: Past breast cancer with hormonal methods. "
                    "Provider judgment required — residual risk of recurrence.")
        if method_key == "cu_iud":
            _update(1, "Past breast cancer — Cu-IUD",
                    "Cu-IUD preferred: non-hormonal, no restriction (Category 1).")

    # ── CERVICAL CANCER ────────────────────────────────────────
    # Source: WHO MEC 6th Ed, Cervical cancer section.
    # Cervical cancer awaiting treatment:
    #   CHC: Category 2 (benefits outweigh risks for short-term use)
    #   IUD: Category 4 for initiation (not appropriate before treatment)
    if profile.cervical_cancer:
        if method_key in ["cu_iud", "lng_iud"]:
            _update(4, "Cervical cancer awaiting treatment — IUD",
                    "IUD CONTRAINDICATED in cervical cancer awaiting treatment. "
                    "Risk of introducing infection before tumour treatment.")
        if method_key in COMBINED_HORMONAL_METHODS:
            _update(2, "Cervical cancer awaiting treatment",
                    "CHC: short-term use acceptable while awaiting treatment "
                    "(Category 2). Transition to non-hormonal after treatment begins.")

    # ── FIBROIDS DISTORTING UTERINE CAVITY ────────────────────
    # Source: WHO MEC 6th Ed, Uterine fibroids section.
    # Fibroids without distortion: Category 1 for IUDs
    # Fibroids WITH distortion of uterine cavity: Category 4 for IUDs
    if profile.fibroids_distorting_cavity:
        if method_key in ["cu_iud", "lng_iud"]:
            _update(4, "Uterine fibroids distorting the uterine cavity",
                    "ABSOLUTE CONTRAINDICATION: IUD cannot be safely inserted "
                    "when fibroids distort the uterine cavity. "
                    "Refer for gynaecological assessment.")

    # ── RECENT PID ─────────────────────────────────────────────
    # Source: WHO MEC 6th Ed, IUD sections.
    # Current PID or within past 3 months:
    #   IUD: Category 4
    if profile.recent_pid:
        if method_key in ["cu_iud", "lng_iud"]:
            _update(4, "Recent pelvic inflammatory disease (past 3 months)",
                    "ABSOLUTE CONTRAINDICATION: IUD initiation in current or "
                    "recent PID. Risk of ascending infection and sepsis. "
                    "Treat PID first, then reassess.")

    # ── HIGH STI RISK ─────────────────────────────────────────
    # Source: WHO MEC 6th Ed, Increased risk of STIs section.
    # Increased risk of STIs:
    #   Cu-IUD: Category 2 (benefits generally outweigh risks)
    #   LNG-IUD: Category 2
    # Note: Condoms are recommended concurrently for dual protection.
    if profile.high_sti_risk:
        if method_key in ["cu_iud", "lng_iud"]:
            _update(2, "High STI risk",
                    "Category 2: IUD with high STI risk. Benefits generally "
                    "outweigh risks. Dual protection with condoms strongly recommended.")

    # ── HIV ────────────────────────────────────────────────────
    # Source: WHO MEC 6th Ed, HIV/ART sections.
    # HIV positive + on ART — varies by ART regimen:
    #   NRTIs only: all hormonal methods Category 1 or 2
    #   NNRTIs with efavirenz: CHC Category 2, POP Category 2, NET-EN Cat 2, implants Cat 2
    #   NNRTIs without efavirenz: CHC Cat 1, POP Cat 1, DMPA Cat 1, implants Cat 1
    #   Protease inhibitors: CHC Cat 1, implants Cat 1
    #   IUD in HIV stage 1/2: Category 2
    #   IUD in HIV stage 3/4: Category 3 (LNG-IUD)
    # Women with HIV using PrEP: all hormonal methods Category 1
    if profile.prep_use:
        # PrEP users: all hormonal methods without restriction
        pass  # No restriction added — Category 1 baseline applies

    if profile.hiv_positive:
        art = profile.art_regimen or "unknown"
        hiv_stage = profile.hiv_stage or "stage_1_2"

        if art == "nnrti_efavirenz":
            if method_key in COMBINED_HORMONAL_METHODS + ["pop"] + ["net_en"] + IMPLANTS:
                _update(2, "HIV positive — NNRTI (efavirenz)",
                        "Category 2: Efavirenz reduces CHC, POP, NET-EN, implant "
                        "effectiveness. Benefits generally outweigh risks. "
                        "DMPA can be used without restriction.")
            if method_key in ["dmpa_im", "dmpa_sc"]:
                _update(1, "HIV positive — NNRTI (efavirenz) — DMPA",
                        "DMPA without restriction with efavirenz (Category 1).")
        elif art in ["nrti", "integrase_inhibitor", "protease_inhibitor",
                     "nnrti_no_efavirenz"]:
            # All hormonal methods without restriction
            pass  # Category 1 baseline

        # IUD eligibility by HIV stage
        if method_key in ["cu_iud", "lng_iud"]:
            if hiv_stage == "stage_3_4":
                if method_key == "lng_iud":
                    _update(3, "HIV stage 3 or 4 — LNG-IUD",
                            "Category 3: Advanced HIV disease with LNG-IUD. "
                            "Cu-IUD preferred as non-hormonal alternative.")
                else:
                    _update(2, "HIV stage 3 or 4 — Cu-IUD",
                            "Cu-IUD: generally acceptable in advanced HIV (Category 2). "
                            "Cu-IUD preferred over LNG-IUD.")
            else:
                _update(2, "HIV positive — IUD",
                        "IUD: generally acceptable in HIV stages 1-2 (Category 2).")

    # ── EPILEPSY — ENZYME-INDUCING ANTIEPILEPTICS ─────────────
    # Source: WHO MEC 6th Ed, Drug interactions / Epilepsy section.
    # Enzyme-inducing AEDs (phenytoin, carbamazepine, barbiturates,
    # primidone, topiramate, oxcarbazepine, lamotrigine):
    #   CHC: Category 3 (reduced effectiveness)
    #   POP: Category 3
    #   Implants: Category 3
    #   DMPA, Cu-IUD: Category 1 (not affected)
    if profile.epilepsy_on_enzyme_inducing_aeds:
        if method_key in COMBINED_HORMONAL_METHODS + ["pop"] + IMPLANTS:
            _update(3, "Epilepsy on enzyme-inducing antiepileptics",
                    "Category 3: Enzyme-inducing AEDs significantly reduce "
                    "effectiveness of hormonal methods. DMPA or Cu-IUD preferred.")
        if method_key in ["dmpa_im", "dmpa_sc", "net_en", "cu_iud"]:
            _update(1, "Epilepsy on enzyme-inducing AEDs — DMPA/Cu-IUD",
                    "DMPA and Cu-IUD not affected by enzyme-inducing AEDs (Category 1).")

    # ── KIDNEY DISEASE ─────────────────────────────────────────
    # Source: WHO MEC 6th Ed, Nephropathy section.
    if profile.severe_kidney_disease:
        if method_key in COMBINED_HORMONAL_METHODS:
            _update(3, "Severe kidney disease / nephropathy",
                    "Category 3: CHC with severe kidney disease. "
                    "Progestogen-only or non-hormonal preferred.")
        if method_key in ["pop"] + PROGESTOGEN_ONLY_INJECTABLES + IMPLANTS:
            _update(2, "Severe kidney disease",
                    "Progestogen-only with severe kidney disease (Category 2).")

    # ── MALE CONDOM — ALWAYS CATEGORY 1 (no medical contraindications) ──
    # Unless latex allergy (not asked in our intake, noted for completeness)
    if method_key == "male_condom":
        max_cat = max(max_cat, 1)

    # ── FEMALE CONDOM — ALWAYS CATEGORY 1 ─────────────────────
    if method_key == "female_condom":
        max_cat = max(max_cat, 1)

    # ── STERILIZATION — SPECIAL RULES ─────────────────────────
    # Female and male sterilization: Category 1 for most conditions.
    # Not assigned restrictions by MEC for medical conditions
    # (eligibility is determined by surgical risk assessment, not MEC).
    # Exception: active pelvic infection, unresolved cardiac issues.
    if method_key in ["female_ster", "male_ster"]:
        if profile.heart_disease or profile.ischemic_heart_disease:
            _update(3, "Cardiac disease — sterilization",
                    "Cardiac disease may increase anaesthetic/surgical risk. "
                    "Requires specialist clearance before sterilization.")

    # ── BUILD RESULT ────────────────────────────────────────────
    requires_provider = max_cat == 3
    is_contraindicated = max_cat == 4

    return MethodResult(
        method_name=method_key,
        method_display_name=METHOD_DISPLAY_NAMES[method_key],
        max_mec_category=max_cat,
        limiting_conditions=limiting,
        clinical_note=" | ".join(clinical_notes) if clinical_notes else "",
        requires_provider_judgment=requires_provider,
        is_contraindicated=is_contraindicated,
    )


def run_mec_assessment(profile: UserProfile) -> MECResult:
    """
    Run the complete WHO MEC 6th Edition assessment for all methods.

    This is the main entry point for the MEC engine.
    Call this function from the orchestrator after building the UserProfile.

    Parameters
    ----------
    profile : UserProfile
        Structured user profile from intake questions.

    Returns
    -------
    MECResult
        Categorized methods: recommended, provider_judgment, contraindicated.

    Usage
    -----
        result = run_mec_assessment(profile)
        safe_methods = [m.method_name for m in result.recommended_methods]
    """
    # Pre-compute shared values used by multiple rules
    bp = _classify_blood_pressure(
        profile.systolic_bp_mmhg,
        profile.diastolic_bp_mmhg,
        profile.hypertension,
    )
    pp = _compute_postpartum_status(
        profile.postpartum_days,
        profile.breastfeeding,
    )

    # Immediate referral trigger: known pregnancy
    if profile.pregnancy_status == "pregnant":
        return MECResult(
            refer_immediately=True,
            refer_reason=(
                "Client is pregnant or pregnancy cannot be excluded. "
                "Refer to antenatal care. No contraceptive method is initiated "
                "during confirmed pregnancy."
            ),
        )

    # Assess all methods
    recommended = []
    provider_judgment = []
    contraindicated = []
    flagged = []

    for method_key in ALL_METHODS:
        result = _assess_method(method_key, profile, pp, bp)

        if result.limiting_conditions:
            flagged.extend(result.limiting_conditions)

        if result.is_contraindicated:
            contraindicated.append(result)
        elif result.requires_provider_judgment:
            provider_judgment.append(result)
        else:
            recommended.append(result)

    # Sort recommended by category (Category 1 before Category 2)
    recommended.sort(key=lambda m: m.max_mec_category)

    return MECResult(
        recommended_methods=recommended,
        provider_judgment_methods=provider_judgment,
        contraindicated_methods=contraindicated,
        flagged_conditions=list(set(flagged)),
    )


def format_mec_result_for_llm(result: MECResult,
                               language: str = "english") -> str:
    """
    Format MEC results as a structured string for the RAG + LLM pipeline.

    The LLM receives this as part of its system prompt context.
    It uses only the methods listed here — never recommends methods
    that are not in the recommended_methods list.

    Parameters
    ----------
    result : MECResult
        Output from run_mec_assessment().
    language : str
        'english' or 'swahili'. (LLM handles translation — this sets framing.)

    Returns
    -------
    str
        Formatted string for injection into LLM context.
    """
    if result.refer_immediately:
        return (
            f"[MEC RESULT — IMMEDIATE REFERRAL REQUIRED]\n"
            f"Reason: {result.refer_reason}\n"
            f"Instruction: Do NOT recommend any contraceptive method. "
            f"Tell the client to visit a health facility immediately for "
            f"antenatal care and contraceptive counselling after delivery."
        )

    lines = ["[MEC RESULT — WHO Medical Eligibility Criteria 6th Edition 2025]"]
    lines.append("")

    lines.append("METHODS SAFE TO RECOMMEND (Category 1 or 2):")
    if result.recommended_methods:
        for m in result.recommended_methods:
            cat_label = "No restriction" if m.max_mec_category == 1 else "Generally acceptable"
            lines.append(f"  - {m.method_display_name} (Category {m.max_mec_category}: {cat_label})")
    else:
        lines.append("  NONE — All methods have restrictions for this profile. "
                     "Refer to provider.")

    lines.append("")
    lines.append("METHODS REQUIRING PROVIDER JUDGMENT (Category 3 — do not recommend directly):")
    if result.provider_judgment_methods:
        for m in result.provider_judgment_methods:
            cond = ", ".join(m.limiting_conditions[:2])
            lines.append(f"  - {m.method_display_name}: {cond}")
    else:
        lines.append("  None")

    lines.append("")
    lines.append("ABSOLUTELY CONTRAINDICATED (Category 4 — never recommend):")
    if result.contraindicated_methods:
        for m in result.contraindicated_methods:
            cond = ", ".join(m.limiting_conditions[:2])
            lines.append(f"  - {m.method_display_name}: {cond}")
    else:
        lines.append("  None")

    lines.append("")
    lines.append("INSTRUCTION TO LLM:")
    lines.append("  You MUST only recommend methods from the 'safe to recommend' list above.")
    lines.append("  You MUST NOT recommend any method from the 'contraindicated' list.")
    lines.append("  For 'provider judgment' methods, tell the client to discuss with a "
                 "health worker before using that method.")
    lines.append("  Always recommend male or female condoms alongside any other method "
                 "if high STI risk is flagged.")

    return "\n".join(lines)


def export_mec_table_as_json() -> str:
    """
    Export a structured JSON summary of all MEC rules in this engine.
    Useful for documentation, auditing, and open science publishing.

    Returns
    -------
    str
        JSON string of method: {condition: category} mapping.
    """
    table = {
        "source": "WHO Medical Eligibility Criteria 6th Edition, 2025",
        "kenya_supplement": "Kenya National FP Guideline 7th Edition, 2025",
        "generated_by": "ChaguoAI who_mec_engine.py",
        "methods_covered": list(METHOD_DISPLAY_NAMES.keys()),
        "conditions_assessed": [
            "pregnancy", "age", "smoking_age_combination",
            "postpartum_non_breastfeeding", "postpartum_breastfeeding",
            "lactational_amenorrhoea_method",
            "hypertension_mild", "hypertension_severe",
            "diabetes_no_complications", "diabetes_with_vascular_complications",
            "migraine_with_aura", "migraine_without_aura",
            "ischemic_heart_disease", "history_of_stroke", "heart_disease",
            "current_vte", "history_of_vte",
            "active_viral_hepatitis", "liver_disease",
            "breast_cancer_current", "breast_cancer_past",
            "cervical_cancer",
            "fibroids_distorting_cavity",
            "recent_pid",
            "high_sti_risk",
            "hiv_positive_by_art_regimen",
            "epilepsy_enzyme_inducing_aeds",
            "severe_kidney_disease",
        ],
        "category_definitions": {
            "1": "No restriction. Method can be used.",
            "2": "Advantages generally outweigh risks. Method can be used.",
            "3": "Risks usually outweigh advantages. Provider judgment required.",
            "4": "Unacceptable health risk. Method MUST NOT be used.",
        },
        "safety_gate_rules": {
            "recommended": "Category 1 or 2 — safe to include in recommendation",
            "provider_judgment": "Category 3 — do not recommend without provider",
            "contraindicated": "Category 4 — never include in recommendation",
        }
    }
    return json.dumps(table, indent=2)
