"""
USSD flow — aligned with WhatsApp Method Match (13 questions, shared clinical pipeline).
Supports English and Kiswahili.
"""

from firebase_admin import firestore

from clinical_pipeline import generate_ussd_recommendation
from db_client import get_db
from geography import (
    admin_area_label,
    build_admin_area_firestore_fields,
    build_country_firestore_fields,
    is_valid_country_input,
    is_valid_location_input,
    normalize_country,
)
from method_categories import classify_method_category_primary
from user_profile_mapper import map_ussd_responses_to_firestore_user

USSD_STRINGS = {
    "english": {
        "welcome": "CON ChaguoAI\n1.Method Match\n2.Report Side Effects\n3.Check Method\n4.Contact CHW\n5.Change Language",
        "language": "CON ChaguoAI\n1.English\n2.Kiswahili",
        "side_effect_prompt": "CON Describe your side effect briefly:",
        "side_effect_saved": "END Side effect recorded. A health worker will review it.",
        "no_match": "END No Method Match found. Dial 1 to start Method Match.",
        "hotline": "END Call 0800-720-593 for clinical support.",
        "invalid": "END Invalid choice. Dial again.",
        "match_prefix": "END Match: ",
        "match_error": "END We saved your answers but could not analyze now. Try again later.",
        "geo_country": "CON Analytics only: Enter your country (e.g. Kenya):",
        "geo_area": "CON Analytics only: Enter your county/region:",
        "geo_invalid": "END Invalid entry. Dial again and enter a valid country or region.",
        "q1": "CON Q1/15: How old are you? (number e.g. 25)",
        "q2": "CON Q2/13: Last period / pregnancy?\n1.Within 4 wks\n2.Unsure\n3.Pregnant",
        "q3": "CON Q3/13: Baby under 6 months?\n1.Yes\n2.No",
        "q3a": "CON Q3a: Breastfeeding only?\n1.Yes\n2.No",
        "q4": "CON Q4/13: Living children? (number e.g. 0)",
        "q5": "CON Q5/13: Want more children?\n1.Yes in 2 yrs\n2.Yes later\n3.No",
        "q6": "CON Q6/13: Health conditions? (e.g. 1,2 or 7)\n1.BP 2.Diabetes 3.Heart 4.Liver 5.Cancer 6.Migraine 7.None",
        "q7": "CON Q7/13: Living with HIV?\n1.Yes\n2.No\n3.Prefer not say",
        "q8": "CON Q8/13: Do you smoke?\n1.Yes\n2.No",
        "q9": "CON Q9/13: Used contraception before?\n1.Yes\n2.No",
        "q9a": "CON Q9a: Did you stop?\n1.Still using\n2.Side effects\n3.Other\n4.Switched",
        "q10": "CON Q10/13: Partner supports FP?\n1.Yes\n2.No\n3.No partner",
        "q11": "CON Q11/13: Facility access?\n1.Easy\n2.Sometimes hard\n3.Very hard",
        "q12": "CON Q12/13: STI protection concern?\n1.Yes\n2.No",
        "q13": "CON Q13/13: Methods to avoid? (e.g. 1,2 or 5)\n1.Pills 2.Injectables 3.IUD 4.Implants 5.None",
    },
    "swahili": {
        "welcome": "CON ChaguoAI\n1.Njia Inayonifaa\n2.Ripoti Madhara\n3.Angalia Njia\n4.Piga CHW\n5.Badilisha Lugha",
        "language": "CON ChaguoAI\n1.Kiingereza\n2.Kiswahili",
        "side_effect_prompt": "CON Eleza madhara yako kwa ufupi:",
        "side_effect_saved": "END Madhara yamehifadhiwa. Mhudumu ataangalia.",
        "no_match": "END Hakuna mapendekezo. Piga 1 kuanza Method Match.",
        "hotline": "END Piga 0800-720-593 kwa msaada.",
        "invalid": "END Chaguo si sahihi. Piga tena.",
        "match_prefix": "END Mapendekezo: ",
        "match_error": "END Tumehifadhi majibu yako lakini tuchambua baadaye.",
        "geo_country": "CON Kwa takwimu tu: Andika nchi yako (mf. Kenya):",
        "geo_area": "CON Kwa takwimu tu: Andika kaunti/eneo lako:",
        "geo_invalid": "END Ulichoandika si sahihi. Piga tena.",
        "q1": "CON Q1/15: Una umri gani? (nambari mf. 25)",
        "q2": "CON Q2/13: Hedhi / ujauzito?\n1.Ndani wiki 4\n2.Sina uhakika\n3.Nina mimba",
        "q3": "CON Q3/13: Mtoto chini miezi 6?\n1.Ndio\n2.Hapana",
        "q3a": "CON Q3a: Unanyonyesha pekee?\n1.Ndio\n2.Hapana",
        "q4": "CON Q4/13: Watoto wangapi? (nambari mf. 0)",
        "q5": "CON Q5/13: Unataka watoto zaidi?\n1.Ndio miaka 2\n2.Ndio baadaye\n3.Hapana",
        "q6": "CON Q6/13: Hali ya kiafya? (mf. 1,2 au 7)\n1.BP 2.Kisukari 3.Moyo 4.Ini 5.Saratani 6.Migraine 7.Hakuna",
        "q7": "CON Q7/13: Unaishi na HIV?\n1.Ndio\n2.Hapana\n3.Sipendelei",
        "q8": "CON Q8/13: Unavuta sigara?\n1.Ndio\n2.Hapana",
        "q9": "CON Q9/13: Umewahi kutumia uzazi?\n1.Ndio\n2.Hapana",
        "q9a": "CON Q9a: Uliacha?\n1.Bado\n2.Madhara\n3.Nyingine\n4.Nilibadilisha",
        "q10": "CON Q10/13: Mpenzi anaunga mkono?\n1.Ndio\n2.Hapana\n3.Sina mpenzi",
        "q11": "CON Q11/13: Kufika kituo cha afya?\n1.Rahisi\n2.Wakati mwingine\n3.Ngumu sana",
        "q12": "CON Q12/13: Wajali STI?\n1.Ndio\n2.Hapana",
        "q13": "CON Q13/13: Njia za kuepuka? (mf. 1,2 au 5)\n1.Pills 2.Injectables 3.IUD 4.Implants 5.Hakuna",
    },
}


