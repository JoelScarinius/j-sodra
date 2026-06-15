// @ts-nocheck
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const FINAL_STATUSES = new Set([
  "played",
  "complete",
  "completed",
  "finished",
  "match ended",
]);

const KNOWN_LEAGUE_NAMES: Record<number, string> = {
  810: "Ettan",
};

function jsonResponse(status: number, payload: Record<string, unknown>) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

function normalizeStatus(value: unknown) {
  return String(value ?? "scheduled").trim().toLowerCase();
}

function isFinalStatus(value: unknown) {
  return FINAL_STATUSES.has(normalizeStatus(value));
}

function toNumber(value: unknown) {
  if (value === null || value === undefined || value === "") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function toIso(value: unknown) {
  if (!value) return null;
  const text = String(value);
  const parsed = new Date(text.includes("T") ? text : text.replace(" ", "T") + "Z");
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toISOString();
}

function parseMatchScore(label: unknown) {
  const text = String(label ?? "").trim();
  const match = text.match(/^(.*?)-(.*?),(\s*)(\d+)\s*-\s*(\d+)$/);
  if (!match) {
    return {
      label: text || null,
      homeName: null,
      awayName: null,
      homeScore: null,
      awayScore: null,
    };
  }

  return {
    label: text,
    homeName: match[1].trim(),
    awayName: match[2].trim(),
    homeScore: toNumber(match[4]),
    awayScore: toNumber(match[5]),
  };
}

function pickString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function isPlaceholderTeamName(value: unknown) {
  const text = String(value ?? "").trim();
  return !text || /^Team\s+\d+$/i.test(text);
}

function dateSortValue(value: unknown) {
  if (!value) return Number.NEGATIVE_INFINITY;
  const parsed = Date.parse(`${String(value).slice(0, 10)}T00:00:00Z`);
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

function pickCurrentSeasonRow(rows: any[]) {
  return [...rows].sort((left, right) => {
    const startDiff = dateSortValue(right?.start_date) - dateSortValue(left?.start_date);
    if (startDiff !== 0) return startDiff;

    const endDiff = dateSortValue(right?.end_date) - dateSortValue(left?.end_date);
    if (endDiff !== 0) return endDiff;

    return (toNumber(right?.provider_season_id) ?? 0) - (toNumber(left?.provider_season_id) ?? 0);
  })[0] ?? null;
}

function extractMatches(payload: any) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.matches)) return payload.matches;
  if (Array.isArray(payload?.data?.matches)) return payload.data.matches;
  return [];
}

function extractTeamIdsFromMatchDetail(detail: any) {
  const teamsData = detail?.teamsData;
  const home = teamsData?.home ?? {};
  const away = teamsData?.away ?? {};

  return {
    homeProviderTeamId: toNumber(home.teamId ?? home.id),
    awayProviderTeamId: toNumber(away.teamId ?? away.id),
    homeName: pickString(home.name, home.team?.name),
    awayName: pickString(away.name, away.team?.name),
    homeScore: toNumber(home.score),
    awayScore: toNumber(away.score),
    homeHtScore: toNumber(home.halfTimeScore),
    awayHtScore: toNumber(away.halfTimeScore),
  };
}

function inferSeasonName(
  summary: any,
  seasonId: number,
  kickoffValues: string[] = [],
) {
  const providerName = pickString(
    summary?.season?.name,
    summary?.seasonName,
    summary?.season?.displayName,
  );

  const years = Array.from(
    new Set(
      kickoffValues
        .map((value) => {
          const parsed = new Date(value);
          return Number.isNaN(parsed.getTime()) ? null : parsed.getUTCFullYear();
        })
        .filter((value): value is number => value !== null),
    ),
  ).sort((a, b) => a - b);

  if (years.length === 1) return String(years[0]);
  if (years.length > 1) return `${years[0]}/${years[years.length - 1]}`;

  return providerName ?? `Season ${seasonId}`;
}

function inferLeagueName(
  firstSummary: any,
  providerLeagueId: number,
  fallbackName: string | null,
  competitionDetail: any = null,
) {
  return pickString(
    fallbackName,
    competitionDetail?.name,
    competitionDetail?.competition?.name,
    firstSummary?.competition?.name,
    firstSummary?.competitionName,
    KNOWN_LEAGUE_NAMES[providerLeagueId],
    `Competition ${providerLeagueId}`,
  );
}

