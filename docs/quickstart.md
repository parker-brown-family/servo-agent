# Quick start

## Install

```bash
uv tool install servo-agent
```

(`pipx install servo-agent` works too. For unreleased changes on `main`, install
`git+https://github.com/parker-brown-family/servo-agent` instead. From a clone,
`uv sync` and prefix commands with `uv run`.)

You also need a built `servoshell`. Either put it on `PATH`, set `$SERVOSHELL`,
or check out the [Servo](https://github.com/servo/servo) repo next to this one and:

```bash
./mach build -d --media-stack dummy  # -> target/debug/servoshell
```

`servo-agent` discovers the binary via `$SERVOSHELL` → `PATH` → a built `servo/`
checkout (`servo/target/{debug,release}/servoshell`) beside this repository or
beside any directory above the installed package. `read_native` additionally
needs the `t3/native-read` branch of
[our Servo fork](https://github.com/parker-brown-family/servo/tree/t3/native-read).

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
claude mcp add servo-agent -s user -- servo-agent serve
```

From a clone:

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
`open_url`, `read_page`, `read_native`, `find`, `wait_for_selector`,
`wait_for_load`, `get_errors`, `click`, `type_text`, `fill_form`, `scroll`,
`extract_links`, `extract_table`, `eval_js`, `screenshot`, and `status`.
