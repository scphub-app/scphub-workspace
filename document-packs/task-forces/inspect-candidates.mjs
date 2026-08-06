#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const cheerio = require("../../tools/node_modules/cheerio");
const { fetchHTML } = require("../../tools/lib/http");
const { extractTags, extractDiscussURL } = require("../../tools/lib/download");

const here = path.dirname(fileURLToPath(import.meta.url));
const indexes = [
  {
    site_id: "cn",
    url: "https://scp-wiki-cn.wikidot.com/task-forces-cn",
    host: "scp-wiki-cn.wikidot.com",
  },
  {
    site_id: "en",
    url: "https://scp-wiki.wikidot.com/task-forces",
    host: "scp-wiki.wikidot.com",
  },
];

function candidateLinks(html, index) {
  const $ = cheerio.load(html);
  const candidates = [];
  $("#page-content a[href]").each((_, element) => {
    const href = $(element).attr("href");
    const text = $(element).text().replace(/\s+/g, " ").trim();
    if (!/(?:mtf|task[- ]?force|特遣队|特遣隊)/i.test(`${href} ${text}`)) return;
    let url;
    try {
      url = new URL(href, index.url);
    } catch {
      return;
    }
    if (url.hostname !== index.host || url.hash) return;
    if (/^(?:\/system:|\/forum\/|\/task-forces\/?$)/.test(url.pathname)) return;
    if (/\.(?:png|jpg|jpeg|gif|webp)$/i.test(url.pathname)) return;
    url.protocol = "https:";
    candidates.push({ linked_as: text, slug: url.pathname.slice(1), url: url.origin + url.pathname });
  });
  return [...new Map(candidates.map((candidate) => [candidate.url, candidate])).values()];
}

async function inspectCandidate(siteId, candidate) {
  const response = await fetchHTML(candidate.url, { timeout: 45_000, retries: 3 });
  if (!response.success) {
    return { site_id: siteId, ...candidate, error: response.error };
  }
  const finalURL = response.finalUrl || candidate.url;
  const $ = cheerio.load(response.html);
  const title = $("#page-title").first().text().trim();
  const pageText = $("#page-content").text().replace(/\s+/g, " ").trim();
  return {
    site_id: siteId,
    ...candidate,
    final_url: finalURL,
    title,
    tags: extractTags(response.html),
    discuss_url: extractDiscussURL(response.html, finalURL),
    content_bytes: Buffer.byteLength($("#page-content").html() || ""),
    excerpt: pageText.slice(0, 280),
  };
}

const discovered = [];
for (const index of indexes) {
  const response = await fetchHTML(index.url, { timeout: 45_000, retries: 3 });
  if (!response.success) throw new Error(`${index.url}: ${response.error}`);
  const candidates = candidateLinks(response.html, index);
  if (index.site_id === "en") {
    candidates.push({
      linked_as: "MTF Theta-90 Character Profiles",
      slug: "mtf-theta-90-character-profiles",
      url: "https://scp-wiki.wikidot.com/mtf-theta-90-character-profiles",
    });
  }
  process.stdout.write(`[${index.site_id}] inspecting ${candidates.length} candidates\n`);
  for (let offset = 0; offset < candidates.length; offset += 4) {
    const batch = candidates.slice(offset, offset + 4);
    const inspected = await Promise.all(
      batch.map((candidate) => inspectCandidate(index.site_id, candidate)),
    );
    discovered.push(...inspected);
  }
}

const output = {
  inspected_at: new Date().toISOString(),
  method: "same-site MTF/task-force links from canonical overview pages, plus linked Theta-90 profile page",
  pages: discovered,
};
fs.writeFileSync(
  path.join(here, "discovery.json"),
  `${JSON.stringify(output, null, 2)}\n`,
  "utf8",
);
console.log(JSON.stringify({ pages: discovered.length, errors: discovered.filter((page) => page.error).length }));
