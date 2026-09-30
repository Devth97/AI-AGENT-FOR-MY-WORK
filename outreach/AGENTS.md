# Outreach writing

Before drafting or editing personalized outreach emails or freelance proposals, read `writing/humanizer/SKILL.md` and apply its full review process in embedded mode. Send only the final email, never the critique or drafting notes.

Use recorded page evidence or the actual project brief for personalization. Preserve counts, page references, the distinction between fetched HTML and rendered content, sender identity, mailing address and opt-out instructions. Never invent familiarity, compliments, outcomes, urgency, credentials or prior contact. Keep one clear question as the call to action.

For Python-generated emails, the templates in `pipeline.py` are edited with this guidance. They do not invoke a model at runtime. Do not describe template generation as a per-message AI Humanizer pass.

Check the contact ledger and Gmail history before interactive sends. Record confirmed sends with `record_gmail_receipts.py`. Keep runtime lead data and credentials out of Git.
