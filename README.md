# DeepSeek Codex Desktop

A lightweight Windows desktop client for working with DeepSeek through a Codex-style project workflow.

> Unofficial community project. Not affiliated with OpenAI or DeepSeek.

DeepSeek Codex Desktop gives you a native desktop workspace for project-based AI coding without replacing your existing Codex installation. It uses a separate DeepSeek Codex profile and calls the installed Codex CLI under the hood.

## Highlights

- Native Windows desktop UI
- Project switching and per-project chat history
- Persistent Codex sessions
- DeepSeek Flash model workflow
- Edit mode and read-only analysis mode
- Git changes panel with diff preview
- Safe Git revert with confirmation
- Git branch switching and branch creation
- Built-in project file browser
- Built-in PowerShell terminal
- File attachments, drag & drop, and clipboard screenshots
- Project checkpoints with restore support
- Exact token usage from Codex JSONL events
- Pinned chats and full-content chat search
- Single-instance protection
## Requirements

- Windows 10 or Windows 11
- Python 3.11+ for running from source
- Node.js/npm
- Git
- Codex CLI installed globally
- A working DeepSeek Codex profile in `%USERPROFILE%\.codex-deepseek`

The app does **not** contain or ship your DeepSeek API key.

## Install Codex CLI

```powershell
npm install -g @openai/codex
```

Configure your DeepSeek Codex profile separately before starting the app. This repository intentionally does not include API keys, personal config files, state files, chat history, or checkpoints.

## Run from source

```powershell
git clone https://github.com/denisbogdanov354-ctrl/deepseek-codex-desktop.git
cd deepseek-codex-desktop
python -m pip install -r requirements.txt
python app.py
```
## Build the Windows app

```powershell
.\build.ps1
```

The resulting app is created at:

```text
dist\DeepSeek Codex\DeepSeek Codex.exe
```

## Configuration

By default, the app uses:

```text
DeepSeek profile: %USERPROFILE%\.codex-deepseek
Projects root:    %USERPROFILE%\Documents
```

You can override both without modifying the source:

```powershell
$env:DEEPSEEK_CODEX_HOME="D:\Profiles\.codex-deepseek"
$env:DEEPSEEK_CODEX_PROJECTS_ROOT="D:\Projects"
python app.py
```

The app looks for `codex.cmd`, `codex.exe`, or `codex` in PATH and falls back to the standard npm global installation path on Windows.
## Safety notes

- Read-only analysis mode runs Codex with a read-only sandbox.
- Git revert always requires confirmation.
- Untracked files are never silently deleted by Git revert.
- Project checkpoint restore requires confirmation and creates a safety checkpoint first.
- Checkpoints exclude common generated folders and files larger than 25 MB.
- Only one application instance is allowed at a time to protect the shared state file.

## Privacy

Local app state is stored outside the repository in the configured DeepSeek Codex profile directory. The public repository contains no user chat history, API keys, project files, or checkpoints.

## Status

Current release line: **1.0.x**

The application is Windows-first and currently built with Tkinter + tkinterdnd2.

## License

MIT. See [LICENSE](LICENSE).