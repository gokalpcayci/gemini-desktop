import os
import sys
import time
from typing import Any, Dict, List, Tuple, Optional

from playwright.sync_api import Page, sync_playwright
from google import genai
from google.genai import types
from google.genai.types import Content, Part


# Recommended screen dimensions for Computer Use
SCREEN_WIDTH = 1440
SCREEN_HEIGHT = 900


def load_env_from_dotenv(path: str = ".env") -> None:
    """Load simple KEY=VALUE pairs from a .env file if present."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and not os.getenv(key):
                    os.environ[key] = value
    except Exception:
        # Fail silently; we still allow regular environment variables to be used.
        pass


def denormalize_x(x: int, screen_width: int) -> int:
    """Convert normalized x coordinate (0-1000) to actual pixel coordinate."""
    return int(x / 1000 * screen_width)


def denormalize_y(y: int, screen_height: int) -> int:
    """Convert normalized y coordinate (0-1000) to actual pixel coordinate."""
    return int(y / 1000 * screen_height)


def ensure_url_scheme(url: str) -> str:
    """Ensure the URL has a scheme. Defaults to https:// when missing."""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"https://{url}" if url else url


def get_safety_confirmation(safety_decision: Dict[str, Any]) -> str:
    """Prompt user for confirmation when safety check is triggered."""
    print("\n[Safety] Confirmation required:")
    explanation = safety_decision.get("explanation") or safety_decision.get("reason") or "The model requested a potentially sensitive action."
    print(explanation)
    decision = ""
    while decision.lower() not in ("y", "n", "yes", "no"):
        decision = input("Proceed? [Y]es/[N]o: ").strip()
    if decision.lower() in ("n", "no"):
        return "TERMINATE"
    return "CONTINUE"


def execute_function_calls(candidate, page: Page, screen_width: int, screen_height: int) -> Tuple[List[Tuple[str, Dict[str, Any], Dict[str, Any]]], bool]:
    """Translate model FunctionCalls into Playwright actions.

    Returns:
        - results: list of tuples (function_name, action_result, extra_fields_for_function_response)
        - terminated: whether execution should terminate early
    """
    results: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
    terminated = False

    function_calls: List[Any] = []
    for part in candidate.content.parts:
        if getattr(part, "function_call", None):
            function_calls.append(part.function_call)

    for function_call in function_calls:
        action_result: Dict[str, Any] = {}
        extra_fr_fields: Dict[str, Any] = {}
        fname = function_call.name
        args = dict(function_call.args or {})
        print(f"  -> Executing: {fname}")

        # Safety decision handling
        safety_decision = args.get("safety_decision")
        if isinstance(safety_decision, dict):
            decision = get_safety_confirmation(safety_decision)
            if decision == "TERMINATE":
                print("Terminating agent loop by user choice.")
                terminated = True
                # Acknowledge the safety decision in the next function response bundle (if any)
                extra_fr_fields["safety_acknowledgement"] = "false"
                results.append((fname, {"terminated_by_user": True}, extra_fr_fields))
                break
            extra_fr_fields["safety_acknowledgement"] = "true"

        try:
            if fname == "open_web_browser":
                # No-op; browser is already open in this client
                pass

            elif fname == "navigate":
                url = ensure_url_scheme(str(args.get("url", "")))
                if not url:
                    raise ValueError("Missing 'url' argument for navigate")
                page.goto(url, wait_until="domcontentloaded")

            elif fname == "click_at":
                actual_x = denormalize_x(int(args["x"]), screen_width)
                actual_y = denormalize_y(int(args["y"]), screen_height)
                page.mouse.click(actual_x, actual_y)

            elif fname == "type_text_at":
                actual_x = denormalize_x(int(args["x"]), screen_width)
                actual_y = denormalize_y(int(args["y"]), screen_height)
                text = str(args.get("text", ""))
                press_enter = bool(args.get("press_enter", True))
                clear_before_typing = bool(args.get("clear_before_typing", True))

                page.mouse.click(actual_x, actual_y)
                if clear_before_typing:
                    # macOS shortcut to select-all then delete
                    page.keyboard.press("Meta+A")
                    page.keyboard.press("Backspace")
                if text:
                    page.keyboard.type(text, delay=15)
                if press_enter:
                    page.keyboard.press("Enter")

            elif fname == "key_combination":
                keys = str(args.get("keys", "")).strip()
                if not keys:
                    raise ValueError("Missing 'keys' argument for key_combination")
                normalized = keys.title() if keys.lower() != "enter" else "Enter"
                page.keyboard.press(normalized)

            elif fname == "scroll_document":
                direction = (args.get("direction") or "down").lower()
                if direction not in ("up", "down", "left", "right"):
                    raise ValueError("direction must be up, down, left, or right")
                magnitude = int(args.get("magnitude", 800))
                dx = 0
                dy = 0
                if direction == "down":
                    dy = magnitude
                elif direction == "up":
                    dy = -magnitude
                elif direction == "right":
                    dx = magnitude
                elif direction == "left":
                    dx = -magnitude
                page.mouse.wheel(dx, dy)

            else:
                print(f"Warning: Unimplemented or custom function '{fname}'")

            # Give time for UI to settle after actions
            try:
                page.wait_for_load_state(state="networkidle", timeout=5000)
            except Exception:
                pass
            time.sleep(0.8)

        except Exception as e:
            print(f"Error executing {fname}: {e}")
            action_result = {"error": str(e)}

        results.append((fname, action_result, extra_fr_fields))

    return results, terminated


