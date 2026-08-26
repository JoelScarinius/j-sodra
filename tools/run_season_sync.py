#!/usr/bin/env python3
"""Run resumable local sync-league batches until the trust gate finishes."""
from __future__ import annotations
import argparse, json, os, sys, time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def post_json(url: str, token: str, payload: dict, timeout: int) -> tuple[int, dict]:
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"error": body}
        return exc.code, parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=os.getenv("LOCAL_API_URL", "http://127.0.0.1:54321"))
    parser.add_argument("--league-id", type=int, required=True)
    parser.add_argument("--season-id", type=int, required=True, help="Provider season ID")
    parser.add_argument("--team-group-anchor", required=True, help="Team name identifying the desired division, for example Jonkopings Sodra")
    parser.add_argument("--batch-size", type=int, default=2, choices=range(1, 11), metavar="1-10")
    parser.add_argument("--request-delay-ms", type=int, default=250)
    parser.add_argument("--detail-concurrency", type=int, default=2)
    parser.add_argument("--event-concurrency", type=int, default=1)
    parser.add_argument("--max-batches", type=int, default=500)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-request-retries", type=int, default=5)
    args = parser.parse_args()

    token = os.getenv("LOCAL_SYNC_TOKEN") or os.getenv("SYNC_LEAGUE_TOKEN")
    if not token:
        print("Set LOCAL_SYNC_TOKEN or SYNC_LEAGUE_TOKEN in the environment.", file=sys.stderr)
        return 2

    endpoint = args.api_url.rstrip("/") + "/functions/v1/sync-league"
    payload = {
        "provider_league_id": args.league_id,
        "provider_season_ids": [args.season_id],
        "mode": "full",
        "include_events": True,
        "force_rehydrate_events": False,
        "max_matches": 0,
        "event_batch_size": args.batch_size,
        "team_name_keywords": [],
        "team_group_anchor": args.team_group_anchor,
        "detail_concurrency": args.detail_concurrency,
        "event_concurrency": args.event_concurrency,
        "request_delay_ms": args.request_delay_ms,
        "wyscout_max_retries": 5,
    }

    previous_remaining = None
    no_progress = 0
    retryable_http = {401, 409, 429, 500, 502, 503, 504}

    for batch_no in range(1, args.max_batches + 1):
        result = {}
        status_code = 0
        for attempt in range(1, args.max_request_retries + 2):
            try:
                status_code, result = post_json(endpoint, token, payload, args.timeout)
            except (URLError, TimeoutError) as exc:
                status_code = 0
                result = {"error": str(exc)}

            details = str(result.get("details") or result.get("error") or "")
            ingestion_ok = result.get("ingestion_passed", result.get("ok", False))
            retryable_body = any(code in details for code in (
                "57014", "statement timeout", "Unauthorized", "WORKER_LIMIT",
            ))
            should_retry = (
                status_code in retryable_http
                or status_code == 0
                or (not ingestion_ok and retryable_body)
            )
            if not should_retry:
                break
            if attempt > args.max_request_retries:
                break
            delay = min(30, 2 ** (attempt - 1))
            print(
                f"Batch {batch_no}: transient failure HTTP {status_code}; "
                f"retry {attempt}/{args.max_request_retries} in {delay}s",
                flush=True,
            )
            time.sleep(delay)

        telemetry = result.get("event_sync") or {}
        remaining = result.get("remaining_event_candidates")
        print(
            f"Batch {batch_no}: HTTP {status_code}; status={result.get('status')}; "
            f"fetched={telemetry.get('event_fetch_requests', 0)}; "
            f"reconciled={telemetry.get('matches_reconciled', 0)}; "
            f"unavailable={telemetry.get('matches_deferred_no_stats', 0)}; "
            f"remaining={remaining}; completeness={result.get('completeness_status')}",
            flush=True,
        )

        if not result.get("ingestion_passed", result.get("ok", False)):
            print(json.dumps(result, indent=2), file=sys.stderr, flush=True)
            return 1

        if result.get("continuation_required") is False:
            if result.get("completeness_passed") is True:
                print("Backfill complete and completeness audit passed.", flush=True)
                return 0
            print(json.dumps(result, indent=2), file=sys.stderr, flush=True)
            print("Backfill stopped without a passing completeness gate.", file=sys.stderr, flush=True)
            return 1

        if remaining is None:
            print(json.dumps(result, indent=2), file=sys.stderr, flush=True)
            print("Response did not contain continuation fields.", file=sys.stderr, flush=True)
            return 1

        if previous_remaining is not None and remaining >= previous_remaining:
            no_progress += 1
        else:
            no_progress = 0
        previous_remaining = remaining
        if no_progress >= 3:
            print("No progress across three batches. Inspect live claims and sync run logs.", file=sys.stderr, flush=True)
            return 1
        time.sleep(1)

    print("Maximum batch count reached before completion.", file=sys.stderr, flush=True)
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
