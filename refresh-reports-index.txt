// @ts-nocheck
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";

const corsHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

const githubApiBase = (Deno.env.get("GITHUB_API_BASE_URL") ?? "https://api.github.com").replace(/\/+$/, "");
const githubOwner = Deno.env.get("GITHUB_OWNER") ?? "";
const githubRepo = Deno.env.get("GITHUB_REPO") ?? "";
const githubToken = Deno.env.get("GITHUB_TOKEN") ?? "";
const workflowFile = Deno.env.get("GITHUB_REFRESH_WORKFLOW_FILE") ?? "refresh-reports.yml";
const workflowRef = Deno.env.get("GITHUB_REFRESH_REF") ?? "main";
const workflowEvent = Deno.env.get("GITHUB_REFRESH_EVENT") ?? "workflow_dispatch";

function jsonResponse(status: number, payload: Record<string, unknown>) {
    return new Response(JSON.stringify(payload), {
        status,
        headers: { "Content-Type": "application/json", ...corsHeaders },
    });
}

function githubHeaders() {
    return {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${githubToken}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    };
}

function missingConfig(): string[] {
    const missing = [];
    if (!githubOwner) missing.push("GITHUB_OWNER");
    if (!githubRepo) missing.push("GITHUB_REPO");
    if (!githubToken) missing.push("GITHUB_TOKEN");
    return missing;
}

function buildStatusUrl(requestUrl: URL, runId: string) {
    const url = new URL(requestUrl.toString());
    url.search = "";
    url.searchParams.set("run_id", runId);
    return url.toString();
}

function parseRunId(runId: string | null) {
    if (!runId) return { requestedAtMs: NaN, upstreamRunId: null };
    const [timestampPart, upstreamPart] = runId.split("_", 2);
    const requestedAtMs = Number(timestampPart);
    const upstreamRunId = upstreamPart && /^\d+$/.test(upstreamPart) ? upstreamPart : null;
    return { requestedAtMs, upstreamRunId };
}

function createRunId(requestedAtMs: number, upstreamRunId?: string | number | null) {
    if (upstreamRunId) return `${requestedAtMs}_${String(upstreamRunId)}`;
    return `${requestedAtMs}_${crypto.randomUUID()}`;
}

function mapStatus(run: any) {
    if (!run) {
        return {
            status: "queued",
            upstream_status: null,
            upstream_conclusion: null,
            error: null,
        };
    }

    const upstreamStatus = run.status ?? null;
    const conclusion = run.conclusion ?? null;

    if (upstreamStatus === "completed") {
        if (conclusion === "success") {
            return {
                status: "succeeded",
                upstream_status: upstreamStatus,
                upstream_conclusion: conclusion,
                error: null,
            };
        }

        return {
            status: "failed",
            upstream_status: upstreamStatus,
            upstream_conclusion: conclusion,
            error: `GitHub workflow concluded with ${conclusion ?? "unknown"}`,
        };
    }

    if (["in_progress"].includes(upstreamStatus)) {
        return {
            status: "running",
            upstream_status: upstreamStatus,
            upstream_conclusion: conclusion,
            error: null,
        };
    }

    return {
        status: "queued",
        upstream_status: upstreamStatus,
        upstream_conclusion: conclusion,
        error: null,
    };
}

function serializeRun(reqUrl: URL, runId: string, requestedAtMs: number, run?: any) {
    const mapped = mapStatus(run);
    return {
        run_id: runId,
        status: mapped.status,
        requested_at: Number.isFinite(requestedAtMs)
            ? new Date(requestedAtMs).toISOString()
            : run?.created_at ?? null,
        started_at: run?.run_started_at ?? null,
        finished_at: run?.status === "completed" ? run?.updated_at ?? null : null,
        accepted: true,
        already_running: false,
        status_url: buildStatusUrl(reqUrl, runId),
        upstream_run_id: run?.id ?? null,
        upstream_status: mapped.upstream_status,
        upstream_conclusion: mapped.upstream_conclusion,
        html_url: run?.html_url ?? null,
        details_url: run?.html_url ?? null,
        workflow: workflowFile,
        ref: workflowRef,
        error: mapped.error,
    };
}

async function githubFetch(path: string, init: RequestInit = {}) {
    const response = await fetch(`${githubApiBase}${path}`, {
        ...init,
        headers: {
            ...githubHeaders(),
            ...(init.headers ?? {}),
        },
    });

    const text = await response.text();
    let json = null;
    try {
        json = text ? JSON.parse(text) : null;
    } catch {
        json = null;
    }

    return { response, text, json };
}

async function listWorkflowRuns() {
    const url = new URL(
        `${githubApiBase}/repos/${encodeURIComponent(githubOwner)}/${encodeURIComponent(githubRepo)}/actions/workflows/${encodeURIComponent(workflowFile)}/runs`,
    );
    url.searchParams.set("per_page", "20");
    url.searchParams.set("event", workflowEvent);
    url.searchParams.set("branch", workflowRef);

    const response = await fetch(url.toString(), {
        headers: githubHeaders(),
    });
    const text = await response.text();
    let json = null;
    try {
        json = text ? JSON.parse(text) : null;
    } catch {
        json = null;
    }

    if (!response.ok) {
        throw new Error(json?.message || text || `GitHub API failed with ${response.status}`);
    }

    return Array.isArray(json?.workflow_runs) ? json.workflow_runs : [];
}

