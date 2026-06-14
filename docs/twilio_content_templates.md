# Twilio WhatsApp Content Templates — ChaguoAI

Interactive WhatsApp buttons **require approved Twilio Content templates**. Each template has a **fixed number of option slots**. Sending the wrong count fails silently and ChaguoAI falls back to numbered text.

## Why some questions had buttons and others did not

| Question | Options | Template needed |
|----------|---------|-----------------|
| Main menu | 5 | **List picker × 5** |
| Language menu | 4 | **List picker × 4** |
| Q3, Q8, Q9, Q12 | 2 (Yes/No) | **Quick reply × 2** |
| Q2, Q5, Q7, Q10, Q11 | 3 | **Quick reply × 3** |
| Q4 (children count) | 4 | **List picker × 4** |
| Q9a (stop reason) | 4 | **List picker × 4** |
| Q13 (methods to avoid) | 5 | **List picker × 5** |
| Q6 (health conditions) | 7 | **List picker × 7** |

If you only created a **3-button quick-reply** template, Q5 works but **Q3 does not** (2 options ≠ 3 slots).

---

## Step 1 — Open Twilio Content Template Builder

1. [Twilio Console](https://console.twilio.com/) → **Messaging** → **Content Template Builder**
2. Click **Create new template**
3. Choose **WhatsApp** as the channel
4. Pick the template type below for each size

---

## Step 2 — Create five templates

### Template A: Quick Reply — 2 buttons

- **Type:** `twilio/quick-reply`
- **Name:** `chaguoai_quick_reply_2`
- **Body:** `{{body}}`
- **Buttons:**
  - Button 1: `{{option_1}}` → payload `{{option_1_payload}}`
  - Button 2: `{{option_2}}` → payload `{{option_2_payload}}`
- **Do NOT add a third button**
- Submit for WhatsApp approval (sandbox is usually instant)
- Copy **Content SID** → `.env`:

```env
TWILIO_CONTENT_QUICK_REPLY_2_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Used for:** Q3, Q8, Q9, Q12 (Yes/No)

---

### Template B: Quick Reply — 3 buttons

- **Type:** `twilio/quick-reply`
- **Name:** `chaguoai_quick_reply_3`
- **Body:** `{{body}}`
- **Buttons:** 3 buttons with `{{option_1}}` … `{{option_3}}` and payloads `{{option_1_payload}}` … `{{option_3_payload}}`

```env
TWILIO_CONTENT_QUICK_REPLY_3_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Used for:** Q2, Q5, Q7, Q10 (partner), Q11

---

### Template C: List Picker — 4 rows

- **Type:** `twilio/list-picker`
- **Name:** `chaguoai_list_4`
- **Body:** `{{body}}`
- **List button label:** `{{button}}`
- **Rows:** exactly **4** rows:
  - Row 1: `{{option_1}}` / `{{option_1_payload}}`
  - Row 2: `{{option_2}}` / `{{option_2_payload}}`
  - Row 3: `{{option_3}}` / `{{option_3_payload}}`
  - Row 4: `{{option_4}}` / `{{option_4_payload}}`

```env
TWILIO_CONTENT_LIST_PICKER_4_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Used for:** Language menu (4), Q4 children count (4), Q9a (4)

---

### Template D: List Picker — 5 rows

- **Type:** `twilio/list-picker`
- **Name:** `chaguoai_list_5`
- **Body:** `{{body}}`
- **List button:** `{{button}}`
- **Rows:** exactly **5** rows (`option_1` … `option_5` + payloads)

```env
TWILIO_CONTENT_LIST_PICKER_5_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Used for:** Main menu (5), Q13 methods to avoid (5)

---

### Template E: List Picker — 7 rows

- **Type:** `twilio/list-picker`
- **Name:** `chaguoai_list_7`
- **Body:** `{{body}}`
- **List button:** `{{button}}`
- **Rows:** exactly **7** rows (`option_1` … `option_7` + payloads)

```env
TWILIO_CONTENT_LIST_PICKER_7_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Used for:** Q6 health conditions (7)

---

## Step 3 — Full `.env` block

```env
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886

TWILIO_CONTENT_QUICK_REPLY_2_SID=HX...
TWILIO_CONTENT_QUICK_REPLY_3_SID=HX...
TWILIO_CONTENT_LIST_PICKER_4_SID=HX...
TWILIO_CONTENT_LIST_PICKER_5_SID=HX...
TWILIO_CONTENT_LIST_PICKER_7_SID=HX...

# Optional legacy aliases (same as _3 and _5 if you prefer one name)
# TWILIO_CONTENT_QUICK_REPLY_SID=HX...
# TWILIO_CONTENT_LIST_PICKER_SID=HX...
```

Restart Flask after changing `.env`.

---

## Step 4 — Verify at startup

When `main.py` starts, look for:

```text
[WhatsApp Templates] quick_reply_2=set quick_reply_3=set list_picker_4=set list_picker_5=set list_picker_7=set
```

If any say `missing`, those questions will use numbered text fallback.

When a send fails, logs show:

```text
Twilio Content Error: ... (2 options, quick_reply, SID=HX...)
```

---

## Step 5 — Test each size

Send `hi` on WhatsApp and walk through:

1. Language list (4 rows) — tap opens list
2. Main menu (5 rows)
3. Method Match → confirm Q3 shows **2 tappable buttons**, Q4 shows **list with 4 items**, Q13 shows **list with 5**

---

## Label length limits

ChaguoAI truncates labels automatically:

- Quick reply buttons: **20 characters**
- List row titles: **24 characters**

Long Swahili/French labels are shortened with `…` so Twilio does not reject the message.

---

## FAQ

**Can one list template handle 4 and 5 options?**  
No. Twilio expects every variable slot defined in the template. Use separate 4-row and 5-row templates.

**Sandbox vs production**  
Templates must be approved for your WhatsApp sender. Sandbox uses the sandbox number; production uses your approved Business number.

**Buttons still missing after setup?**  
1. Confirm all 5 SIDs in `.env`  
2. Restart the server  
3. Check terminal for `Twilio Content Error`  
4. In Twilio Console → Content → open template → verify variable names match exactly (`option_1`, not `Option_1`)
