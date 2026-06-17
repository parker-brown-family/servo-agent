# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities.

Report privately via GitHub's
[**Report a vulnerability**](https://github.com/parker-brown-family/servo-agent/security/advisories/new)
flow (the Security tab → Advisories). We aim to acknowledge reports within a few
days and will coordinate a fix and disclosure timeline with you.

When reporting, please include:

- A description of the issue and its impact
- Steps to reproduce (a minimal proof-of-concept if possible)
- Affected version(s) / commit

## Scope

`servo-agent` drives a local `servoshell` over WebDriver and renders arbitrary
web content. Note that:

- **It executes the JavaScript of pages you navigate to.** Treat any page you
  point it at as untrusted, and run it in an appropriately sandboxed environment
  for adversarial inputs.
- `read_page` returns page-derived content. Downstream consumers (e.g. an LLM)
  should treat that content as untrusted data, not instructions.

Issues in the underlying Servo engine should be reported upstream to the
[Servo project](https://github.com/servo/servo/security).

## Supported versions

This project is pre-1.0; security fixes land on `main` and in the latest
release. Pin a version and watch releases for updates.