function teamProfileRow(
  profile: any,
  providerTeamId: number,
  fallbackName: string | null,
  existingRow: any = null,
) {
  const preservedName = existingRow && !isPlaceholderTeamName(existingRow.name)
    ? existingRow.name
    : null;

  return {
    provider: "wyscout",
    provider_team_id: providerTeamId,
    name: pickString(
      profile?.name,
      profile?.officialName,
      preservedName,
      fallbackName,
      `Team ${providerTeamId}`,
    ),
    short_name: pickString(profile?.shortName, existingRow?.short_name, fallbackName),
    official_name: pickString(
      profile?.officialName,
      profile?.name,
      existingRow?.official_name,
      preservedName,
      fallbackName,
    ),
    logo_url: pickString(
      profile?.logoUrl,
      profile?.imageData?.url,
      profile?.imageData?.avatarUrl,
      profile?.images?.logo,
      existingRow?.logo_url,
    ),
    country_name: pickString(profile?.area?.name, profile?.country?.name, existingRow?.country_name),
    venue_name: pickString(profile?.venueName, profile?.venue?.name, existingRow?.venue_name),
    metadata: profile ?? existingRow?.metadata ?? {},
  };
}

function buildSummaryRecord(summary: any) {
  const parsed = parseMatchScore(summary?.label);
  return {
    providerMatchId: toNumber(summary?.matchId ?? summary?.wyId ?? summary?.id),
    providerSeasonId: toNumber(summary?.seasonId ?? summary?.season?.wyId ?? summary?.season?.id),
    providerLeagueId: toNumber(summary?.competitionId ?? summary?.competition?.wyId ?? summary?.competition?.id),
    roundNumber: toNumber(summary?.gameweek ?? summary?.roundNumber),
    stageName: pickString(summary?.stageName, summary?.roundName),
    label: parsed.label,
    homeName: parsed.homeName,
    awayName: parsed.awayName,
    homeScore: parsed.homeScore,
    awayScore: parsed.awayScore,
    kickoffAt: toIso(summary?.dateutc ?? summary?.date),
    status: normalizeStatus(summary?.status),
    raw: summary,
  };
}

function expectedPointsFromXg(_xgFor: number | null, _xgAgainst: number | null) {
  return null;
}

function summarizeEvents(events: any[], providerTeamId: number | null) {
  let shots = 0;
  let shotsOnTarget = 0;
  let corners = 0;
  let xg = 0;
  let xt = 0;
  let hasXt = false;
  let eventCount = 0;

  for (const event of events) {
    if (toNumber(event?.team?.id) !== providerTeamId) continue;

    eventCount += 1;
    if (event?.shot) {
      shots += 1;
      xg += Number(event?.shot?.xg ?? 0);
      const secondary = Array.isArray(event?.type?.secondary) ? event.type.secondary : [];
      if (event?.shot?.isGoal || event?.shot?.onTarget || secondary.includes("goal") || secondary.includes("on_target")) {
        shotsOnTarget += 1;
      }
    }

    const secondary = Array.isArray(event?.type?.secondary) ? event.type.secondary : [];
    if (event?.type?.primary === "corner" || secondary.includes("corner")) {
      corners += 1;
    }

    const xtValue = toNumber(event?.xt ?? event?.xT ?? event?.pass?.xT ?? event?.carry?.xT ?? event?.possession?.attack?.xT);
    if (xtValue !== null) {
      xt += xtValue;
      hasXt = true;
    }
  }

  return {
    shots,
    shotsOnTarget,
    corners,
    xg,
    xt: hasXt ? xt : null,
    eventCount,
  };
}