def get_function_responses(page: Page, results: List[Tuple[str, Dict[str, Any], Dict[str, Any]]]) -> List[types.FunctionResponse]:
    """Create FunctionResponse objects including a fresh screenshot and the current URL."""
    screenshot_bytes = page.screenshot(type="png")
    current_url = page.url
    function_responses: List[types.FunctionResponse] = []

    for name, result, extra_fields in results:
        response_data: Dict[str, Any] = {"url": current_url}
        if result:
            response_data.update(result)
        if extra_fields:
            response_data.update(extra_fields)
        function_responses.append(
            types.FunctionResponse(
                name=name,
                response=response_data,
                parts=[
                    types.FunctionResponsePart(
                        inline_data=types.FunctionResponseBlob(
                            mime_type="image/png",
                            data=screenshot_bytes,
                        )
                    )
                ],
            )
        )
    return function_responses


def run_agent_loop(client: genai.Client, page: Page, user_goal: str, excluded_functions: Optional[List[str]] = None) -> None:
    # ... (code before the loop is fine) ...

    turn_limit = 10
    for i in range(turn_limit):
        print(f"\n--- Turn {i + 1} ---")
        
        # ✅ START OF CORRECTED BLOCK
        # This whole section must be indented to be INSIDE the loop
        response = client.models.generate_content(
            model="gemini-2.5-computer-use-preview-10-2025",
            contents=contents,
            config=config,
        )

        candidate = response.candidates[0]
        contents.append(candidate.content)

        has_function_calls = any(getattr(p, "function_call", None) for p in candidate.content.parts)
        if not has_function_calls:
            text_response = " ".join([p.text for p in candidate.content.parts if getattr(p, "text", None)])
            print(f"Agent: {text_response.strip()}")
            break

        print("Executing actions...")
        results, terminated = execute_function_calls(candidate, page, SCREEN_WIDTH, SCREEN_HEIGHT)

        print("Capturing state...")
        function_responses = get_function_responses(page, results)

        contents.append(
            Content(role="user", parts=[Part(function_response=fr) for fr in function_responses])
        )

        if terminated:
            break
        # ✅ END OF CORRECTED BLOCK


def main() -> None:
    # Load .env if present so GOOGLE_API_KEY is available without manual export
    load_env_from_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GENAI_API_KEY")
    if not api_key:
        print("Missing API key. Set 'GOOGLE_API_KEY' (preferred) or 'GENAI_API_KEY' in your environment.")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    print("Initializing browser...")
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(viewport={"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT})
    page = context.new_page()

    try:
        # Start on a neutral page to allow the model to drive navigation
        page.goto("https://www.google.com", wait_until="domcontentloaded")

        print("\nType what you want the agent to do. Example:")
        print("  - Go to ai.google.dev/gemini-api/docs and search for pricing.")
        print("  - Find highly rated 27-inch 4K monitors under $300 and list 3.")
        print("Type 'exit' to quit.")

        while True:
            goal = input("\nYour goal: ").strip()
            if not goal:
                continue
            if goal.lower() in ("exit", "quit"):
                break

            # Optional: exclude high-risk actions during experimentation
            excluded: List[str] = []  # e.g., ["drag_and_drop"]
            run_agent_loop(client, page, goal, excluded_functions=excluded)

    finally:
        print("\nClosing browser...")
        try:
            browser.close()
        except Exception:
            pass
        playwright.stop()


if __name__ == "__main__":
    main()

