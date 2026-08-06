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
const packsRoot = path.dirname(here);

// These are the canonical per-site overview pages. Each page contains the
// introductions, missions, and appearance lists for all MTFs that meet that
// site's inclusion rules.
const targets = [
  {
    id: "cn-task-forces-001",
    siteId: "cn",
    siteIndex: 3,
    name: "机动特遣队资料集",
    summary: "中文站机动特遣队总览、完整名录、分部列表、装备及专题资料",
    baseURL: "https://scp-wiki-cn.wikidot.com",
    selection: "all current MTF-focused reference, list, dossier, hub, profile, application, equipment, and training pages found through the official sitemap and canonical-page link graph; artwork, contests, components, fragments, archived versions, ordinary narrative tales, and pages without a required discussion URL are excluded",
    pages: [
      { slug: "task-forces-cn", expectedTitle: "机动特遣队-CN" },
      { slug: "task-forces", expectedTitle: "机动特遣队" },
      { slug: "task-forces-complete-list", expectedTitle: "机动特遣队完整列表" },
      { slug: "mtf-list-cn-i", expectedTitle: "非官方中分mtf列表整理" },
      { slug: "site-cn-03-mtf", expectedTitle: "Site-CN-03 机动特遣队详细信息" },
      { slug: "mtf-cn-eta-3", expectedTitle: "关于Site-CN-21站点项目特殊收容措施维护小组" },
      { slug: "mtf-equipment", expectedTitle: "机动特遣队战斗人员与安保部门人员的标准装备" },
      { slug: "task-forces-de", expectedTitle: "德语区分部机动特遣队" },
      { slug: "mtf-liste", expectedTitle: "德语分部机动特遣队列表" },
      { slug: "task-forces-jp", expectedTitle: "日本国内机动部队" },
      { slug: "mtf-psi-7-home-improvement-hub", expectedTitle: "机动特遣队Psi-7（“Home Improvement”-家居装饰）中心" },
      { slug: "overview-of-mtf-psi-7-home-improvement", expectedTitle: "机动特遣队Psi-7“家居装饰”概述" },
      { slug: "mtf-theta-90-hub-page", expectedTitle: "MTF Theta-90中心页" },
      { slug: "mtf-theta-90-character-profiles", expectedTitle: "MTF Theta-90角色简介" },
      { slug: "sunday-0600-mobile-task-force-central-training-facility", expectedTitle: "机动特遣队第一课：就职说明" },
      { slug: "application-to-form-mtf-mu3-cover-letter", expectedTitle: "申请组建MTF Mu-3" },
      { slug: "application-to-form-mtf-mu3-supplementary-docs", expectedTitle: "MTF Mu-3组建申请书：文件" },
    ],
  },
  {
    id: "en-task-forces-001",
    siteId: "en",
    siteIndex: 0,
    name: "Mobile Task Force Reference",
    summary: "Main-site MTF overview, comprehensive list, hubs, applications, training, and profiles",
    baseURL: "https://scp-wiki.wikidot.com",
    selection: "all current MTF-focused reference, hub, profile, application, commissioning, and training pages found through the official sitemap, canonical-page link graph, and focused official-site search; artwork, contests, components, fragments, archived versions, and ordinary narrative tales are excluded",
    pages: [
      { slug: "task-forces", expectedTitle: "Mobile Task Forces" },
      { slug: "task-forces-complete-list", expectedTitle: "A Comprehensive List of Mobile Task Forces" },
      { slug: "mtf-psi-7-home-improvement-hub", expectedTitle: "Mobile Task Force Psi-7 \"Home Improvement\" Hub" },
      { slug: "overview-of-mtf-psi-7-home-improvement", expectedTitle: "Overview of MTF Psi-7 \"Home Improvement\"" },
      { slug: "mtf-theta-90-hub-page", expectedTitle: "MTF Theta-90 Hub Page" },
      { slug: "mtf-theta-90-character-profiles", expectedTitle: "MTF Theta-90 Character Profiles" },
      { slug: "petition-for-the-creation-of-mtf-nu-15", expectedTitle: "Petition for the Creation of MTF Nu-15" },
      { slug: "application-to-form-mtf-rho-87", expectedTitle: "Application to form MTF Rho-87" },
      { slug: "application-to-form-mtf-mu3-cover-letter", expectedTitle: "Application to Form MTF Mu-3" },
      { slug: "application-to-form-mtf-mu3-supplementary-docs", expectedTitle: "Application to Form MTF Mu-3: Documents" },
      { slug: "sunday-0600-mobile-task-force-central-training-facility", expectedTitle: "Mobile Task Force Basic School: Induction Remarks" },
      { slug: "hello-world", expectedTitle: "Hello World" },
    ],
  },
];

