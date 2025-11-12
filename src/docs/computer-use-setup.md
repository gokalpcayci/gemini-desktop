## Gemini Computer Use: Local Desktop Trial (Browser Control via Terminal)

This guide shows how to run a local Computer Use agent that can see a browser window and perform actions you describe in your terminal. It uses the Gemini 2.5 Computer Use Preview model plus Playwright to actually click, type, navigate, and scroll.

Note: The agent sees and controls the Playwright browser window you launch, not your entire desktop.

### Prerequisites

- Python 3.10+ recommended
- A Gemini API key
  - Set it as an environment variable (preferred): `GOOGLE_API_KEY`
- Dependencies:

```bash
pip install google-genai playwright
playwright install chromium
```

### Run

```bash
export GOOGLE_API_KEY="YOUR_API_KEY"
python index.py
```

- A Chromium window opens at 1440x900.
- In your terminal, enter a goal (e.g., “Go to ai.google.dev/gemini-api/docs and search for pricing.”).
- The agent will iteratively propose actions (click/type/navigate/scroll), execute them, and continue until it can answer or stops.

### Safety confirmations

- If an action requires explicit user confirmation, you’ll be prompted in the terminal. Type “y” to proceed or “n” to stop that loop.

### Core actions implemented

- open_web_browser (no-op; browser is already open)
- navigate (with URL normalization)
- click_at (normalized coordinates -> screen pixels)
- type_text_at (optional clear_before_typing, optional press_enter)
- key_combination (e.g., Enter, Meta+A, Control+C)
- scroll_document (up/down/left/right with magnitude)

Additional actions can be added in `execute_function_calls` as needed.

### Tips

- Default viewport is 1440x900 to match model recommendations.
- You can add excluded actions in `index.py` by setting `excluded = ["drag_and_drop"]` (example).
- To start on a different page, change the initial `page.goto(...)` in `main()`.

### Troubleshooting

- “Missing API key”: Ensure `GOOGLE_API_KEY` (or `GENAI_API_KEY`) is set before running.
- Browser doesn’t open: Ensure Playwright is installed and `playwright install chromium` has been run.
- Actions seem off-target: Keep the window at 1440x900; avoid zoom changes and overlays.

### Notes

- Preview model: Expect occasional mistakes. Supervise usage, especially around consequential actions.


