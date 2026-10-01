# Growplus AI Agency outreach automation

Local Python project for worldwide ecommerce prospect research and individual outreach. Sender: Khalandar Thameem, khalandarthameem97@gmail.com. Target: 50 qualified first-contact emails per UTC day and 750 total campaign sends (the original 250 plus 500 additional). No paid search or AI API is required by default.

## Run

```powershell
cd 'D:\AI AGENT\outreach'
.\run.ps1 research
.\run.ps1 export
.\.venv\Scripts\python.exe -m unittest -v test_pipeline.py
```

Results: `data/leads.csv`, `data/listings.csv`, `data/outreach.sqlite`, and `data/runs.log`. CSV values are escaped to prevent scraped text being evaluated as spreadsheet formulas. The evidence column includes page URLs, observations, published contact sources, and AEO/GEO review signals.

## Connect sending

During an interactive assistant session, the connected Gmail tool can send authorized outreach directly. This does not require the local SMTP app password. Confirmed sends must be imported into the same ledger so the background sender cannot contact those prospects again:

```powershell
.\.venv\Scripts\python.exe record_gmail_receipts.py data/gmail-sent-receipts.json
```

The receipt importer accepts full Gmail message objects, checks the sender and SENT label, and preserves the actual text, timestamp and RFC Message-ID. Receipt files and prospect records stay in ignored `data/`.

For an interactive campaign, `connected_campaign.py` reserves reviewed messages before sending. It checks the 750-send ceiling, 50-per-day limit, suppression and prior contact in one transaction. Check Gmail history before marking a message `history_checked`. A reservation counts toward the target until its Gmail receipt is reconciled, preventing retries after an uncertain result. Store one receipt file per message to avoid Windows command-length limits. This helper never sends mail itself; the connected Gmail tool sends each reviewed message individually.

```powershell
.\.venv\Scripts\python.exe connected_campaign.py data/reviewed-messages.json --target 750
.\.venv\Scripts\python.exe -m unittest -v test_pipeline.py test_connected_campaign.py
```

## Larger research batches

