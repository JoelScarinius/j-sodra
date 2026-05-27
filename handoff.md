# Minimal Collaborator Handoff

## What Runs Where

- `fetch_football_data.py` is the only analytics entrypoint.
- `supabase/functions/wyscout-proxy` proxies Wyscout API calls.
- `supabase/functions/refresh-reports` is the public refresh endpoint the frontend calls.
- `.github/workflows/refresh-reports.yml` is the hosted executor that actually runs the Python pipeline.

## Hosted Refresh Setup

- You already have the Wyscout proxy edge function.
- To make refresh work without your laptop, add the new `refresh-reports` edge function and the GitHub Actions workflow.
- Flow:
  - Lovable calls `POST /functions/v1/refresh-reports`.
  - The edge function dispatches the GitHub Actions workflow.
  - GitHub Actions runs `python fetch_football_data.py --force-refresh`.
  - The pipeline publishes fresh `reports/` artifacts to Supabase Storage.
  - Lovable polls `GET /functions/v1/refresh-reports?run_id=...` until it sees `succeeded`, then refetches `reports/index.json`.

## Local Requirements

- Install Python dependencies from `requirements.txt`.
- Add these local `.env` values: `SUPABASE_FUNCTION_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_S3_ENDPOINT`, `SUPABASE_S3_BUCKET`, `SUPABASE_S3_ACCESS_KEY`, `SUPABASE_S3_SECRET_KEY`.
- Optional local `.env` values: `SUPABASE_S3_PREFIX`, `SUPABASE_PUBLIC_BASE_URL`.
- Wyscout client id and secret are only needed on the deployed Supabase proxy, not in the frontend.

## Basic Commands

```bash
pip install -r requirements.txt
python fetch_football_data.py
python fetch_football_data.py --force-refresh
```

## Supabase Function Secrets

- `wyscout-proxy` needs `WYSCOUT_CLIENT_ID`, `WYSCOUT_CLIENT_SECRET`, and optional `WYSCOUT_BASE_URL`.
- `refresh-reports` needs:
  - `GITHUB_OWNER`
  - `GITHUB_REPO`
  - `GITHUB_TOKEN`
  - optional `GITHUB_REFRESH_WORKFLOW_FILE` default `refresh-reports.yml`
  - optional `GITHUB_REFRESH_REF` default `main`

## GitHub Repository Secrets

- The workflow needs these GitHub repo secrets:
  - `SUPABASE_FUNCTION_URL`
  - `SUPABASE_ANON_KEY`
  - `SUPABASE_S3_ENDPOINT`
  - `SUPABASE_S3_BUCKET`
  - `SUPABASE_S3_ACCESS_KEY`
  - `SUPABASE_S3_SECRET_KEY`
  - optional `SUPABASE_S3_PREFIX`
  - optional `SUPABASE_PUBLIC_BASE_URL`

## GitHub Token Requirements

- `GITHUB_TOKEN` in the Supabase edge function secrets is a personal access token or fine-grained token that can:
  - dispatch GitHub Actions workflows
  - read GitHub Actions workflow runs
- For a fine-grained token, grant this repository:
  - Actions: read and write
  - Contents: read

## Exact Secret Commands

Supabase function secrets for the current project ref `ytzuftamjgafzgyogpke`:

```bash
supabase secrets set --project-ref ytzuftamjgafzgyogpke \
  GITHUB_OWNER=<github-owner> \
  GITHUB_REPO=<github-repo> \
  GITHUB_TOKEN=<github-token>

supabase secrets set --project-ref ytzuftamjgafzgyogpke \
  WYSCOUT_CLIENT_ID=<wyscout-client-id> \
  WYSCOUT_CLIENT_SECRET=<wyscout-client-secret> \
  WYSCOUT_BASE_URL=https://apirest.wyscout.com/v3
```

Optional Supabase refresh overrides:

```bash
supabase secrets set --project-ref ytzuftamjgafzgyogpke \
  GITHUB_REFRESH_WORKFLOW_FILE=refresh-reports.yml \
  GITHUB_REFRESH_REF=main
```

GitHub repository secrets with GitHub CLI:

```bash
gh secret set SUPABASE_FUNCTION_URL --body "https://ytzuftamjgafzgyogpke.supabase.co/functions/v1/wyscout-proxy"
gh secret set SUPABASE_ANON_KEY --body "<supabase-anon-key>"
gh secret set SUPABASE_S3_ENDPOINT --body "https://ytzuftamjgafzgyogpke.storage.supabase.co/storage/v1/s3"
gh secret set SUPABASE_S3_BUCKET --body "plots"
gh secret set SUPABASE_S3_ACCESS_KEY --body "<supabase-s3-access-key>"
gh secret set SUPABASE_S3_SECRET_KEY --body "<supabase-s3-secret-key>"
gh secret set SUPABASE_PUBLIC_BASE_URL --body "https://ytzuftamjgafzgyogpke.supabase.co"
```

Deploy:

```bash
supabase functions deploy wyscout-proxy
supabase functions deploy refresh-reports
```

## Frontend Contract

- Lovable must bootstrap from `reports/index.json`.
- The page should fetch section refs from `index.sections`.
- The refresh button should `POST /functions/v1/refresh-reports`, poll `GET /functions/v1/refresh-reports?run_id=<run_id>`, and refetch `reports/index.json` after status becomes `succeeded`.
- If the refresh endpoint returns a hosted setup error, the frontend should fall back to reloading already-published reports and stay usable.

## Quick Troubleshooting

- `401` on function call usually means the anon key is missing or wrong.
- `500` on refresh function usually means one of `GITHUB_OWNER`, `GITHUB_REPO`, or `GITHUB_TOKEN` is missing in Supabase function secrets, or the token cannot access Actions.
- `404 No statistical data available` on match events is expected for some matches; the pipeline handles it as missing event data.
- If a refresh job stays in `queued` or `running`, check the GitHub Actions run for this repository.
