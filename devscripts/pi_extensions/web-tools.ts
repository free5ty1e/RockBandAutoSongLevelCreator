/**
 * web-tools — first-class web research tools for the Pi coding agent.
 *
 * Gives every Pi session a `web_search` tool (Bing RSS endpoint; DuckDuckGo
 * HTML/lite endpoints block datacenter IPs with an anomaly challenge — verified
 * 2026-10-24 from this devcontainer) and a `web_fetch` tool (URL → readable
 * text, HTML stripped, truncated with a pointer for follow-up reads).
 *
 * No npm dependencies: Node 18+ global fetch only. Load behavior and tool
 * contracts follow the Pi extensions guide (registerTool + TypeBox schema,
 * execute() throws to produce a failed tool result).
 *
 * Install (canonical copy lives in this repo): after a devcontainer rebuild,
 *   mkdir -p ~/.pi/agent/extensions
 *   cp devscripts/pi_extensions/web-tools.ts ~/.pi/agent/extensions/
 * then restart Pi (extensions load at session start).
 *
 * Research patterns that worked from this environment (2026-10-24):
 *   - Bing RSS: https://www.bing.com/search?q=<q>&format=rss   (broad, sometimes
 *     shallow on niche queries — quoted phrases help)
 *   - GitHub code search via `gh search code "<phrase>"` (authenticated, precise)
 *   - Wayback CDX: web.archive.org/cdx/search/cdx?url=<domain>*&output=text
 *     (note: IA goes temporarily offline sometimes)
 *   - Direct raw fetches: raw.githubusercontent.com, archive.org advancedsearch
 *     JSON API, r.jina.ai as an HTML→text fallback proxy
 */

import { Type } from "@earendil-works/pi-ai";
import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";

const UA =
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) " +
  "Chrome/120.0 Safari/537.36 AutoRB-research/1.0";

async function fetchText(url: string, timeoutMs: number = 25000): Promise<string> {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      headers: {
        "user-agent": UA,
        accept: "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
      },
      signal: ac.signal,
      redirect: "follow",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
    return await res.text();
  } finally {
    clearTimeout(t);
  }
}

function decodeEntities(s: string): string {
  // Entity literals are composed from the ampersand character so that no raw
  // HTML-entity sequences appear in this source (encoding-safe for edits).
  const a = String.fromCharCode(38);
  return s
    .replace(new RegExp(a + "nbsp;", "g"), " ")
    .replace(new RegExp(a + "amp;", "g"), a)
    .replace(new RegExp(a + "lt;", "g"), "<")
    .replace(new RegExp(a + "gt;", "g"), ">")
    .replace(new RegExp(a + "quot;", "g"), '"')
    .replace(new RegExp(a + "#39;", "g"), "'")
    .replace(new RegExp(a + "#x27;", "gi"), "'")
    .replace(new RegExp(a + "#(\\d+);", "g"), (_m, d) => String.fromCharCode(parseInt(d, 10)));
}

function stripTags(s: string): string {
  return decodeEntities(s.replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim();
}

/** HTML → readable plain text (headings/block elements become newlines). */
export function stripHtml(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<noscript[\s\S]*?<\/noscript>/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/<(\/?)(p|div|li|h[1-6]|tr|table|section|article|blockquote|pre|dt|dd)\b[^>]*>/gi, "\n")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .split("\n")
    .map((line) => decodeEntities(line).replace(/[ \t]+/g, " ").trim())
    .filter((line, i, arr) => line !== "" || (i > 0 && arr[i - 1] !== ""))
    .join("\n")
    .trim();
}

export interface SearchHit {
  title: string;
  link: string;
  snippet: string;
}

/** Parse a Bing RSS results channel into hits. */
export function parseBingRss(xml: string): SearchHit[] {
  const hits: SearchHit[] = [];
  const itemRe = /<item>([\s\S]*?)<\/item>/g;
  let m: RegExpExecArray | null;
  while ((m = itemRe.exec(xml)) !== null && hits.length < 25) {
    const block = m[1];
    const cdata = (tag: string): string => {
      const mm = block.match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)</${tag}>`));
      if (!mm) return "";
      return mm[1].trim().replace(/^<!\[CDATA\[/, "").replace(/\]\]>$/, "");
    };
    const link = cdata("link");
    const title = stripTags(cdata("title"));
    const snippet = stripTags(cdata("description"));
    if (link || title) hits.push({ title, link, snippet });
  }
  return hits;
}

const webSearch = defineTool({
  name: "web_search",
  label: "Web Search",
  description:
    "Search the public web and return result titles, URLs, and snippets " +
    "(Bing RSS provider). Results can be shallow on niche/long-tail queries — " +
    "for deep research combine with web_fetch on specific pages, `gh search " +
    "code/repos` for GitHub, and archive.org / Wayback CDX APIs. " +
    "DuckDuckGo HTML endpoints are blocked from datacenter IPs.",
  annotations: { readOnlyHint: true, openWorldHint: true, idempotentHint: true },
  parameters: Type.Object({
    query: Type.String({ description: "Search query (quoted phrases for exact terms)" }),
    count: Type.Optional(
      Type.Number({ description: "Max results to return (default 15)", minimum: 1, maximum: 25 }),
    ),
  }),
  async execute(_toolCallId, params) {
    const url =
      "https://www.bing.com/search?q=" +
      encodeURIComponent(params.query) +
      "&format=rss&count=" +
      (params.count ?? 15);
    const xml = await fetchText(url);
    const hits = parseBingRss(xml);
    if (hits.length === 0) {
      throw new Error(
        "No results parsed — the provider may have rate-limited or returned an " +
          "error page. Retry, simplify the query, or fetch a known URL directly " +
          "with web_fetch.",
      );
    }
    const text =
      hits
        .slice(0, params.count ?? 15)
        .map((h, i) => `${i + 1}. ${h.title}\n   ${h.link}\n   ${h.snippet}`)
        .join("\n\n") +
      "\n\n(call web_fetch on any link to read the full page)";
    return { content: [{ type: "text", text }], details: { hits } };
  },
});

const webFetch = defineTool({
  name: "web_fetch",
  label: "Web Fetch",
  description:
    "Fetch a URL and return readable text (HTML is stripped to plain text; " +
    "JSON/XML/raw files pass through). For docs, guidelines, articles, raw " +
    "GitHub files, and JSON/XML APIs. Truncates long pages and tells you the " +
    "full length so you can continue with a larger max_length.",
  annotations: { readOnlyHint: true, openWorldHint: true },
  parameters: Type.Object({
    url: Type.String({ description: "URL to fetch (http/https)" }),
    max_length: Type.Optional(
      Type.Number({ description: "Max characters to return (default 20000)" }),
    ),
  }),
  async execute(_toolCallId, params) {
    const raw = await fetchText(params.url);
    const looksLikeHtml = /<html|<!doctype/i.test(raw);
    const text = looksLikeHtml ? stripHtml(raw) : raw;
    const max = params.max_length ?? 20000;
    let out = text;
    let truncated = false;
    if (text.length > max) {
      out = text.slice(0, max);
      truncated = true;
      out +=
        "\n\n[... truncated at " + max + " of " + text.length +
        " chars — re-fetch with a larger max_length (or in sections) to continue]";
    }
    return {
      content: [{ type: "text", text: out }],
      details: { url: params.url, length: text.length, truncated, html_stripped: looksLikeHtml },
    };
  },
});

export default function (pi: ExtensionAPI) {
  pi.registerTool(webSearch);
  pi.registerTool(webFetch);
}