function buildTeamStatRows(
  matchRow: any,
  detail: any,
  events: any[],
  options: {
    existingHomeStat?: any;
    existingAwayStat?: any;
    preserveExistingMetrics?: boolean;
  } = {},
) {
  const sides = extractTeamIdsFromMatchDetail(detail);
  const homeProviderTeamId = sides.homeProviderTeamId;
  const awayProviderTeamId = sides.awayProviderTeamId;
  const existingHomeStat = options.existingHomeStat ?? null;
  const existingAwayStat = options.existingAwayStat ?? null;
  const preserveExistingMetrics = Boolean(options.preserveExistingMetrics);

  if (!homeProviderTeamId || !awayProviderTeamId || !matchRow.home_team_id || !matchRow.away_team_id) {
    return [];
  }

  const homeScore = toNumber(sides.homeScore ?? matchRow.home_score) ?? 0;
  const awayScore = toNumber(sides.awayScore ?? matchRow.away_score) ?? 0;
  const homeStats = summarizeEvents(events, homeProviderTeamId);
  const awayStats = summarizeEvents(events, awayProviderTeamId);
  const matchStatus = normalizeStatus(matchRow.status);
  const finalMatch = isFinalStatus(matchStatus);

  const homeHasComputedMetrics = !preserveExistingMetrics && homeStats.eventCount > 0;
  const awayHasComputedMetrics = !preserveExistingMetrics && awayStats.eventCount > 0;

  const homeXgFor = homeHasComputedMetrics ? homeStats.xg : existingHomeStat?.xg_for ?? null;
  const homeXgAgainst = awayHasComputedMetrics
    ? awayStats.xg
    : existingHomeStat?.xg_against ?? existingAwayStat?.xg_for ?? null;
  const awayXgFor = awayHasComputedMetrics ? awayStats.xg : existingAwayStat?.xg_for ?? null;
  const awayXgAgainst = homeHasComputedMetrics
    ? homeStats.xg
    : existingAwayStat?.xg_against ?? existingHomeStat?.xg_for ?? null;

  const homeXtFor = homeHasComputedMetrics ? homeStats.xt : existingHomeStat?.xt_for ?? null;
  const homeXtAgainst = awayHasComputedMetrics
    ? awayStats.xt
    : existingHomeStat?.xt_against ?? existingAwayStat?.xt_for ?? null;
  const awayXtFor = awayHasComputedMetrics ? awayStats.xt : existingAwayStat?.xt_for ?? null;
  const awayXtAgainst = homeHasComputedMetrics
    ? homeStats.xt
    : existingAwayStat?.xt_against ?? existingHomeStat?.xt_for ?? null;

  const homeResult = finalMatch
    ? homeScore > awayScore
      ? "W"
      : homeScore === awayScore
        ? "D"
        : "L"
    : "P";
  const awayResult = finalMatch
    ? awayScore > homeScore
      ? "W"
      : awayScore === homeScore
        ? "D"
        : "L"
    : "P";

  const homePoints = homeResult === "W" ? 3 : homeResult === "D" ? 1 : 0;
  const awayPoints = awayResult === "W" ? 3 : awayResult === "D" ? 1 : 0;

  return [
    {
      match_id: matchRow.id,
      season_id: matchRow.season_id,
      league_id: matchRow.league_id,
      team_id: matchRow.home_team_id,
      opponent_team_id: matchRow.away_team_id,
      venue: "home",
      match_status: matchStatus,
      match_kickoff_at: matchRow.kickoff_at,
      round_number: matchRow.round_number,
      result: homeResult,
      goals_for: homeScore,
      goals_against: awayScore,
      points: homePoints,
      xg_for: homeXgFor,
      xg_against: homeXgAgainst,
      xp: existingHomeStat?.xp ?? expectedPointsFromXg(homeXgFor, homeXgAgainst),
      xt_for: homeXtFor,
      xt_against: homeXtAgainst,
      shots: homeHasComputedMetrics ? homeStats.shots : toNumber(existingHomeStat?.shots) ?? 0,
      shots_on_target: homeHasComputedMetrics ? homeStats.shotsOnTarget : toNumber(existingHomeStat?.shots_on_target) ?? 0,
      corners: homeHasComputedMetrics ? homeStats.corners : toNumber(existingHomeStat?.corners) ?? 0,
      clean_sheet: finalMatch && awayScore === 0,
      event_count: homeHasComputedMetrics ? homeStats.eventCount : toNumber(existingHomeStat?.event_count) ?? 0,
      source_updated_at: new Date().toISOString(),
      payload: { source: "sync-league", detail },
    },
    {
      match_id: matchRow.id,
      season_id: matchRow.season_id,
      league_id: matchRow.league_id,
      team_id: matchRow.away_team_id,
      opponent_team_id: matchRow.home_team_id,
      venue: "away",
      match_status: matchStatus,
      match_kickoff_at: matchRow.kickoff_at,
      round_number: matchRow.round_number,
      result: awayResult,
      goals_for: awayScore,
      goals_against: homeScore,
      points: awayPoints,
      xg_for: awayXgFor,
      xg_against: awayXgAgainst,
      xp: existingAwayStat?.xp ?? expectedPointsFromXg(awayXgFor, awayXgAgainst),
      xt_for: awayXtFor,
      xt_against: awayXtAgainst,
      shots: awayHasComputedMetrics ? awayStats.shots : toNumber(existingAwayStat?.shots) ?? 0,
      shots_on_target: awayHasComputedMetrics ? awayStats.shotsOnTarget : toNumber(existingAwayStat?.shots_on_target) ?? 0,
      corners: awayHasComputedMetrics ? awayStats.corners : toNumber(existingAwayStat?.corners) ?? 0,
      clean_sheet: finalMatch && homeScore === 0,
      event_count: awayHasComputedMetrics ? awayStats.eventCount : toNumber(existingAwayStat?.event_count) ?? 0,
      source_updated_at: new Date().toISOString(),
      payload: { source: "sync-league", detail },
    },
  ];
}

