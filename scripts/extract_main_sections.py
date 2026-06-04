from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "mhc-backend"
lines = (BACKEND / "main.py").read_text(encoding="utf-8").splitlines(keepends=True)


def write(path: str, start: int, end: int, prefix: str = "") -> None:
    target = BACKEND / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(prefix + "".join(lines[start - 1 : end]), encoding="utf-8")
    print(f"wrote {path}: {end - start + 1} lines")


write(
    "whatsapp/constants.py",
    194,
    216,
    '"""WhatsApp survey menus and translations."""\n\nfrom __future__ import annotations\n\n',
)
with (BACKEND / "whatsapp/constants.py").open("a", encoding="utf-8") as handle:
    handle.write("".join(lines[309:446]))

write(
    "whatsapp/helpers.py",
    218,
    293,
    (
        '"""WhatsApp helper functions for menus and method match dispatch."""\n\n'
        "from __future__ import annotations\n\n"
        "import threading\n\n"
        "from db_client import get_db\n"
        "from method_match_tasks import process_whatsapp_method_match_job\n"
        "from task_queue import (\n"
        "    TRIAGE_JOB_FAILURE_TTL_SECONDS,\n"
        "    TRIAGE_JOB_RESULT_TTL_SECONDS,\n"
        "    TRIAGE_JOB_TIMEOUT_SECONDS,\n"
        "    get_triage_queue,\n"
        ")\n"
        "from twilio_messaging import send_whatsapp_options\n"
        "from user_profile_mapper import serializable_user_snapshot\n"
        "from whatsapp.constants import LANGUAGE_OPTIONS, MAIN_MENU_OPTIONS, STRINGS\n\n"
    ),
)

write(
    "whatsapp/flow.py",
    447,
    814,
    '"""Inbound WhatsApp conversation state machine."""\n\nfrom __future__ import annotations\n\n',
)

write("routes/_public_body.py", 120, 126)
with (BACKEND / "routes/_public_body.py").open("a", encoding="utf-8") as handle:
    handle.write("".join(lines[295:308]))
    handle.write("".join(lines[815:821]))
    handle.write("".join(lines[847:851]))

write("routes/_admin_body.py", 825, 938)
write("routes/_provider_body.py", 942, 1747)

print("extract complete")
