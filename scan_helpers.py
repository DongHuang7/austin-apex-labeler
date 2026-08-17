"""
Shared Claude batch-categorization call, used by both the incremental
new-sender scan (scan_new_contacts) and the dashboard's manual "Check now"
button. The two scan *strategies* (what contacts to look at, how much email
history to pull) stay separate — only this API call + response parsing is
shared, since forcing the two fetch strategies to converge would slow down
the cheap incremental scan for no benefit.
"""
import json

import anthropic

MODEL_CATEGORIZE = "claude-haiku-4-5-20251001"

client = anthropic.Anthropic()

PROMPT_TEMPLATE = """You are a real estate assistant helping categorize contacts for a real estate agent.

Categorize each contact into one of these groups:
- Buyer: Someone looking to purchase property. Clues: asking about homes, neighborhoods, prices, school districts, scheduling tours.
- Seller: Someone looking to sell their property. Clues: asking about home value, listing process, what their home is worth.
- Broker: A real estate agent, broker, or industry professional. Clues: agent language, referencing MLS, showings, co-op, listings, commission.
- Other: Anyone who doesn't fit the above.

Use the information given to decide. If unsure, use "Other".

Return ONLY a valid JSON array, no explanation:
[
  {{"index": 1, "category": "Buyer/Seller/Broker/Other", "reason": "brief reason"}},
  ...
]

Contacts:
{contact_list}"""


def categorize_batch_with_claude(batch: list, contact_list: str) -> None:
    """Send a pre-formatted contact list to Claude and assign `category`/
    `reason` back onto each dict in `batch` by its 1-based `index`."""
    response = client.messages.create(
        model=MODEL_CATEGORIZE,
        max_tokens=4096,
        messages=[{"role": "user", "content": PROMPT_TEMPLATE.format(contact_list=contact_list)}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    results = json.loads(raw.strip())
    for item in results:
        idx = item["index"] - 1
        batch[idx]["category"] = item["category"]
        batch[idx]["reason"] = item["reason"]
