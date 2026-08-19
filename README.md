# Sberworks MCP

Local stdio MCP server for Jira, Confluence, Bitbucket Server/Data Center and Jenkins.

## Prerequisites

- Python 3.11 or newer.
- `uv` is recommended for day-to-day setup.
- `cryptography` is used to read `CLIENT_P12_PATH`; no external OpenSSL binary is required.

The server is cross-platform and supports Windows, macOS and Linux. MCP clients can start it from any working directory when you use the generated config snippets.

## Quick Start With uv

PowerShell:

```powershell
cd path\to\sberworks-mcp
uv run sberworks-mcp init
uv run sberworks-mcp doctor
uv run sberworks-mcp config-snippet --client claude
```

bash/zsh:

```bash
cd /path/to/sberworks-mcp
uv run sberworks-mcp init
uv run sberworks-mcp doctor
uv run sberworks-mcp config-snippet --client claude
```

If `uv` is not installed, use the fallback below.

## Fallback With venv and pip

PowerShell:

```powershell
cd path\to\sberworks-mcp
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\sberworks-mcp init
.\.venv\Scripts\sberworks-mcp doctor
.\.venv\Scripts\sberworks-mcp config-snippet --client claude
```

bash/zsh:

```bash
cd /path/to/sberworks-mcp
python3 -m venv .venv
./.venv/bin/python -m pip install -e ".[dev]"
./.venv/bin/sberworks-mcp init
./.venv/bin/sberworks-mcp doctor
./.venv/bin/sberworks-mcp config-snippet --client claude
```

## First Run

Run the setup helper:

```powershell
sberworks-mcp init
```

`init` creates only a local `.env` file. It does not edit Claude, Codex, VS Code or other client configuration files. Existing `.env` files are not overwritten unless you pass `--force`.

Validate the result:

```powershell
sberworks-mcp doctor
```

Generate a client config snippet:

```powershell
sberworks-mcp config-snippet --client claude
sberworks-mcp config-snippet --client codex
sberworks-mcp config-snippet --client vscode
```

The snippets use:

- an absolute Python executable path as `command`;
- `args = ["-m", "sberworks_mcp"]`;
- an absolute `SBERWORKS_MCP_ENV_FILE` path.

This avoids the common MCP issue where a desktop client launches the server from an unexpected working directory or with a minimal inherited environment.

## Client Configuration

### Claude Desktop

Generate:

```powershell
sberworks-mcp config-snippet --client claude
```

Paste the JSON under the top-level config object.

Config path:

- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: Claude Desktop may not have an official Linux build; use Claude Code, Codex or VS Code snippets instead.

Restart Claude Desktop after editing the config.

### Codex

Generate:

```powershell
sberworks-mcp config-snippet --client codex
```

Add the TOML block to your Codex config, usually `~/.codex/config.toml`.

### VS Code

Generate:

```powershell
sberworks-mcp config-snippet --client vscode
```

Use the output in `.vscode/mcp.json` or the user-level MCP config. VS Code uses a top-level `servers` object, not `mcpServers`.

## Docker

Build the local image:

```powershell
docker build -t sberworks-mcp:local .
```

The container runs the same stdio MCP server. For MCP clients, keep stdin open with `-i`:

```powershell
docker run --rm -i `
  --env-file .env `
  -e SBERWORKS_MCP_ENV_FILE=/config/.env `
  -v ${PWD}/.env:/config/.env:ro `
  -v ${PWD}/certs:/certs:ro `
  -v ${PWD}/attachments:/attachments:ro `
  sberworks-mcp:local serve
```

With Docker Compose:

```powershell
docker compose build
docker compose run --rm -T sberworks-mcp doctor
docker compose run --rm -T sberworks-mcp
```

Generate Docker-based client snippets:

```powershell
sberworks-mcp config-snippet --client claude --runtime docker
sberworks-mcp config-snippet --client codex --runtime docker
sberworks-mcp config-snippet --client vscode --runtime docker
```

Use `--image` if you built the image under another tag:

```powershell
sberworks-mcp config-snippet --client claude --runtime docker --image custom/sberworks-mcp:test
```

The generated snippets use `command = docker` and pass `run --rm -i`, `--env-file`, the `.env` mount at `/config/.env`, and read-only mounts for `/certs` and `/attachments`.

When running in Docker, paths inside `.env` must be container paths. For example:

```dotenv
REQUESTS_CA_BUNDLE=/certs/ca.pem
CLIENT_P12_PATH=/certs/client.p12
```

Do not publish local runtime files. `.env`, `certs/`, `.cert_cache/` and `attachments/` are intentionally excluded from git and the Docker build context.

## Run Manually

For normal MCP client usage, the client starts the server. For a manual stdio launch:

```powershell
sberworks-mcp
```

or:

```powershell
sberworks-mcp serve
```

`python -m sberworks_mcp` is also supported.

## Environment

Required:

- `JIRA_BASE_URL`
- `CONFLUENCE_BASE_URL`
- `BITBUCKET_BASE_URL`
- `AUTH_USERNAME`
- `AUTH_PASSWORD`

Zephyr methods use `JIRA_BASE_URL` and the same Jira authentication. They target the `/rest/atm/latest` API namespace.