function buildEventRows(matchRow: any, events: any[], providerToLocalTeamId: Map<number, number>) {
  return events.map((event, index) => {
    const secondary = Array.isArray(event?.type?.secondary) ? event.type.secondary : [];
    const teamProviderId = toNumber(event?.team?.id);
    const opponentProviderId = toNumber(event?.opponentTeam?.id);
    return {
      provider: "wyscout",
      provider_event_id: String(event?.id ?? `${matchRow.provider_match_id}:${index}`),
      match_id: matchRow.id,
      season_id: matchRow.season_id,
      league_id: matchRow.league_id,
      team_id: teamProviderId ? providerToLocalTeamId.get(teamProviderId) ?? null : null,
      opponent_team_id: opponentProviderId ? providerToLocalTeamId.get(opponentProviderId) ?? null : null,
      provider_player_id: toNumber(event?.player?.id),
      event_type: pickString(event?.type?.primary),
      event_sub_type: secondary[0] ?? null,
      period: pickString(event?.matchPeriod),
      minute: toNumber(event?.minute),
      second: toNumber(event?.second),
      x: toNumber(event?.location?.x),
      y: toNumber(event?.location?.y),
      end_x: toNumber(event?.pass?.endLocation?.x ?? event?.carry?.endLocation?.x ?? event?.shot?.endLocation?.x),
      end_y: toNumber(event?.pass?.endLocation?.y ?? event?.carry?.endLocation?.y ?? event?.shot?.endLocation?.y),
      xg: toNumber(event?.shot?.xg),
      xt: toNumber(event?.xt ?? event?.xT ?? event?.pass?.xT ?? event?.carry?.xT ?? event?.possession?.attack?.xT),
      is_shot: Boolean(event?.shot),
      is_goal: Boolean(event?.shot?.isGoal || secondary.includes("goal")),
      source_updated_at: new Date().toISOString(),
      payload: event,
    };
  });
}

async function mapWithConcurrency<T, R>(items: T[], concurrency: number, worker: (item: T) => Promise<R>) {
  const results: R[] = [];
  let currentIndex = 0;

  async function runWorker() {
    while (currentIndex < items.length) {
      const index = currentIndex;
      currentIndex += 1;
      results[index] = await worker(items[index]);
    }
  }

  const runners = Array.from({ length: Math.max(1, concurrency) }, () => runWorker());
  await Promise.all(runners);
  return results;
}