def _t(lang: str, key: str) -> str:
    return USSD_STRINGS.get(lang, USSD_STRINGS["english"]).get(key, USSD_STRINGS["english"][key])


def _ussd_geo_area_prompt(lang: str, country: str) -> str:
    label = admin_area_label(country)
    if lang == "swahili":
        return f"CON Kwa takwimu tu: Andika {label} yako:"
    return f"CON Analytics only: Enter your {label}:"


def _get_lang(db, phone: str) -> str | None:
    if not db:
        return "english"
    doc = db.collection("contraceptive_users").document(phone).get()
    if doc.exists:
        return doc.to_dict().get("language")
    return None


def _save_lang(db, phone: str, lang: str):
    if db:
        db.collection("contraceptive_users").document(phone).set({
            "phone": phone,
            "language": lang,
            "source": "ussd",
        }, merge=True)


def process_method_match(answers, phone_number, db):
    lang = _get_lang(db, phone_number) or "english"
    s = USSD_STRINGS[lang]
    ans_index = 0
    responses = {}

    def need(key):
        return s[key]

    if ans_index >= len(answers):
        return need("geo_country")
    country_text = answers[ans_index]
    if not is_valid_country_input(country_text):
        return need("geo_invalid")
    normalized = normalize_country(country_text)
    responses.update(build_country_firestore_fields(normalized, source="ussd"))
    ans_index += 1

    if ans_index >= len(answers):
        return _ussd_geo_area_prompt(lang, normalized.canonical)
    area_text = answers[ans_index]
    if not is_valid_location_input(area_text):
        return need("geo_invalid")
    responses.update(
        build_admin_area_firestore_fields(area_text, normalized.canonical, source="ussd")
    )
    ans_index += 1

    if ans_index >= len(answers):
        return need("q1")
    responses["age"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q2")
    responses["last_period"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q3")
    q3_ans = answers[ans_index]
    responses["baby_under_6m"] = q3_ans
    ans_index += 1

    if q3_ans == "1":
        if ans_index >= len(answers):
            return need("q3a")
        responses["breastfeeding"] = answers[ans_index]
        ans_index += 1

    if ans_index >= len(answers):
        return need("q4")
    responses["children"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q5")
    responses["more_children"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q6")
    responses["health"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q7")
    responses["hiv"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q8")
    responses["smoke"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q9")
    q9_ans = answers[ans_index]
    responses["used_before"] = q9_ans
    ans_index += 1

    if q9_ans == "1":
        if ans_index >= len(answers):
            return need("q9a")
        responses["stop_reason"] = answers[ans_index]
        ans_index += 1

    if ans_index >= len(answers):
        return need("q10")
    responses["partner"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q11")
    responses["facility_access"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q12")
    responses["sti"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q13")
    responses["prefer_not"] = answers[ans_index]

    user_doc = map_ussd_responses_to_firestore_user(responses, phone_number, lang)
    try:
        print(f"[{phone_number}] USSD: running shared clinical pipeline...")
        reply_text, mec_text = generate_ussd_recommendation(user_doc)
        if db:
            db.collection("contraceptive_users").document(phone_number).set({
                **user_doc,
                "matched_method": reply_text,
                "method_category_primary": classify_method_category_primary(reply_text),
                "latest_mec_text": mec_text,
                "stage": "REGISTERED",
                "registered_at": firestore.SERVER_TIMESTAMP,
                "method_match_status": "completed",
                "source": "ussd",
            }, merge=True)
        return f"{_t(lang, 'match_prefix')}{reply_text}"
    except Exception as exc:
        print(f"USSD ERROR: {exc}")
        if db:
            db.collection("contraceptive_users").document(phone_number).set({
                **user_doc,
                "stage": "REGISTERED",
                "method_match_status": "failed",
                "method_match_error": str(exc),
                "registered_at": firestore.SERVER_TIMESTAMP,
            }, merge=True)
        return _t(lang, "match_error")


def handle_ussd_request(session_id, service_code, phone_number, text, db=None):
    db = db or get_db()
    text_array = text.split("*") if text else []

    lang = _get_lang(db, phone_number)

    if lang is None:
        if len(text_array) == 0:
            return _t("english", "language")
        if len(text_array) == 1 and text_array[0] in ("1", "2"):
            chosen = "english" if text_array[0] == "1" else "swahili"
            _save_lang(db, phone_number, chosen)
            return _t(chosen, "welcome")
        return _t("english", "language")

    if len(text_array) == 0:
        return _t(lang, "welcome")

    if text_array[0] == "5":
        if len(text_array) == 1:
            return _t(lang, "language")
        if len(text_array) == 2 and text_array[1] in ("1", "2"):
            chosen = "english" if text_array[1] == "1" else "swahili"
            _save_lang(db, phone_number, chosen)
            return _t(chosen, "welcome")
        return _t(lang, "language")

    choice = text_array[0]

    if choice == "1":
        return process_method_match(text_array[1:], phone_number, db)
    if choice == "2":
        if len(text_array) == 1:
            return _t(lang, "side_effect_prompt")
        if db:
            try:
                db.collection("contraceptive_users").document(phone_number).collection("side_effects").add({
                    "report": text_array[1],
                    "language": lang,
                    "timestamp": firestore.SERVER_TIMESTAMP,
                    "source": "ussd",
                })
            except Exception:
                pass
        return _t(lang, "side_effect_saved")
    if choice == "3":
        if db:
            try:
                user_doc = db.collection("contraceptive_users").document(phone_number).get()
                if user_doc.exists:
                    method = user_doc.to_dict().get("matched_method")
                    if method:
                        short = method[:120] + ("..." if len(method) > 120 else "")
                        return f"END {short}"
            except Exception:
                pass
        return _t(lang, "no_match")
    if choice == "4":
        return _t(lang, "hotline")

    return _t(lang, "invalid")