Jenkins is optional. When `JENKINS_BASE_URL` is set, the client uses the same `AUTH_USERNAME` and `AUTH_PASSWORD`, but authenticates with mTLS followed by the configured form flow. SAML installations are handled as Jenkins `SAMLRequest` → identity-provider login form → Jenkins `SAMLResponse`; a regular Jenkins form remains supported as a fallback. The account password is never sent as Jenkins HTTP Basic auth.

Optional:

- `JENKINS_BASE_URL`: Jenkins controller base URL, for example `https://sberworks.ru/jenkins-ci`.
- `BITBUCKET_SERVER_BEARER_TOKEN`: takes precedence for Bitbucket auth.
- `REQUESTS_CA_BUNDLE`: corporate CA bundle path.
- `CLIENT_P12_PATH` and `CLIENT_P12_PASSWORD`: client certificate in P12 format.
- `SBERWORKS_MCP_CERT_CACHE_DIR`: directory for converted PEM certificate files. Defaults to `.cert_cache` next to `SBERWORKS_MCP_ENV_FILE`, so desktop clients can start the MCP server from any working directory.
- `SBERWORKS_MCP_DOWNLOAD_DIR`: default directory for `bitbucket_download_file`. Defaults to the system temp directory under `sberworks-mcp-downloads`.
- `SBERWORKS_MCP_ENABLE_WRITES`: defaults to `false`.
- `SBERWORKS_MCP_TIMEOUT_SECONDS`: defaults to `30`.

Write tools are disabled by default. Enable them explicitly only after read-only tools work:

```powershell
$env:SBERWORKS_MCP_ENABLE_WRITES = "true"
```

or set it in `.env`:

```dotenv
SBERWORKS_MCP_ENABLE_WRITES=true
```

## Tools

Jira:

- `jira_search`
- `jira_get_issue`
- `jira_get_comments`
- `jira_get_remote_links`
- `jira_get_development_details`
- `jira_add_comment`
- `jira_create_issue`
- `jira_add_attachment`
- `jira_update_issue_fields`
- `jira_list_transitions`
- `jira_transition_issue`

Confluence:

- `confluence_search`
- `confluence_get_page`
- `confluence_get_children`
- `confluence_create_page`
- `confluence_update_page`
- `confluence_add_comment`

Bitbucket:

- `bitbucket_get_repo`
- `bitbucket_list_repositories`
- `bitbucket_create_repo`
- `bitbucket_list_pull_requests`
- `bitbucket_get_pull_request`
- `bitbucket_find_pull_requests_by_issue_key`
- `bitbucket_get_pr_diff`
- `bitbucket_get_file`
- `bitbucket_download_file`
- `bitbucket_put_file`
- `bitbucket_add_pr_comment`
- `bitbucket_create_pull_request`

Zephyr:

- `zephyr_get_cycle`
- `zephyr_get_cycle_case_keys`
- `zephyr_get_test_case`
- `zephyr_get_test_cases`
- `zephyr_get_test_case_details`
- `zephyr_export_cycle_cases`
- `zephyr_export_cycle_case_details`
- `zephyr_probe_cycle_endpoints`

Jenkins read tools:

- `jenkins_get_info`
- `jenkins_list_jobs`
- `jenkins_get_job`
- `jenkins_list_builds`
- `jenkins_get_build`
- `jenkins_get_console`
- `jenkins_list_queue`
- `jenkins_get_queue_item`
- `jenkins_list_artifacts`
- `jenkins_download_artifact`

Jenkins write tools, guarded by `SBERWORKS_MCP_ENABLE_WRITES`:

- `jenkins_trigger_build`
- `jenkins_stop_build`
- `jenkins_cancel_queue_item`

Jenkins job paths are slash-separated logical paths such as `Folder/Multibranch/main`; the client converts each segment to Jenkins' `/job/<segment>` URL form. Build parameters must be scalar JSON values. File parameters and Jenkins administration are not supported.

## Resources

- `jira://issue/{key}`
- `confluence://page/{page_id}`
- `bitbucket://projects/{project}/repos/{repo}/files/{path}?at={ref}`
- `zephyr://cycle/{cycle_key}`
- `zephyr://testcase/{case_key}`

## Troubleshooting

- Run `sberworks-mcp doctor --env-file /absolute/path/to/.env`.
- Use absolute paths in MCP client configs and `.env` file references.
- Do not write MCP protocol logs to stdout in server mode; stdout is reserved for JSON-RPC.
- Check client logs when a server does not appear.
  - Claude Desktop Windows logs: `%APPDATA%\Claude\logs`
  - Claude Desktop macOS logs: `~/Library/Logs/Claude`
- Test with MCP Inspector when a client cannot connect.
- If `CLIENT_P12_PATH` is set, make sure the file path is absolute for desktop MCP clients.
- `doctor` opens the configured P12 with `CLIENT_P12_PASSWORD`; this catches a stale password even when an older converted PEM cache still exists.
- A Jenkins SAML/form login error means the configured identity provider rejected the credentials or returned an unsupported form. A browser tab may continue to work because it already has a session cookie.

## Tests

```powershell
python -m pytest
```
