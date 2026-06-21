# Getting code suggestions with GitHub Copilot

A concise reference for enabling and using GitHub Copilot in common IDEs.

## Quick prerequisites
- A GitHub account with Copilot access (Free or paid).
- Sign in to GitHub from your IDE.
- Install the Copilot plugin/extension for your IDE.

## VS Code (recommended)
- Install and sign in to the GitHub Copilot extension.
- Inline suggestions appear as you type; accept with `Tab`.
- Show alternatives: `Alt + ]` / `Alt + [` (Windows/Linux) or `Option + ]` / `Option + [` (macOS).
- Open multiple suggestions: `Ctrl + Enter` (Windows/Linux) or `Cmd + Shift + A` (macOS).
- Accept next word: `Ctrl + →` (Windows/Linux) or `Cmd + →` (macOS).

## JetBrains IDEs (IntelliJ, PyCharm, GoLand...)
- Install the GitHub Copilot plugin from the JetBrains Marketplace.
- Sign in to GitHub in the IDE.
- Inline suggestions accept with `Tab`.
- See next/previous alternatives with `Alt + ]` / `Alt + [` (Windows/Linux).
- Open the Copilot pane for multiple completions via the IDE command palette.

## Visual Studio (Windows)
- Requires Visual Studio 2022 (17.8+) and the Copilot extension.
- Sign in and accept suggestions with `Tab`.
- Use Copilot edit controls in the suggestion UI for alternatives.

## Vim / Neovim
- Install the official Copilot plugin for Neovim/Vim and Node.js 18+.
- Inline suggestions appear while typing; accept with `Tab`.

## Other IDEs (Xcode, Eclipse, Azure Data Studio, etc.)
- Install the appropriate Copilot extension and sign in.
- Most editors use `Tab` to accept inline suggestions and provide IDE-specific keys to browse alternatives.

## Tips for better suggestions
- Provide clear natural-language comments describing intent before writing code.
- Keep surrounding code context in the editor — Copilot uses it to match style.
- If suggestions are limited, check duplication-detection settings in your Copilot preferences.

## Troubleshooting
- Ensure you're signed in to GitHub and have the Copilot extension enabled.
- Restart the IDE after installing/updating the extension.
- Check extension logs or the IDE's plugin settings for errors.

---
Saved to `docs/COPILOT_USAGE.md` — tell me if you want this committed or expanded for a specific IDE or team policy.
