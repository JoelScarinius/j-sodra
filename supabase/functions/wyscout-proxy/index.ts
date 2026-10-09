// Shared production Wyscout proxy.
// Callers must send X-Proxy-Key matching PROXY_SHARED_SECRET.
// Keep this credential server-side and never expose it in frontend/VITE_* code.
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": Deno.env.get("CORS_ORIGIN") ?? "",
  "Access-Control-Allow-Headers": "content-type,x-proxy-key",
  "Access-Control-Allow-Methods": "GET,OPTIONS",
};

const allowedEndpoints = [
  /^\/search$/,
  /^\/competitions\/\d+\/(?:seasons|matches)$/,
  /^\/seasons\/\d+(?:\/(?:teams|players|matches|standings|scorers|assistmen))?$/,
  /^\/teams\/\d+(?:\/(?:fixtures|matches))?$/,
  /^\/matches\/\d+(?:\/(?:events|formations|advancedstats(?:\/players)?))?$/,
];

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...corsHeaders },
  });
}

function constantTimeEqual(left: string, right: string) {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

serve(async (request) => {
  if (request.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }
  if (request.method !== "GET") {
    return jsonResponse({ error: "method_not_allowed" }, 405);
  }

  const expectedSecret = Deno.env.get("PROXY_SHARED_SECRET") ?? "";
  const suppliedSecret = request.headers.get("x-proxy-key") ?? "";
  if (!expectedSecret || !constantTimeEqual(expectedSecret, suppliedSecret)) {
    return jsonResponse({ error: "unauthorized" }, 401);
  }

  const clientId = Deno.env.get("WYSCOUT_CLIENT_ID") ?? "";
  const clientSecret =
    Deno.env.get("WYSCOUT_CLIENT_SECRET") ?? Deno.env.get("WYSCOUT_SECRET") ?? "";
  const baseUrl = (
    Deno.env.get("WYSCOUT_BASE_URL") ?? "https://apirest.wyscout.com/v3"
  ).replace(/\/$/, "");

  if (!clientId || !clientSecret) {
    return jsonResponse({ error: "wyscout_credentials_not_configured" }, 500);
  }

  const incomingUrl = new URL(request.url);
  const endpoint = incomingUrl.searchParams.get("endpoint") ?? "";
  if (!allowedEndpoints.some((rule) => rule.test(endpoint))) {
    return jsonResponse({ error: "endpoint_not_allowed", endpoint }, 403);
  }

  const upstreamUrl = new URL(baseUrl + endpoint);
  incomingUrl.searchParams.forEach((value, key) => {
    if (key !== "endpoint") upstreamUrl.searchParams.append(key, value);
  });

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 85_000);
  try {
    const upstreamResponse = await fetch(upstreamUrl, {
      method: "GET",
      signal: controller.signal,
      headers: {
        Authorization: "Basic " + btoa(`${clientId}:${clientSecret}`),
        Accept: "application/json",
      },
    });
    const body = await upstreamResponse.arrayBuffer();
    const headers = new Headers(corsHeaders);
    headers.set(
      "content-type",
      upstreamResponse.headers.get("content-type") ?? "application/octet-stream",
    );
    headers.set("x-upstream-status", String(upstreamResponse.status));
    const retryAfter = upstreamResponse.headers.get("retry-after");
    if (retryAfter) headers.set("retry-after", retryAfter);
    return new Response(body, { status: upstreamResponse.status, headers });
  } catch (error) {
    const isTimeout = error instanceof DOMException && error.name === "AbortError";
    return jsonResponse(
      {
        error: isTimeout ? "upstream_timeout" : "upstream_failure",
        detail: String(error),
      },
      isTimeout ? 504 : 502,
    );
  } finally {
    clearTimeout(timeout);
  }
});
