# 🧱 DueNote architecture

How DueNote works under the hood, with one diagram per idea.

**Contents:** [1. Module map](#1-module-map) · [2. The four steps](#2-the-four-steps) · [3. Reading a page with Gemma 4](#3-reading-a-page-with-gemma-4) · [4. From a written amount to a counted rupee](#4-from-a-written-amount-to-a-counted-rupee) · [5. Customer states](#5-customer-states) · [6. Why reminders never go stale](#6-why-reminders-never-go-stale) · [7. Recording a payment](#7-recording-a-payment) · [8. Data model](#8-data-model) · [9. Design decisions](#9-design-decisions)

---

## 1. Module map

```mermaid
flowchart TB
    subgraph Browser["🌐 Browser (laptop or phone)"]
        USER["🧑‍💼 Shop owner"]
    end

    subgraph App["🖥️ app.py: Streamlit web app"]
        CAP["1 · Capture"]
        REV["2 · Review"]
        COL["3 · Collect"]
        HIS["4 · History"]
    end

    subgraph Modules["Python modules"]
        IMG["images.py<br/>15 MB / 40 MP limits<br/>EXIF rotation · resize to 1600 px"]
        EXT["extract.py<br/>prompt · JSON schema check<br/>one repair attempt · rows → entries"]
        PRV["provider.py<br/>lazy Gemma client · error types<br/>retries · race both models"]
        REM["reminders.py<br/>Urdu / Roman templates<br/>amount check · phone check"]
        STO["store.py<br/>SQLite: pages, entries,<br/>payments, contacts, history"]
    end

    LED["🧮 skills/duenote/scripts/ledger.py<br/>money parsing · balances · revisions<br/>(standard library only)"]
    SKILL["🧩 SKILL.md + balances.py<br/>portable agent skill"]
    GEM[("☁️ Gemma 4<br/>Gemini API")]
    DB[("💾 SQLite file<br/>or in-memory demo")]

    USER <--> App
    CAP --> IMG
    CAP --> EXT --> PRV --> GEM
    REV --> LED
    COL --> REM
    COL --> STO
    HIS --> STO
    STO --> DB
    EXT --> LED
    REM --> LED
    STO --> LED
    SKILL --> LED

    classDef core fill:#E6F4EA,stroke:#34A853,color:#1a1a1a
    classDef ext fill:#E8F0FE,stroke:#4285F4,color:#1a1a1a
    class LED core
    class GEM ext
```

**Key idea:** `ledger.py` is the **only** place money is calculated. The app, the database layer and the agent skill all use it, so they can never disagree.

---

## 2. The four steps

```mermaid
flowchart TD
    START(["Open DueNote"]) --> SRC{"Where is the page?"}
    SRC -- "Sample" --> REPLAY["🧪 Replay verified<br/>transcription<br/>(no AI, no internet)"]
    SRC -- "Photos" --> UP["📁 Upload 1–10 photos<br/>or 📷 camera"]
    UP --> CHECK{"Valid image?"}
    CHECK -- "No" --> ERR1["⚠️ Explain the problem<br/>(other files continue)"]
    CHECK -- "Yes" --> READ["🤖 Read with Gemma 4<br/>one page or Read all"]
    READ --> OK{"Read OK?"}
    OK -- "No" --> ERR2["⚠️ Friendly error<br/>retry later · old results<br/>never shown"]
    OK -- "Yes" --> REVIEW
    REPLAY --> REVIEW["🔍 Review rows<br/>next to the photo"]
    REVIEW --> EVID["Compare page's written<br/>balances & total<br/>with Python"]
    EVID --> CONF["✅ Confirm page"]
    CONF --> MORE{"More uploaded<br/>pages waiting?"}
    MORE -- "Yes" --> REVIEW
    MORE -- "No" --> COLLECT["💰 Collect<br/>balances · payments ·<br/>reminders · fixes"]
    COLLECT --> HISTORY["📜 History<br/>events · CSV export"]
```

You can always move between steps with **← Back / Next →**. Confirming never gets stuck: unclear rows are stored as *Needs checking* and fixed later in Collect.

---

## 3. Reading a page with Gemma 4

```mermaid
sequenceDiagram
    autonumber
    actor Owner
    participant App as app.py
    participant Img as images.py
    participant Ext as extract.py
    participant Prv as provider.py
    participant A as gemma-4-26b-a4b-it
    participant B as gemma-4-31b-it

    Owner->>App: Read with Gemma 4
    App->>App: Already read this session? → reuse (instant)
    App->>Img: resize photo (longest side 1600 px)
    App->>Ext: extract_page(photo)
    Ext->>Prv: prompt + photo
    par Race both models
        Prv->>A: generate (up to 6 tries, backoff 1·2·4·8 s)
    and
        Prv->>B: generate (up to 6 tries)
    end
    A-->>Prv: first valid answer wins
    Prv-->>Ext: text
    Ext->>Ext: find JSON · check schema
    alt Malformed JSON
        Ext->>Prv: one repair request (no new values)
        Prv-->>Ext: fixed JSON or error
    end
    Ext-->>App: rows (raw text kept)
    App->>App: rows → entries via ledger.py
    App-->>Owner: "✅ N amounts found · 55 s"
```

| Failure | What the owner sees |
|---|---|
| No API key | "No Gemini API key… or use Sample replay" |
| 401 / 403 | "The API key was rejected" |
| 429 | "Too many requests, wait a minute" |
| 5xx / busy | Retried automatically on both models, then "Google's servers are busy" |
| Bad JSON twice | "Model output was not valid JSON", with nothing half-saved |

**Speed note:** the photo costs only ~620 tokens. Time goes on Gemma's hidden thinking, which the API won't let us switch off for Gemma, so the prompt says *"simple copying task, answer directly"*. In our measurement that cut thinking ~40% (Urdu page 180 s → 66 s together with racing).

---

## 4. From a written amount to a counted rupee

```mermaid
flowchart LR
    RAW["Written amount<br/>e.g. 'Rs. ۱,۲۵۰'"] --> DIG["Urdu/Arabic digits<br/>→ 0-9"]
    DIG --> CUR["Strip Rs · PKR · روپے · /-"]
    CUR --> NEG{"Negative?"}
    NEG -- "Yes" --> BAD["🟠 Needs checking<br/>'negative amount'"]
    NEG -- "No" --> FMT{"Well-formed?<br/>1150 · 1,150 ·<br/>1,50,000 · 750.50"}
    FMT -- "No" --> BAD2["🟠 Needs checking<br/>'unreadable amount'<br/>raw text kept"]
    FMT -- "Yes" --> DEC["Decimal('1250.00')"]
    DEC --> DIR{"Owed or paid<br/>known?"}
    DIR -- "No" --> BAD3["🟠 Needs checking<br/>'direction unclear'"]
    DIR -- "Yes" --> OKE["✅ Counted in balances"]

    classDef warn fill:#FFF4E5,stroke:#F29900,color:#1a1a1a
    classDef good fill:#E6F4EA,stroke:#34A853,color:#1a1a1a
    class BAD,BAD2,BAD3 warn
    class OKE good
```

Written **remaining balances** and **page totals** never become debts. They're only compared with Python's result, and any difference is shown as a warning.

---

## 5. Customer states

```mermaid
stateDiagram-v2
    direction LR
    [*] --> NeedsChecking: any row unclear
    [*] --> Due: balance > 0
    [*] --> Settled: balance = 0
    [*] --> Credit: balance < 0

    NeedsChecking --> Due: owner fixes rows
    Due --> Overdue: saved due date passes
    Due --> Settled: full payment
    Due --> Credit: overpayment
    Overdue --> Settled: full payment
    Due --> Due: partial payment

    note right of Due
        📲 Only Due / Overdue customers
        get a WhatsApp reminder
    end note
```

| State | Badge | Reminder? |
|---|---|---|
| Needs checking | 🟠 | ❌ (unlocks after fixing) |
| Due | 🔴 | ✅ |
| Overdue | ⏰ | ✅ (only with a saved, passed due date) |
| Settled | 🟢 | ❌ |
| Credit | 🔵 | ❌ |

---

## 6. Why reminders never go stale

```mermaid
flowchart TD
    CHANGE["Any change:<br/>payment · row fix · alias ·<br/>shop name · notebook type"] --> REV["ledger.revision()<br/>new fingerprint of<br/>all money + context"]
    REV --> CMP{"Draft's revision<br/>= current?"}
    CMP -- "Yes" --> KEEP["Keep owner's wording"]
    CMP -- "No" --> REBUILD["Rebuild message from<br/>template with CURRENT<br/>confirmed balance<br/>🔄 'message was rewritten'"]
    KEEP --> VAL
    REBUILD --> VAL{"check_draft():<br/>exact amount present,<br/>no other amount?"}
    VAL -- "No" --> BLOCK["⚠️ Button hidden<br/>until fixed"]
    VAL -- "Yes" --> BTN["📲 Remind on WhatsApp<br/>wa.me/92XXXXXXXXXX?text=…"]
    BTN --> SEND["Owner presses Send<br/>in WhatsApp"]
```

Phone numbers are normalized before saving: `0300 1234567`, `+92 300 1234567`, `0092-300-1234567` and Urdu digits all become `923001234567`. Anything else is rejected with a helpful message.

---

## 7. Recording a payment

```mermaid
sequenceDiagram
    actor Owner
    participant App as Collect screen
    participant Sto as store.py
    participant Led as ledger.py

    Owner->>App: Record payment "1,000" for عثمان
    App->>App: Same payment in last 8 s? → ignore (double tap)
    App->>Led: parse_amount("1,000")
    Led-->>App: Decimal 1000.00 ✓ (0, negative, junk → error)
    App->>Sto: record_payment → 'paid' entry + history event
    Sto-->>App: saved
    App->>Led: compute_balances()
    Led-->>App: عثمان 3,000 · total 13,700
    App-->>Owner: "✅ Recorded Rs. 1,000. New balance: Rs. 3,000"
    Note over App: New revision → عثمان's reminder rewrites itself
```

---

## 8. Data model

```mermaid
erDiagram
    PAGES ||--o{ ENTRIES : contains
    ENTRIES }o--|| CUSTOMER : "belongs to (by name key + approved aliases)"
    CUSTOMER ||--o| CONTACTS : "saved number & due date"
    ALIASES }o--|| CUSTOMER : "owner-approved same person"
    EVENTS }o--o| ENTRIES : records

    PAGES {
        text id "hash of the photo"
        text label
        text page_kind "transactions or summary"
        text written_total "evidence only"
        text signature "spots re-photographed pages"
    }
    ENTRIES {
        text id
        text page_id "or 'payments'"
        text name "original script"
        text amount_raw "exactly as written"
        text amount "Decimal or empty if unclear"
        text kind "owed, paid, or empty"
        text source "extracted, manual, payment"
    }
    CONTACTS {
        text customer_id
        text phone "923XXXXXXXXX"
        text due_date "optional"
    }
    ALIASES {
        text alias_key
        text canonical_key
    }
    EVENTS {
        int id
        text type "page_confirmed, payment, row_fixed, alias_approved"
        text customer
        text amount
    }
```

Customers aren't a separate table: a customer is **the exact name key** (Unicode-normalized, case-folded), plus any aliases the owner approved. `عثمان` and `Usman` are different people until the owner says otherwise.

---

## 9. Design decisions

| Decision | Why |
|---|---|
| **Streamlit web app** | Runs in any browser, including phones on the same Wi-Fi, with no app install. Fast to build in a hackathon |
| **AI transcribes, Python calculates** | Language models can make arithmetic slips; `Decimal` doesn't |
| **Unknown is never zero** | A silent zero means asking a customer for the wrong amount |
| **Original-script identity** | Transliterations vary (*Aisha* / *Ayesha*); the written name doesn't |
| **Revision-bound reminders** | Makes it impossible to send an outdated amount |
| **Sample replay mode** | A reliable demo that doesn't depend on Google's free servers, clearly labelled as replay |
| **Race two Gemma 4 models** | Busy-server errors often hit one model but not the other |
| **SQLite, single user** | Enough for one shop's laptop; a public version would need logins first |
