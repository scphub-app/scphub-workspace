#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const cheerio = require("../../tools/node_modules/cheerio");
const { fetchHTML } = require("../../tools/lib/http");
const {
  extractPageContent,
  extractTags,
  extractDiscussURL,
} = require("../../tools/lib/download");
const { cleanHTML } = require("../../tools/lib/clean");
const { verifyHTML } = require("../../tools/lib/verify");

const here = path.dirname(fileURLToPath(import.meta.url));
const sourceDir = path.join(here, "source");
const docsDir = path.join(sourceDir, "docs");
const baseURL = "https://scp-wiki-cn.wikidot.com";

// Selected from the official "最高评分的原创故事" list on 2026-07-17.
// Every page must still carry 原创 / 故事 / 精品 when fetched.
const selected = [
  { slug: "2521-escaped", title: "⚠︎ ⬤⬤|⬤⬤⬤⬤⬤|⬤⬤|⬤？ ⚠︎" },
  {
    slug: "no-offset",
    title: "我的兄弟叫林南之关于《关于SCP基金会数据库新增迭代（Offset）及内容方面限制的说明》的说明从天降",
  },
  { slug: "kill-d-class", title: "死亡从善如流：SCP基金会D级人员管理制度优化史" },
  { slug: "golden-soup", title: "我的兄弟叫林南之金汁玉液从天降" },
  { slug: "wcnmm", title: "沙虫" },
  { slug: "falling-into-stars", title: "坠星者" },
  { slug: "whereishome", title: "“孩子们，我回来了”到底有什么好笑的？" },
  { slug: "bostongarden", title: "花园球馆今天没有比赛" },
];

function escapeHTML(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function pageRating($) {
  const candidates = [
    $(".rate-points").first().text(),
    $("[id^=prw]").first().text(),
  ];
  for (const value of candidates) {
    const match = value.match(/-?\d+/);
    if (match) return Number(match[0]);
  }
  return null;
}

function buildDocument({ title, slug, content, fetchedAt }) {
  const sourceURL = `${baseURL}/${slug}`;
  return `<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>${escapeHTML(title)}</title>
    <meta name="source-url" content="${sourceURL}">
    <meta name="downloaded-at" content="${fetchedAt}">
    <meta name="site-id" content="cn">
    <meta name="site-index" content="3">
</head>
<body>
<div id="page-content">
${content}
</div>
</body>
</html>`;
}

fs.mkdirSync(docsDir, { recursive: true });

const expectedDocs = new Set(selected.map(({ slug }) => `${slug}.html`));
const unexpectedDocs = fs.readdirSync(docsDir).filter((name) => !expectedDocs.has(name));
if (unexpectedDocs.length) {
  throw new Error(`unexpected existing docs: ${unexpectedDocs.join(", ")}`);
}

const fetchedAt = new Date().toISOString();
const files = [];
const audit = [];

for (const [index, expected] of selected.entries()) {
  const sourceURL = `${baseURL}/${expected.slug}`;
  process.stdout.write(`[${index + 1}/${selected.length}] ${expected.slug} ... `);
  const response = await fetchHTML(sourceURL, { timeout: 30_000, retries: 3 });
  if (!response.success) throw new Error(`${expected.slug}: ${response.error}`);

  const finalURL = response.finalUrl || sourceURL;
  const $ = cheerio.load(response.html);
  const title = $("#page-title").first().text().trim();
  if (title !== expected.title) {
    throw new Error(`${expected.slug}: title changed; expected ${expected.title}, got ${title}`);
  }

  const tags = extractTags(response.html);
  const missingTags = ["原创", "故事", "精品"].filter((tag) => !tags.includes(tag));
  if (missingTags.length) {
    throw new Error(`${expected.slug}: missing required tags ${missingTags.join(", ")}`);
  }

  const discussURL = extractDiscussURL(response.html, finalURL);
  if (!discussURL) throw new Error(`${expected.slug}: discussion URL not found`);
  const content = extractPageContent(response.html);
  if (!content.success) throw new Error(`${expected.slug}: ${content.error}`);

  const rawDocument = buildDocument({
    title,
    slug: expected.slug,
    content: content.content,
    fetchedAt,
  });
  const cleaned = cleanHTML(rawDocument, `cn-${expected.slug}.html`);
  const verification = verifyHTML(cleaned.html, `cn-${expected.slug}.html`);
  if (!verification.ok) {
    throw new Error(`${expected.slug}: ${verification.problems.join("; ")}`);
  }

  fs.writeFileSync(path.join(docsDir, `${expected.slug}.html`), cleaned.html, "utf8");
  files.push({
    name: title,
    tags,
    filename: expected.slug,
    discuss_url: discussURL,
  });
  audit.push({
    title,
    filename: expected.slug,
    source_url: finalURL,
    discuss_url: discussURL,
    rating: pageRating($),
    tags,
    bytes: Buffer.byteLength(cleaned.html),
    warnings: [...cleaned.warnings, ...verification.warnings],
  });
  console.log(`${Buffer.byteLength(cleaned.html)} bytes`);
}

const manifest = {
  id: "cn-tales-002",
  site_id: "cn",
  name: "原创故事精选 Vol.2",
  summary: "中文分部高分原创故事八篇：《沙虫》《坠星者》《花园球馆今天没有比赛》《“孩子们，我回来了”到底有什么好笑的？》等",
  version: 1,
  files,
};

fs.writeFileSync(
  path.join(sourceDir, "manifest.json"),
  `${JSON.stringify(manifest, null, 2)}\n`,
  "utf8",
);
fs.writeFileSync(
  path.join(here, "selection.json"),
  `${JSON.stringify({ fetched_at: fetchedAt, source: "official-top-rated-original-tales", files: audit }, null, 2)}\n`,
  "utf8",
);

console.log(JSON.stringify({
  manifest: path.join(sourceDir, "manifest.json"),
  documents: files.length,
  total_bytes: audit.reduce((sum, item) => sum + item.bytes, 0),
}, null, 2));