async function getWorkflowRun(upstreamRunId: string) {
    const { response, text, json } = await githubFetch(
        `/repos/${encodeURIComponent(githubOwner)}/${encodeURIComponent(githubRepo)}/actions/runs/${encodeURIComponent(upstreamRunId)}`,
        { method: "GET" },
    );

    if (!response.ok) {
        throw new Error(json?.message || text || `GitHub run lookup failed with ${response.status}`);
    }

    return json;
}

async function findActiveRun() {
    const runs = await listWorkflowRuns();
    return runs.find((run: any) => run.status !== "completed") ?? null;
}

async function findRunForRequest(requestedAtMs: number) {
    const runs = await listWorkflowRuns();
    const toleranceMs = 30_000;
    return (
        runs.find((run: any) => {
            const createdAtMs = Date.parse(run.created_at ?? "");
            return Number.isFinite(createdAtMs) && createdAtMs >= requestedAtMs - toleranceMs;
        }) ?? null
    );
}

async function dispatchRefresh(runId: string, requestedAtMs: number, forceRefresh: boolean) {
    const { response, text, json } = await githubFetch(
        `/repos/${encodeURIComponent(githubOwner)}/${encodeURIComponent(githubRepo)}/actions/workflows/${encodeURIComponent(workflowFile)}/dispatches`,
        {
            method: "POST",
            body: JSON.stringify({
                ref: workflowRef,
                inputs: {
                    client_run_id: runId,
                    requested_at: new Date(requestedAtMs).toISOString(),
                    force_refresh: forceRefresh ? "true" : "false",
                },
            }),
        },
    );

    if (!response.ok) {
        throw new Error(json?.message || text || `GitHub dispatch failed with ${response.status}`);
    }
}

serve(async (req: Request) => {
    if (req.method === "OPTIONS") {
        return new Response("ok", { headers: corsHeaders });
    }

    if (!["GET", "POST"].includes(req.method)) {
        return jsonResponse(405, { error: "Method not allowed" });
    }

    const missing = missingConfig();
    if (missing.length) {
        return jsonResponse(500, {
            error: "Missing GitHub refresh configuration",
            missing,
        });
    }

    try {
        const requestUrl = new URL(req.url);

        if (req.method === "GET") {
            const runId = requestUrl.searchParams.get("run_id");
            if (!runId) {
                const activeRun = await findActiveRun();
                const latestRuns = await listWorkflowRuns();
                const latestRun = latestRuns[0] ?? null;

                return jsonResponse(200, {
                    ok: true,
                    mode: "github-actions",
                    workflow: workflowFile,
                    ref: workflowRef,
                    current_run: activeRun
                        ? serializeRun(
                              requestUrl,
                              createRunId(Date.parse(activeRun.created_at ?? new Date().toISOString()), activeRun.id),
                              Date.parse(activeRun.created_at ?? new Date().toISOString()),
                              activeRun,
                          )
                        : null,
                    latest_run: latestRun
                        ? serializeRun(
                              requestUrl,
                              createRunId(Date.parse(latestRun.created_at ?? new Date().toISOString()), latestRun.id),
                              Date.parse(latestRun.created_at ?? new Date().toISOString()),
                              latestRun,
                          )
                        : null,
                });
            }

            const parsed = parseRunId(runId);
            if (!Number.isFinite(parsed.requestedAtMs)) {
                return jsonResponse(400, { error: "Invalid run_id" });
            }

            let run = null;
            if (parsed.upstreamRunId) {
                run = await getWorkflowRun(parsed.upstreamRunId);
            } else {
                run = await findRunForRequest(parsed.requestedAtMs);
            }

            if (!run) {
                return jsonResponse(200, {
                    run_id: runId,
                    status: "queued",
                    requested_at: new Date(parsed.requestedAtMs).toISOString(),
                    accepted: true,
                    already_running: false,
                    status_url: buildStatusUrl(requestUrl, runId),
                    workflow: workflowFile,
                    ref: workflowRef,
                    upstream_run_id: null,
                    upstream_status: null,
                    upstream_conclusion: null,
                    html_url: null,
                    details_url: null,
                    error: null,
                });
            }

            return jsonResponse(
                200,
                serializeRun(
                    requestUrl,
                    createRunId(parsed.requestedAtMs, run.id),
                    parsed.requestedAtMs,
                    run,
                ),
            );
        }

        const bodyText = await req.text();
        let body = {};
        try {
            body = bodyText ? JSON.parse(bodyText) : {};
        } catch {
            body = {};
        }

        const activeRun = await findActiveRun();
        if (activeRun) {
            const requestedAtMs = Date.parse(activeRun.created_at ?? new Date().toISOString());
            return jsonResponse(202, {
                ...serializeRun(
                    requestUrl,
                    createRunId(requestedAtMs, activeRun.id),
                    requestedAtMs,
                    activeRun,
                ),
                accepted: false,
                already_running: true,
            });
        }

        const requestedAtMs = Date.now();
        const runId = createRunId(requestedAtMs);
        const forceRefresh = body?.force_refresh !== false;

        await dispatchRefresh(runId, requestedAtMs, forceRefresh);

        return jsonResponse(202, {
            run_id: runId,
            status: "queued",
            requested_at: new Date(requestedAtMs).toISOString(),
            accepted: true,
            already_running: false,
            status_url: buildStatusUrl(requestUrl, runId),
            workflow: workflowFile,
            ref: workflowRef,
            upstream_run_id: null,
            upstream_status: null,
            upstream_conclusion: null,
            html_url: null,
            details_url: null,
            error: null,
        });
    } catch (error) {
        return jsonResponse(500, {
            error: "Refresh webhook execution failed",
            details: error instanceof Error ? error.message : String(error),
        });
    }
});