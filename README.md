# Sberworks MCP

Local stdio MCP server for Jira, Confluence and Bitbucket Server/Data Center.

## Setup

```powershell
cd C:\Work\Sberworks-mcp
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Fill `.env` or pass the same variables from your MCP client:

- `JIRA_BASE_URL`
- `CONFLUENCE_BASE_URL`
- `BITBUCKET_BASE_URL`
- `AUTH_USERNAME`
- `AUTH_PASSWORD`
- `BITBUCKET_SERVER_BEARER_TOKEN`
- `REQUESTS_CA_BUNDLE`
- `CLIENT_P12_PATH`
- `CLIENT_P12_PASSWORD`

Write tools are disabled by default. Enable them explicitly:

```powershell
$env:SBERWORKS_MCP_ENABLE_WRITES = "true"
```

## Run

Preferred command when `uv` is installed:

```powershell
uv run sberworks-mcp
```

Fallback:

```powershell
python -m sberworks_mcp
```

## Tools

Jira:

- `jira_search`
- `jira_get_issue`
- `jira_get_comments`
- `jira_add_comment`
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
- `bitbucket_list_pull_requests`
- `bitbucket_get_pull_request`
- `bitbucket_get_pr_diff`
- `bitbucket_get_file`
- `bitbucket_add_pr_comment`
- `bitbucket_create_pull_request`

## Resources

- `jira://issue/{key}`
- `confluence://page/{page_id}`
- `bitbucket://projects/{project}/repos/{repo}/files/{path}?at={ref}`

## Tests

```powershell
python -m pytest
```
