# post-v1.0 Manual Smoke Checklist

Run these checks when validating the local visual agent by hand.

## Release readiness

Use `agent release doctor` when the package entry point is installed, or run
the module form locally:

```powershell
$env:PYTHONPATH="src"
python -m agent.cli release doctor --cwd F:\agent
```

expected result: prints `release readiness`, `startup command: agent start`,
provider/model, settings write policy, packaging status, and verification
commands.

## DeepSeek terminal chat

```powershell
$env:PYTHONPATH="src"
$env:DEEPSEEK_API_KEY="..."
python -m agent.cli chat --cwd F:\agent --provider deepseek --model deepseek-v4-flash
```

expected result: chat prints a raw model response preview, then a parsed action
result with `terminal_reason: done` for a simple inspection prompt.

## Workbench browser chat

```powershell
$env:PYTHONPATH="src"
python -m agent.cli start --cwd F:\agent --port 8765
```

Open `http://127.0.0.1:8765/`, send a simple inspection prompt, and confirm:

- Status Bar shows workspace, provider, model, key presence, and last refresh.
- Settings Readiness is visible.
- Recent runs updates after the turn.
- Run detail shows Trace, Task Review, Workflow Hints, Patch Review, and Failure Recovery.

expected result: browser chat creates a run and keeps all review panels read-only.