`import_registry.py` imports candidate domains from the [StoreProfiles public registry](https://storeprofiles.com/dataset), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Source attribution, retrieval date and the directory slug stay with each lead. Directory scores do not qualify leads or become email claims. Scrapling checks each store's own pages for published role contacts and page evidence.

`import_shopify_dataset.py` imports candidate domains from the [public Shopify website list](https://huggingface.co/datasets/snncn/shopify-websites), licensed under Apache 2.0. Its URL list is only a discovery source; the live Scrapling audit must still confirm the store, contact address and page findings.

```powershell
.\.venv\Scripts\python.exe import_registry.py
.\.venv\Scripts\python.exe import_shopify_dataset.py
.\.venv\Scripts\python.exe research_batch.py --searches 0 --max-sites 300 --workers 8
```

The research runner supports up to eight independent site audits at once, with the existing robots checks and crawl delays. Each worker has an isolated temporary database; results only update leads still marked `new`. It uses a separate research lock so a long audit does not block the send schedule, and never sends mail. The research schedule audits up to 500 sites every six hours. `--searches 24` also runs rotating free searches across ecommerce niches and markets; search services may throttle these requests.

The connected Gmail tool in chat confirms the sender identity, but its login cannot be exported into a local scheduled Python program. This local runner uses Gmail SMTP with STARTTLS and IMAP with TLS.

1. Create a Gmail app password if your account supports it. [Google instructions](https://support.google.com/accounts/answer/185833). Do not share the password in chat.
2. Run `./connect-gmail.ps1` locally and enter that app password in the credential prompt. Windows encrypts it for the current Windows user. It is stored under `data/`, which is excluded from Git.
3. Run `./activate-sending.ps1`. This verifies Gmail authentication and enables sending in `config.json`. It does not send a test email. The scheduler can then send one qualified email at a time.

## Schedule

`./install-schedule.ps1` registers two Windows tasks: research every six hours and a send attempt every fifteen minutes. Each task type has its own exclusive process lock. Send attempts do nothing while `send_enabled` is false. The daily cap is 50, with at least 15 minutes between sends; all sending stops once the ledger reaches 750 reservations or confirmed sends. The PC must be awake, connected to the internet, and this Windows account logged in. This is not cloud hosting.

On Windows installations that disable scripts, run the reviewed scripts with a process-only override, for example `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\connect-gmail.ps1`. The scheduled tasks use this process-only override; they do not change the machine-wide execution policy.

To stop sending, set `send_enabled` to `false` in `config.json`. To stop both schedules:

```powershell
Disable-ScheduledTask -TaskName Growplus-Outreach-research
Disable-ScheduledTask -TaskName Growplus-Outreach-send
```

## What is implemented

Personalized email writing uses [blader/humanizer](https://github.com/blader/humanizer). A pinned copy of its writing skill and MIT license is in `writing/humanizer/`; `SOURCE.json` records the upstream revision. `AGENTS.md` requires the full Humanizer review for assistant-written emails and freelance proposals. Only the final email goes to the recipient.

The Python templates were edited using that guidance: direct openings, concrete page observations, plain wording and one question. Scheduled template generation does not invoke an AI model or run the full skill on every email. Observation counts, HTML-only scope, sender details and opt-out text are preserved. Already-sent messages and their receipts are unchanged.

- DDGS free web discovery; optional Brave API support only when explicitly configured.
- Scrapling HTML fetches with public-address checks, robots.txt checks, crawl delays, bounded redirects and page limits.
- Ecommerce signals, page-level title, description, heading, viewport, canonical and image-alt observations.
- AEO/GEO signals: question headings, JSON-LD types and malformed JSON-LD counts. These are review inputs, not proof that a site ranks poorly or needs special AI markup.
- Public role-address extraction from mailto links on the same domain. No guessed personal addresses. Addresses are syntactically checked, not guaranteed deliverable.
- Personalized plain-text emails grounded in recorded observations; no fabricated traffic losses, rankings, testimonials or revenue promises.
- Freelancer listing discovery and title-based proposal drafts. Listing presence does not establish an open job; the exported status tells you to verify on the platform. No platform proposals are automatically submitted.
- Deduplication by domain and recipient, daily limits, reply suppression, and conservative handling of uncertain SMTP outcomes. Any reply stops further automated contact; a delivery report can suppress an address too.

## Limits to understand

50 is a target and cap, not a guaranteed daily supply. Discovery cannot enumerate every ecommerce site. Free search can throttle or fail. Static HTML checks can miss JavaScript-rendered content. Missing canonical tags or meta descriptions alone do not prove commercial need. Page findings require contextual review before offering a redesign. Source selectors can change; inspect the logs if listing counts fall to zero. The initial implementation does not measure Core Web Vitals, search rankings, AI citations, or backlink quality.

Only initial outreach is automated. There are no follow-up sequences, meeting booking, CRM deal stages or automatic positive-reply responses. An SMTP timeout may have delivered the message; such a lead is marked `delivery_unknown` and must be reconciled against Sent Mail before any manual retry. Do not reset that state blindly.

The reply sync checks campaign-era INBOX mail on its first run, then processes only new IMAP UIDs. It resets its cursor if Gmail changes the inbox UID validity. Keep replies and delivery reports in INBOX; do not auto-archive them. All replies require human follow-up. Domain matching does not merge subsidiaries or alternate company domains. This implementation does not determine jurisdiction or consent from a website address; worldwide discovery is not worldwide permission to email. Apply the relevant recipient-market rules when selecting campaigns. US commercial email requirements include a postal address and opt-out mechanism: [FTC guidance](https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business).

Manual suppression:

```powershell
.\.venv\Scripts\python.exe pipeline.py suppress --email address@example.com
```

## Repository choices

| Component | Role in this project |
| --- | --- |
| [Scrapling](https://github.com/D4Vinci/Scrapling) | Installed; page fetching and HTML extraction. |
| [DDGS](https://github.com/deedy5/ddgs) | Installed; free search discovery. |
| Python standard library + SQLite | Email composition, SMTP/IMAP, tracking and suppression. |
| [JobSpy](https://github.com/speedyapply/JobSpy) | Evaluated; job-board searches differ from freelance buyer listings. Not installed. |
| [StaffSpy](https://github.com/cullenwatson/StaffSpy) | Evaluated; LinkedIn staff collection is unnecessary for public store contacts. Not installed. |
| [Reacher](https://github.com/reacherhq/check-if-email-exists) | Optional future self-hosted mailbox checking. Not installed; verification is not guaranteed by this project. |
| [Firecrawl](https://github.com/firecrawl/firecrawl) | Evaluated; overlaps with the requested Scrapling layer. Not installed. |
| [Twenty](https://github.com/twentyhq/twenty) | Optional future CRM integration. SQLite currently tracks research and outreach. Not installed. |
| [n8n](https://github.com/n8n-io/n8n) | Evaluated; Windows Task Scheduler runs this local workflow. n8n uses its Sustainable Use License, not an unrestricted open-source license. Not installed. |

Google states that foundational SEO remains relevant to AI search features: [Google AI search guidance](https://developers.google.com/search/docs/appearance/ai-features). This project does not claim that FAQ schema, llms.txt, or any individual tag guarantees inclusion.
