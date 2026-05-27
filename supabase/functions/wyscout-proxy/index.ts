// @ts-nocheck
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";

const corsHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
};

serve(async (req: Request) => {
    if (req.method === "OPTIONS") {
        return new Response("ok", { headers: corsHeaders });
    }

    try {
        const clientId = Deno.env.get("WYSCOUT_CLIENT_ID") ?? "";
        const clientSecret =
            Deno.env.get("WYSCOUT_CLIENT_SECRET") ?? Deno.env.get("WYSCOUT_SECRET") ?? "";
        const baseUrl = Deno.env.get("WYSCOUT_BASE_URL") ?? "https://apirest.wyscout.com/v3";

        if (!clientId || !clientSecret) {
            return new Response(
                JSON.stringify({
                    error: "Missing WYSCOUT_CLIENT_ID or WYSCOUT_CLIENT_SECRET/WYSCOUT_SECRET",
                }),
                {
                    status: 500,
                    headers: { "Content-Type": "application/json", ...corsHeaders },
                },
            );
        }

        const requestUrl = new URL(req.url);
        const endpoint = requestUrl.searchParams.get("endpoint");

        if (!endpoint) {
            return new Response(JSON.stringify({ error: "Missing endpoint query parameter" }), {
                status: 400,
                headers: { "Content-Type": "application/json", ...corsHeaders },
            });
        }

        const normalizedBase = baseUrl.replace(/\/$/, "");
        const normalizedEndpoint = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
        const upstreamUrl = new URL(`${normalizedBase}${normalizedEndpoint}`);

        // Forward every query param except "endpoint" itself.
        requestUrl.searchParams.forEach((value, key) => {
            if (key !== "endpoint") {
                upstreamUrl.searchParams.append(key, value);
            }
        });

        const basicAuth = "Basic " + btoa(`${clientId}:${clientSecret}`);

        const upstreamResponse = await fetch(upstreamUrl.toString(), {
            method: "GET",
            headers: {
                Authorization: basicAuth,
                Accept: "application/json",
            },
        });

        const bodyText = await upstreamResponse.text();

        return new Response(bodyText, {
            status: upstreamResponse.status,
            headers: {
                "Content-Type": upstreamResponse.headers.get("content-type") ?? "application/json",
                ...corsHeaders,
            },
        });
    } catch (error) {
        return new Response(
            JSON.stringify({
                error: "Proxy execution failed",
                details: error instanceof Error ? error.message : String(error),
            }),
            {
                status: 500,
                headers: { "Content-Type": "application/json", ...corsHeaders },
            },
        );
    }
});
