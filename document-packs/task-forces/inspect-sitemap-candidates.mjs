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
const sites = [
  {
    site_id: "cn",
    base_url: "https://scp-wiki-cn.wikidot.com",
    sitemap_pages: 4,
    explicit_slugs: [],
  },
  {
    site_id: "en",
    base_url: "https://scp-wiki.wikidot.com",
    sitemap_pages: 3,
    // Search engines expose this as an MTF commissioning document despite its
    // opaque page slug, so the sitemap-name filter cannot discover it alone.
    explicit_slugs: ["hello-world"],
  },
];

function urlsFromSitemap(xml) {
  return [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1]);
}

async function inspectCandidate(site, url) {
  const response = await fetchHTML(url, { timeout: 45_000, retries: 3 });
  if (!response.success) return { site_id: site.site_id, url, error: response.error };
  const finalURL = response.finalUrl || url;
  const $ = cheerio.load(response.html);
  const title = $("#page-title").first().text().trim();
  const pageText = $("#page-content").text().replace(/\s+/g, " ").trim();
  return {
    site_id: site.site_id,
    slug: new URL(finalURL).pathname.slice(1),
    url,
    final_url: finalURL,
    title,
    tags: extractTags(response.html),
    discuss_url: extractDiscussURL(response.html, finalURL),
    content_bytes: Buffer.byteLength($("#page-content").html() || ""),
    excerpt: pageText.slice(0, 320),
  };
}

const pages = [];
for (const site of sites) {
  const urls = [];
  for (let page = 1; page <= site.sitemap_pages; page += 1) {
    const sitemapURL = `${site.base_url}/sitemap_page_${page}.xml`;
    const response = await fetchHTML(sitemapURL, { timeout: 45_000, retries: 3 });
    if (!response.success) throw new Error(`${sitemapURL}: ${response.error}`);
    urls.push(...urlsFromSitemap(response.html));
  }

  const candidates = urls
    .map((url) => url.replace(/^http:/, "https:"))
    .filter((url) => /(?:mtf|task[-:]?force|mobile-task)/i.test(url));
  candidates.push(...site.explicit_slugs.map((slug) => `${site.base_url}/${slug}`));
  const unique = [...new Set(candidates)];
  process.stdout.write(`[${site.site_id}] inspecting ${unique.length} sitemap candidates\n`);
  for (let offset = 0; offset < unique.length; offset += 5) {
    const batch = unique.slice(offset, offset + 5);
    pages.push(...await Promise.all(batch.map((url) => inspectCandidate(site, url))));
  }
}

const output = {
  inspected_at: new Date().toISOString(),
  method: "official Wikidot page sitemaps filtered by MTF/task-force URL patterns, plus documented opaque-slug seeds",
  pages,
};
fs.writeFileSync(
  path.join(here, "sitemap-discovery.json"),
  `${JSON.stringify(output, null, 2)}\n`,
  "utf8",
);
console.log(JSON.stringify({ pages: pages.length, errors: pages.filter((page) => page.error).length }));
