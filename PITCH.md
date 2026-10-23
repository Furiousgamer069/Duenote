# DueNote: pitch

## 2-minute pitch (with live demo)

**0:00–0:25 · The problem**
Every general store in Faisalabad runs on a *khata*, a notebook of who took goods on credit. Totals are added by hand, numbers get crossed out, and nobody knows at a glance who owes what. Asking a regular customer for money is awkward, so it often never gets asked. Shops lose money they've already earned.

**0:25–0:35 · The solution**
DueNote: the shopkeeper keeps their notebook and just photographs the pages, even several at once. DueNote turns them into a checked ledger with polite WhatsApp reminders.

**0:35–1:25 · Demo**
| Click | Say |
|---|---|
| Sample replay: Urdu table → Replay | Gemma 4, Google's open-weight model, reads every row: names in Urdu script, amounts exactly as written. |
| Review this page → | The owner checks each row next to the photo. The page says 14,700, Python calculated 14,700: they match. Smudged or crossed-out amounts are flagged orange, never guessed. |
| Confirm → open عثمان (Usman) | Usman owes 4,000. His WhatsApp number is saved and a polite Urdu reminder is ready, with the exact amount inserted by code, not the AI. |
| Record payment 1,000 | Balance 3,000, total 13,700, and the reminder rewrote itself. DueNote can never ask for the wrong amount. |

**1:25–1:45 · Trust**
The AI only reads; Python does all the maths. Unknown is never zero. The owner confirms every page and presses Send in WhatsApp themselves.

**1:45–1:50 · Close**
Open source, with an agent skill and 93 automated tests. Shopkeepers keep their notebook, and DueNote helps them get paid.

## 30-second version
Small shops in Pakistan track credit in a handwritten khata, so mistakes happen and money goes uncollected. DueNote turns photos of those pages into a checked ledger. Gemma 4 reads Urdu and Roman Urdu handwriting, Python calculates every rupee, and unclear amounts are flagged instead of guessed. One tap opens a polite WhatsApp reminder with the exact balance, and it updates itself the moment a payment is recorded.

## Judge questions
| Question | Answer |
|---|---|
| Was that live AI? | A verified replay, so the demo is reliable. The live Gemma button reads any photo in about a minute. |
| What did Gemma 4 do? | It reads the handwritten photo and turns each row into structured data. It never does the maths. |
| How accurate is it? | On two test pages, every amount was correct (9/9 and 6/6). It's a small test; real shop notebooks are next. |
| What if it reads wrong? | The owner checks every row against the photo, unclear amounts are flagged, and the page's own totals are cross-checked. |
| A whole notebook? | Upload up to 10 pages at once, read them all, and review them one by one. Totals combine. |
| Does it send messages itself? | No. It opens WhatsApp with the message ready; the owner presses Send. |
