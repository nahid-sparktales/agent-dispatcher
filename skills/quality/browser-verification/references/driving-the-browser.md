# Driving the browser

Prefer, in order:

1. **Playwright MCP** (`mcp__playwright__*`) when configured — navigation, screenshots, console and
   network access, viewport emulation.
2. **The host's own browser tools.** In Claude Code's desktop app: `mcp__Claude_Browser__navigate`,
   `computer` (screenshot, click, type), `resize_window` (viewports), `read_console_messages`,
   `read_network_requests`, `read_page` (accessibility tree).
3. **A local Playwright script**, only when the project already depends on Playwright. Write it to
   a scratch path, not into the repository, unless the user asked for a test to keep.

Viewports: 1440×900 desktop; 768×1024 tablet when there is a mid breakpoint; 375×812 mobile.
Reload after switching — CSS reflows on resize, but layout-time breakpoints and device gates only
re-run on load.

Read the **accessibility tree** rather than a screenshot when the question is "what does this say"
or "is this control reachable". It answers both, it is what a screen reader gets, and it is far
cheaper than an image.