async function wyscoutFetch(endpoint: string, params: Record<string, unknown> = {}) {
  const clientId = Deno.env.get("WYSCOUT_CLIENT_ID") ?? "";
  const clientSecret = Deno.env.get("WYSCOUT_CLIENT_SECRET") ?? Deno.env.get("WYSCOUT_SECRET") ?? "";
  const baseUrl = (Deno.env.get("WYSCOUT_BASE_URL") ?? "https://apirest.wyscout.com/v3").replace(/\/+$/, "");

  if (!clientId || !clientSecret) {
    throw new Error("Missing WYSCOUT_CLIENT_ID or WYSCOUT_CLIENT_SECRET/WYSCOUT_SECRET");
  }

  const url = new URL(`${baseUrl}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }

  const response = await fetch(url.toString(), {
    headers: {
      Authorization: `Basic ${btoa(`${clientId}:${clientSecret}`)}`,
      Accept: "application/json",
    },
  });

  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = null;
  }

  if (!response.ok) {
    throw new Error(payload?.error || payload?.message || text || `Wyscout request failed with ${response.status}`);
  }

  return payload;
}

function adminClient() {
  const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

  if (!supabaseUrl || !serviceRoleKey) {
    throw new Error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY");
  }

  return createClient(supabaseUrl, serviceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

async function selectByProviderIds(client: any, table: string, column: string, ids: number[]) {
  const rows: any[] = [];
  for (let i = 0; i < ids.length; i += 200) {
    const batch = ids.slice(i, i + 200);
    if (!batch.length) continue;
    const { data, error } = await client.from(table).select("*").eq("provider", "wyscout").in(column, batch);
    if (error) throw error;
    rows.push(...(data ?? []));
  }
  return rows;
}

async function selectByIds(client: any, table: string, column: string, ids: Array<number | string>) {
  const rows: any[] = [];
  for (let i = 0; i < ids.length; i += 200) {
    const batch = ids.slice(i, i + 200);
    if (!batch.length) continue;
    const { data, error } = await client.from(table).select("*").in(column, batch);
    if (error) throw error;
    rows.push(...(data ?? []));
  }
  return rows;
}

serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  if (req.method !== "POST") {
    return jsonResponse(405, { error: "Method not allowed" });
  }

  const syncToken = Deno.env.get("SYNC_LEAGUE_TOKEN") ?? "";
  if (syncToken) {
    const authHeader = req.headers.get("Authorization") ?? "";
    if (authHeader !== `Bearer ${syncToken}`) {
      return jsonResponse(401, { error: "Unauthorized" });
    }
  }

  let body: any = {};
  try {
    body = await req.json();
  } catch {
    body = {};
  }

  const providerLeagueId = toNumber(body?.provider_league_id ?? body?.competition_id);
  if (!providerLeagueId) {
    return jsonResponse(400, { error: "Missing provider_league_id or competition_id" });
  }

  const requestedSeasonIds = Array.isArray(body?.provider_season_ids)
    ? body.provider_season_ids.map((value: unknown) => toNumber(value)).filter(Boolean)
    : [];
  const includeEvents = body?.include_events !== false;
  const detailConcurrency = Math.max(1, Math.min(12, Number(body?.detail_concurrency ?? 8)));
  const eventConcurrency = Math.max(1, Math.min(8, Number(body?.event_concurrency ?? 4)));
  const hydrateRecentHours = Math.max(0, Number(body?.hydrate_recent_hours ?? 168));
  const startedAt = new Date().toISOString();

  const supabase = adminClient();

  let runId = null;
  try {
    const { data: insertedRun, error: runError } = await supabase
      .from("sync_runs")
      .insert({
        provider: "wyscout",
        provider_league_id: providerLeagueId,
        provider_season_ids: requestedSeasonIds,
        run_kind: includeEvents ? "incremental_with_events" : "incremental",
        requested_by: "sync-league edge function",
        status: "running",
        started_at: startedAt,
        metadata: body,
      })
      .select("id")
      .single();

    if (runError) throw runError;
    runId = insertedRun?.id ?? null;

    let competitionDetail = null;
    try {
      competitionDetail = await wyscoutFetch(`/competitions/${providerLeagueId}`);
    } catch {
      competitionDetail = null;
    }

    const competitionPayload = await wyscoutFetch(`/competitions/${providerLeagueId}/matches`);
    const summaries = extractMatches(competitionPayload)
      .map(buildSummaryRecord)
      .filter((record) => record.providerMatchId && record.providerSeasonId);

    const selectedSummaries = requestedSeasonIds.length
      ? summaries.filter((record) => requestedSeasonIds.includes(record.providerSeasonId))
      : summaries;

    if (!selectedSummaries.length) {
      throw new Error("No matches found for the selected league and season scope");
    }

    const firstSummary = selectedSummaries[0]?.raw ?? null;
    const leagueRow = {
      provider: "wyscout",
      provider_league_id: providerLeagueId,
      name: inferLeagueName(
        firstSummary,
        providerLeagueId,
        pickString(body?.league_name),
        competitionDetail,
      ),
      country_name: pickString(
        competitionDetail?.area?.name,
        competitionDetail?.country?.name,
        firstSummary?.competition?.area?.name,
        body?.country_name,
      ),
      tier: pickString(body?.tier),
      logo_url: pickString(body?.logo_url),
      metadata: { request: body, competition_detail: competitionDetail ?? {} },
    };

    const { error: upsertLeagueError } = await supabase
      .from("leagues")
      .upsert(leagueRow, { onConflict: "provider,provider_league_id" });
    if (upsertLeagueError) throw upsertLeagueError;

    const existingLeagueRows = await selectByProviderIds(supabase, "leagues", "provider_league_id", [providerLeagueId]);
    const localLeague = existingLeagueRows[0];
    if (!localLeague?.id) {
      throw new Error("Failed to load local league row after upsert");
    }

    const seasonBuckets = new Map<number, any[]>();
    for (const summary of selectedSummaries) {
      if (!seasonBuckets.has(summary.providerSeasonId)) {
        seasonBuckets.set(summary.providerSeasonId, []);
      }
      seasonBuckets.get(summary.providerSeasonId).push(summary);
    }

    const orderedSeasonIds = [...seasonBuckets.keys()].sort((a, b) => a - b);
    const seasonRows = orderedSeasonIds.map((providerSeasonId) => {
      const rows = seasonBuckets.get(providerSeasonId) ?? [];
      const kickoffValues = rows.map((row) => row.kickoffAt).filter(Boolean).sort();
      return {
        provider: "wyscout",
        provider_season_id: providerSeasonId,
        league_id: localLeague.id,
        name: inferSeasonName(rows[0]?.raw, providerSeasonId, kickoffValues),
        start_date: kickoffValues[0] ? kickoffValues[0].slice(0, 10) : null,
        end_date: kickoffValues[kickoffValues.length - 1] ? kickoffValues[kickoffValues.length - 1].slice(0, 10) : null,
        is_current: false,
        sync_policy: "incremental",
        metadata: { provider_league_id: providerLeagueId },
      };
    });

    const { error: upsertSeasonsError } = await supabase
      .from("seasons")
      .upsert(seasonRows, { onConflict: "provider,provider_season_id" });
    if (upsertSeasonsError) throw upsertSeasonsError;

    const { data: allLeagueSeasons, error: allLeagueSeasonsError } = await supabase
      .from("seasons")
      .select("id, provider_season_id, start_date, end_date")
      .eq("league_id", localLeague.id);
    if (allLeagueSeasonsError) throw allLeagueSeasonsError;

    const currentSeasonRow = pickCurrentSeasonRow(allLeagueSeasons ?? []);
    if (currentSeasonRow?.id) {
      const { error: resetCurrentError } = await supabase
        .from("seasons")
        .update({ is_current: false })
        .eq("league_id", localLeague.id);
      if (resetCurrentError) throw resetCurrentError;

      const { error: setCurrentError } = await supabase
        .from("seasons")
        .update({ is_current: true })
        .eq("id", currentSeasonRow.id);
      if (setCurrentError) throw setCurrentError;
    }

    const localSeasons = await selectByProviderIds(supabase, "seasons", "provider_season_id", orderedSeasonIds);
    const seasonIdMap = new Map<number, number>(localSeasons.map((row) => [row.provider_season_id, row.id]));

    const providerMatchIds = selectedSummaries.map((summary) => summary.providerMatchId);
    const existingMatches = await selectByProviderIds(supabase, "matches", "provider_match_id", providerMatchIds);
    const existingMatchMap = new Map<number, any>(existingMatches.map((row) => [row.provider_match_id, row]));
    const existingMatchIds = existingMatches
      .map((row) => row.id)
      .filter((value) => Number.isFinite(Number(value)));
    const existingStats = existingMatchIds.length
      ? await selectByIds(supabase, "team_match_stats", "match_id", existingMatchIds)
      : [];
    const statsPerMatch = new Map<number, number>();
    const existingStatsByMatchTeam = new Map<string, any>();
    for (const row of existingStats) {
      const matchId = Number(row.match_id);
      statsPerMatch.set(matchId, (statsPerMatch.get(matchId) ?? 0) + 1);
      existingStatsByMatchTeam.set(`${matchId}:${row.team_id}`, row);
    }

    const nowMs = Date.now();
    const hydrationCandidates = selectedSummaries.filter((summary) => {
      const existing = existingMatchMap.get(summary.providerMatchId);
      if (!existing) return true;
      if (!existing.home_team_id || !existing.away_team_id) return true;
      if (isFinalStatus(summary.status ?? existing.status) && (statsPerMatch.get(Number(existing.id)) ?? 0) < 2) {
        return true;
      }
      if (summary.status !== normalizeStatus(existing.status)) return true;
      if ((summary.homeScore ?? null) !== (existing.home_score ?? null)) return true;
      if ((summary.awayScore ?? null) !== (existing.away_score ?? null)) return true;
      if (!summary.kickoffAt) return false;
      const kickoffMs = Date.parse(summary.kickoffAt);
      if (!Number.isFinite(kickoffMs)) return false;
      return Math.abs(nowMs - kickoffMs) <= hydrateRecentHours * 60 * 60 * 1000;
    });

    const hydratedDetails = await mapWithConcurrency(hydrationCandidates, detailConcurrency, async (summary) => {
      const detail = await wyscoutFetch(`/matches/${summary.providerMatchId}`, { useSides: 1 });
      return { providerMatchId: summary.providerMatchId, detail };
    });
    const detailMap = new Map<number, any>(hydratedDetails.map((row) => [row.providerMatchId, row.detail]));

    const providerTeamIds = new Set<number>();
    const detailTeamFallbackNames = new Map<number, string>();
    for (const detail of detailMap.values()) {
      const sides = extractTeamIdsFromMatchDetail(detail);
      if (sides.homeProviderTeamId) {
        providerTeamIds.add(sides.homeProviderTeamId);
        if (sides.homeName) detailTeamFallbackNames.set(sides.homeProviderTeamId, sides.homeName);
      }
      if (sides.awayProviderTeamId) {
        providerTeamIds.add(sides.awayProviderTeamId);
        if (sides.awayName) detailTeamFallbackNames.set(sides.awayProviderTeamId, sides.awayName);
      }
    }

    const teamProfiles = await mapWithConcurrency([...providerTeamIds], detailConcurrency, async (providerTeamId) => {
      try {
        const profile = await wyscoutFetch(`/teams/${providerTeamId}`);
        return { providerTeamId, profile };
      } catch {
        return { providerTeamId, profile: null };
      }
    });

    const teamRows = teamProfiles.map(({ providerTeamId, profile }) =>
      teamProfileRow(profile, providerTeamId, detailTeamFallbackNames.get(providerTeamId) ?? null),
    );

    if (teamRows.length) {
      const { error: upsertTeamsError } = await supabase
        .from("teams")
        .upsert(teamRows, { onConflict: "provider,provider_team_id" });
      if (upsertTeamsError) throw upsertTeamsError;
    }

    const localTeams = providerTeamIds.size
      ? await selectByProviderIds(supabase, "teams", "provider_team_id", [...providerTeamIds])
      : [];
    const providerToLocalTeamId = new Map<number, number>(localTeams.map((row) => [row.provider_team_id, row.id]));

    const seasonTeamRows: any[] = [];
    const matchRows: any[] = [];

    for (const summary of selectedSummaries) {
      const existing = existingMatchMap.get(summary.providerMatchId);
      const detail = detailMap.get(summary.providerMatchId) ?? null;
      const sides = detail ? extractTeamIdsFromMatchDetail(detail) : null;
      const homeLocalTeamId = sides?.homeProviderTeamId
        ? providerToLocalTeamId.get(sides.homeProviderTeamId) ?? existing?.home_team_id ?? null
        : existing?.home_team_id ?? null;
      const awayLocalTeamId = sides?.awayProviderTeamId
        ? providerToLocalTeamId.get(sides.awayProviderTeamId) ?? existing?.away_team_id ?? null
        : existing?.away_team_id ?? null;

      if (homeLocalTeamId) {
        seasonTeamRows.push({ season_id: seasonIdMap.get(summary.providerSeasonId), league_id: localLeague.id, team_id: homeLocalTeamId, is_active: true, metadata: {} });
      }
      if (awayLocalTeamId) {
        seasonTeamRows.push({ season_id: seasonIdMap.get(summary.providerSeasonId), league_id: localLeague.id, team_id: awayLocalTeamId, is_active: true, metadata: {} });
      }

      matchRows.push({
        provider: "wyscout",
        provider_match_id: summary.providerMatchId,
        league_id: localLeague.id,
        season_id: seasonIdMap.get(summary.providerSeasonId),
        round_number: summary.roundNumber,
        stage_name: summary.stageName,
        label: detail?.label ?? summary.label,
        kickoff_at: detail?.dateutc ? toIso(detail.dateutc) : summary.kickoffAt,
        status: detail?.status ? normalizeStatus(detail.status) : summary.status,
        venue_name: pickString(detail?.venue?.name, detail?.venueName),
        home_team_id: homeLocalTeamId,
        away_team_id: awayLocalTeamId,
        home_score: toNumber(sides?.homeScore ?? summary.homeScore),
        away_score: toNumber(sides?.awayScore ?? summary.awayScore),
        home_ht_score: toNumber(sides?.homeHtScore),
        away_ht_score: toNumber(sides?.awayHtScore),
        source_updated_at: startedAt,
        last_synced_at: startedAt,
        payload: detail ?? summary.raw,
      });
    }

    if (seasonTeamRows.length) {
      const uniqueSeasonTeams = Array.from(
        new Map(
          seasonTeamRows.map((row) => [`${row.season_id}:${row.team_id}`, row]),
        ).values(),
      );
      const { error: seasonTeamsError } = await supabase
        .from("season_teams")
        .upsert(uniqueSeasonTeams, { onConflict: "season_id,team_id" });
      if (seasonTeamsError) throw seasonTeamsError;
    }

    const { error: upsertMatchesError } = await supabase
      .from("matches")
      .upsert(matchRows, { onConflict: "provider,provider_match_id" });
    if (upsertMatchesError) throw upsertMatchesError;

    const refreshedMatches = await selectByProviderIds(supabase, "matches", "provider_match_id", providerMatchIds);
    const refreshedMatchMap = new Map<number, any>(refreshedMatches.map((row) => [row.provider_match_id, row]));

    const refreshedLocalTeamIds = Array.from(new Set(
      refreshedMatches
        .flatMap((row) => [toNumber(row.home_team_id), toNumber(row.away_team_id)])
        .filter((value): value is number => value !== null),
    ));
    const existingSeasonTeams = refreshedLocalTeamIds.length
      ? await selectByIds(supabase, "teams", "id", refreshedLocalTeamIds)
      : [];
    const existingTeamsByProviderId = new Map<number, any>(
      existingSeasonTeams
        .filter((row) => row?.provider_team_id)
        .map((row) => [row.provider_team_id, row]),
    );
    const providerTeamIdsToRefresh = new Set<number>(providerTeamIds);
    for (const teamRow of existingSeasonTeams) {
      const providerTeamId = toNumber(teamRow?.provider_team_id);
      if (!providerTeamId) continue;
      if (
        isPlaceholderTeamName(teamRow?.name)
        || !pickString(teamRow?.short_name, teamRow?.logo_url, teamRow?.official_name)
      ) {
        providerTeamIdsToRefresh.add(providerTeamId);
      }
    }

    if (providerTeamIdsToRefresh.size) {
      const refreshedTeamProfiles = await mapWithConcurrency([...providerTeamIdsToRefresh], detailConcurrency, async (providerTeamId) => {
        try {
          const profile = await wyscoutFetch(`/teams/${providerTeamId}`);
          return { providerTeamId, profile };
        } catch {
          return { providerTeamId, profile: null };
        }
      });

      const refreshedTeamRows = refreshedTeamProfiles.map(({ providerTeamId, profile }) => {
        const existingTeam = existingTeamsByProviderId.get(providerTeamId) ?? null;
        const fallbackName = detailTeamFallbackNames.get(providerTeamId)
          ?? (!isPlaceholderTeamName(existingTeam?.name) ? existingTeam?.name : null);
        return teamProfileRow(profile, providerTeamId, fallbackName, existingTeam);
      });

      if (refreshedTeamRows.length) {
        const { error: refreshTeamsError } = await supabase
          .from("teams")
          .upsert(refreshedTeamRows, { onConflict: "provider,provider_team_id" });
        if (refreshTeamsError) throw refreshTeamsError;
      }
    }

    const finalHydrationTargets = hydrationCandidates.filter((summary) => {
      const matchRow = refreshedMatchMap.get(summary.providerMatchId);
      return matchRow && isFinalStatus(matchRow.status);
    });

    const hydratedEvents = includeEvents
      ? await mapWithConcurrency(finalHydrationTargets, eventConcurrency, async (summary) => {
        const payload = await wyscoutFetch(`/matches/${summary.providerMatchId}/events`);
        return {
          providerMatchId: summary.providerMatchId,
          events: Array.isArray(payload?.events) ? payload.events : Array.isArray(payload) ? payload : [],
        };
      })
      : [];
    const eventMap = new Map<number, any[]>(hydratedEvents.map((row) => [row.providerMatchId, row.events]));

    let eventsUpserted = 0;
    for (const summary of finalHydrationTargets) {
      const matchRow = refreshedMatchMap.get(summary.providerMatchId);
      const detail = detailMap.get(summary.providerMatchId);
      if (!matchRow || !detail) continue;

      const events = eventMap.get(summary.providerMatchId) ?? [];
      const homeStatKey = `${matchRow.id}:${matchRow.home_team_id}`;
      const awayStatKey = `${matchRow.id}:${matchRow.away_team_id}`;
      const statRows = buildTeamStatRows(matchRow, detail, events, {
        existingHomeStat: existingStatsByMatchTeam.get(homeStatKey) ?? null,
        existingAwayStat: existingStatsByMatchTeam.get(awayStatKey) ?? null,
        preserveExistingMetrics: !includeEvents,
      });
      if (statRows.length) {
        const { error: deleteStatsError } = await supabase
          .from("team_match_stats")
          .delete()
          .eq("match_id", matchRow.id);
        if (deleteStatsError) throw deleteStatsError;

        const { error: upsertStatsError } = await supabase
          .from("team_match_stats")
          .insert(statRows);
        if (upsertStatsError) throw upsertStatsError;
      }

      if (includeEvents) {
        const eventRows = buildEventRows(matchRow, events, providerToLocalTeamId);
        const { error: deleteEventsError } = await supabase
          .from("events")
          .delete()
          .eq("match_id", matchRow.id);
        if (deleteEventsError) throw deleteEventsError;

        if (eventRows.length) {
          const { error: insertEventsError } = await supabase
            .from("events")
            .insert(eventRows);
          if (insertEventsError) throw insertEventsError;
          eventsUpserted += eventRows.length;
        }
      }
    }

    const affectedSeasonIds = Array.from(new Set(matchRows.map((row) => row.season_id).filter(Boolean)));
    for (const seasonId of affectedSeasonIds) {
      const { error: refreshError } = await supabase.rpc("refresh_season_derived_data", {
        p_season_id: seasonId,
        p_snapshot_key: "current",
      });
      if (refreshError) throw refreshError;
    }

    const affectedTeamIds = Array.from(
      new Set(
        [...providerToLocalTeamId.values()].filter(Boolean),
      ),
    );

    if (runId) {
      const { error: finishRunError } = await supabase
        .from("sync_runs")
        .update({
          status: "succeeded",
          finished_at: new Date().toISOString(),
          matches_scanned: selectedSummaries.length,
          matches_hydrated: hydrationCandidates.length,
          matches_upserted: matchRows.length,
          events_upserted: eventsUpserted,
          affected_season_ids: affectedSeasonIds,
          affected_team_ids: affectedTeamIds,
        })
        .eq("id", runId);
      if (finishRunError) throw finishRunError;
    }

    return jsonResponse(200, {
      ok: true,
      run_id: runId,
      provider_league_id: providerLeagueId,
      provider_season_ids: orderedSeasonIds,
      matches_scanned: selectedSummaries.length,
      matches_hydrated: hydrationCandidates.length,
      matches_upserted: matchRows.length,
      events_upserted: eventsUpserted,
      affected_season_ids: affectedSeasonIds,
      affected_team_ids: affectedTeamIds,
      note: "This sync only upserts league data and derived tables. It does not delete unrelated seasons, reports, or storage objects.",
    });
  } catch (error) {
    if (runId) {
      try {
        await supabase.from("sync_runs").update({
          status: "failed",
          finished_at: new Date().toISOString(),
          error: error instanceof Error ? error.message : String(error),
        }).eq("id", runId);
      } catch {
        // Best effort failure reporting.
      }
    }

    return jsonResponse(500, {
      error: "League sync failed",
      details: error instanceof Error ? error.message : String(error),
      run_id: runId,
    });
  }
});