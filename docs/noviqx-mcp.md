# NoviqX GitHub App and MCP (local development)

This optional integration is separate from Nova's existing read-only `gh`
CLI tool. It authenticates as the NoviqX GitHub App installation and exposes a
local MCP server over stdio.

## Install

```powershell
python -m pip install -r requirements-noviqx.txt
```

## Configure this computer

Set these variables in the shell that launches Nova or the MCP client:

```powershell
$env:NOVIQX_APP_ID = "5667949"
$env:NOVIQX_INSTALLATION_ID = "179860235"
$env:NOVIQX_PRIVATE_KEY_PATH = "$env:USERPROFILE\Documents\noviqx.2026-11-08.private-key.pem"
```

The path is machine-specific configuration, not source code. On another
computer, set `NOVIQX_PRIVATE_KEY_PATH` to that machine's secure key location.
Do not distribute the PEM to other users. For now this is a single-developer
local setup. When a hosted service is introduced, move App-key signing and
installation-token issuance behind that service.

## Test authentication without printing the token

```powershell
python -c "from integrations.noviqx.auth import GitHubAppAuth; t=GitHubAppAuth().get_installation_token(); print('Installation token acquired:', bool(t))"
```

This prints only whether a token was acquired. Never print, log, paste, or
commit the token or PEM contents.

## Run the MCP server

```powershell
python -m integrations.noviqx.mcp_server
```

Configure an MCP client to launch this command from the Nova repository root.
The server uses stdio; do not launch it in shared network mode.

## Tools

- Read repository metadata, issues, pull requests, and workflow runs.
- Create branches, issues, and draft pull requests.
- Create or update a repository file on a selected branch.

Merge, delete, release, workflow-editing, and administration operations are not
exposed. GitHub App permissions and selected installation repositories remain
the upper bound on access.

## Security

- The PEM is read from a local path and is never included in MCP tool arguments.
- Installation tokens are cached in process memory and refreshed before expiry.
- Error messages omit API response bodies and authorization data.
- MCP is local stdio only. Do not expose it to a network until transport
  security, user isolation, and authorization are designed for hosted use.
- GitHub App permissions must include the permissions required by each tool.