function escapeHTML(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function buildDocument({ target, page, title, content, fetchedAt }) {
  const sourceURL = `${target.baseURL}/${page.slug}`;
  return `<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>${escapeHTML(title)}</title>
    <meta name="source-url" content="${sourceURL}">
    <meta name="downloaded-at" content="${fetchedAt}">
    <meta name="site-id" content="${target.siteId}">
    <meta name="site-index" content="${target.siteIndex}">
</head>
<body>
<div id="page-content">
${content}
</div>
</body>
</html>`;
}

function pageStats(html) {
  const $ = cheerio.load(html);
  const headings = $("#page-content h1, #page-content h2")
    .map((_, element) => $(element).text().trim())
    .get();
  return {
    heading_count: headings.length,
    mtf_heading_count: headings.filter((heading) => /(?:MTF|机动特遣队)/i.test(heading)).length,
  };
}

const fetchedAt = new Date().toISOString();
const results = [];

for (const target of targets) {
  const packDir = path.join(packsRoot, target.id);
  const sourceDir = path.join(packDir, "source");
  const docsDir = path.join(sourceDir, "docs");
  fs.mkdirSync(docsDir, { recursive: true });

  const expectedDocs = new Set(target.pages.map((page) => `${page.slug}.html`));
  const unexpectedDocs = fs.readdirSync(docsDir).filter((name) => !expectedDocs.has(name));
  if (unexpectedDocs.length) {
    throw new Error(`${target.id}: unexpected existing docs: ${unexpectedDocs.join(", ")}`);
  }

  const files = [];
  const audits = [];
  for (const [index, page] of target.pages.entries()) {
    const sourceURL = `${target.baseURL}/${page.slug}`;
    process.stdout.write(`[${target.siteId} ${index + 1}/${target.pages.length}] ${sourceURL} ... `);
    const response = await fetchHTML(sourceURL, { timeout: 45_000, retries: 3 });
    if (!response.success) throw new Error(`${target.id}/${page.slug}: ${response.error}`);

    const finalURL = response.finalUrl || sourceURL;
    const $ = cheerio.load(response.html);
    const title = $("#page-title").first().text().trim();
    if (title !== page.expectedTitle) {
      throw new Error(`${target.id}/${page.slug}: title changed; expected ${page.expectedTitle}, got ${title}`);
    }

    const tags = extractTags(response.html);
    if (!tags.length) throw new Error(`${target.id}/${page.slug}: no public page tags found`);
    const discussURL = extractDiscussURL(response.html, finalURL);
    if (!discussURL) throw new Error(`${target.id}/${page.slug}: discussion URL not found`);
    const content = extractPageContent(response.html);
    if (!content.success) throw new Error(`${target.id}/${page.slug}: ${content.error}`);

    const rawDocument = buildDocument({
      target,
      page,
      title,
      content: content.content,
      fetchedAt,
    });
    const outputFilename = `${target.siteId}-${page.slug}.html`;
    const cleaned = cleanHTML(rawDocument, outputFilename);
    const verification = verifyHTML(cleaned.html, outputFilename);
    if (!verification.ok) {
      throw new Error(`${target.id}/${page.slug}: ${verification.problems.join("; ")}`);
    }

    const bytes = Buffer.byteLength(cleaned.html);
    fs.writeFileSync(path.join(docsDir, `${page.slug}.html`), cleaned.html, "utf8");
    files.push({
      name: title,
      tags,
      filename: page.slug,
      discuss_url: discussURL,
    });
    audits.push({
      source_url: finalURL,
      title,
      tags,
      discuss_url: discussURL,
      filename: page.slug,
      bytes,
      ...pageStats(response.html),
      warnings: [...cleaned.warnings, ...verification.warnings],
    });
    console.log(`${bytes} bytes`);
  }

  const manifest = {
    id: target.id,
    site_id: target.siteId,
    name: target.name,
    summary: target.summary,
    version: 1,
    files,
  };

  fs.writeFileSync(
    path.join(sourceDir, "manifest.json"),
    `${JSON.stringify(manifest, null, 2)}\n`,
    "utf8",
  );

  const audit = {
    fetched_at: fetchedAt,
    selection: target.selection,
    files: audits,
  };
  fs.writeFileSync(
    path.join(packDir, "source.json"),
    `${JSON.stringify(audit, null, 2)}\n`,
    "utf8",
  );
  results.push({
    id: target.id,
    site_id: target.siteId,
    documents: files.length,
    bytes: audits.reduce((sum, item) => sum + item.bytes, 0),
  });
}

console.log(JSON.stringify({ fetched_at: fetchedAt, packs: results }, null, 2));
