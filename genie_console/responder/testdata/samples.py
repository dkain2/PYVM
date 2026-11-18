"""Fixed inputs used to pin the old look (golden_old.json) and to try the new one."""

RICH = (
    "# Why quote Q-123 did not sync\n\n"
    "The **quote** was rejected by NetSuite. See [the recipe](https://app.workato.com/recipes/1).\n\n"
    "## What happened\n"
    "- Step 1: the quote was *approved*\n"
    "  - nested detail\n"
    "- Step 2: NetSuite said `INVALID_KEY`\n\n"
    "> Retrying will not help until the customer exists.\n\n"
    "---\n\n"
    "| Field | Value |\n|---|---|\n| Quote | Q-123 |\n| Status | **Failed** |\n\n"
    "| Other | Table |\n|---|---|\n| a | b |\n\n"
    "```python\nprint('hi')\n```\n"
)
SAMPLES = {
    "rich": RICH,
    "plain": "Short answer.",
    "long": "\n\n".join("Paragraph {} ".format(i) + "word " * 150 for i in range(40)),
}
