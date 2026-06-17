# Quick start

## Install

```bash
uv tool install servo-agent          # or: pipx install servo-agent
```

You also need a built `servoshell`. Either put it on `PATH`, set `$SERVOSHELL`,
or check out the [Servo](https://github.com/servo/servo) repo next to this one and:

```bash
./mach build -d --media-stack dummy  # -> target/debug/servoshell
```

`servo-agent` auto-discovers the binary via `$SERVOSHELL` → `PATH` → a sibling
`servo/` checkout (`../servo/target/{debug,release}/servoshell`).

## Prove the stack

The self-test spawns its own headless engine, drives a real page through the
whole pipeline, and writes a screenshot — no MCP client required:

```bash
servo-agent selftest https://news.ycombinator.com
```

It walks `open_url → wait_for_selector → extract_links → eval_js → read_page →
screenshot` and reports the raw-vs-distilled size ratio. A green
`✓ self-test passed` means the binary is found, the engine boots, and
distillation works.

## Library use

```python
from servo_agent import ServoBrowser, distill

with ServoBrowser(headless=True) as b:
    b.navigate("https://example.com")
    print(distill(b.read_html(), b.current_url()))   # clean markdown
    rows = b.extract_table("table#stats")            # structured data
    b.screenshot("shot.png")
```

The context manager starts `servoshell` on a free port and tears it down on
exit. See the [API reference](api.md) for every method.

## Run as an MCP server

```bash
servo-agent serve          # MCP over stdio
```

### Wire into Claude Code

```bash
claude mcp add servo-agent -s user -- \
  uv run --project /path/to/servo-agent servo-agent serve
```

### Wire into Codex (`~/.codex/config.toml`)

```toml
[mcp_servers.servo-agent]
command = "uv"
args = ["run", "--project", "/path/to/servo-agent", "servo-agent", "serve"]
```

> MCP tools are injected at client startup — restart after adding/changing the
> server. Validate harness edits without a restart via `servo-agent selftest`.

Once wired in, the agent gets the tools listed in the [API reference](api.md):
`open_url`, `read_page`, `find`, `wait_for_selector`, `click`, `type_text`,
`fill_form`, `scroll`, `extract_links`, `extract_table`, `eval_js`,
`screenshot`, and `status`.
