const { chromium } = require("../../../frontend/node_modules/playwright");

const LOGIN_SHELL_MARKERS = [
  "登录",
  "注册",
  "热门榜单",
  "微博热搜",
  "Copyright © 2009-2026",
];

function normalizePostUrl(input) {
  try {
    const url = new URL(input);
    if (url.hostname.includes("m.weibo.cn")) {
      const mobileMatch = url.pathname.match(/^\/(?:status|detail)\/([A-Za-z0-9]+)/);
      if (mobileMatch) {
        return `https://m.weibo.cn/status/${mobileMatch[1]}`;
      }
    }
    const match = url.pathname.match(/^\/(\d+)\/([A-Za-z0-9]+)/);
    if (!match) {
      return null;
    }
    return `https://weibo.com/${match[1]}/${match[2]}`;
  } catch {
    return null;
  }
}

function isTimestampText(text) {
  return /^\d{2,4}-\d{1,2}-\d{1,2}/.test(text.trim());
}

function normalizeImageUrl(src) {
  if (!src || !src.includes("wx") || !src.includes("sinaimg.cn")) {
    return null;
  }
  const absolute = src.startsWith("//") ? `https:${src}` : src;
  return absolute.replace(/\/(?:thumb\d+|orj\d+|mw\d+|bmiddle|large)\//, "/large/");
}

function looksLikeLoginShell(text) {
  if (!text) {
    return true;
  }
  const compact = String(text).replace(/\s+/g, " ").trim();
  if (compact.length < 80) {
    return true;
  }
  const hits = LOGIN_SHELL_MARKERS.filter((marker) => compact.includes(marker)).length;
  return hits >= 3;
}

async function main() {
  const targetUrl = process.argv[2];
  if (!targetUrl) {
    console.error("missing url");
    process.exit(1);
  }

  const browser = await chromium.launch({
    headless: true,
    args: ["--disable-blink-features=AutomationControlled"],
  });
  const page = await browser.newPage({
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
  });
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "webdriver", { get: () => undefined });
  });
  await page.setExtraHTTPHeaders({
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
  });

  try {
    let finalUrl = targetUrl;
    let bodyText = "";

    page.setDefaultTimeout(10000);
    page.setDefaultNavigationTimeout(22000);

    for (let attempt = 0; attempt < 2; attempt += 1) {
      await page.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 22000 }).catch(() => null);
      await page.waitForTimeout(1800 + attempt * 1200);
      await expandAndLoad(page);
      bodyText = await page.locator("body").innerText();
      finalUrl = page.url();
      if (!looksLikeLoginShell(bodyText)) {
        break;
      }
      if (new URL(targetUrl).hostname.includes("m.weibo.cn")) {
        break;
      }
      await page.reload({ waitUntil: "domcontentloaded", timeout: 22000 }).catch(() => null);
      await page.waitForTimeout(2400 + attempt * 1400);
      await expandAndLoad(page);
      bodyText = await page.locator("body").innerText();
      finalUrl = page.url();
      if (!looksLikeLoginShell(bodyText)) {
        break;
      }
    }

    await expandAndLoad(page);
    const pageTitle = await page.title();

    const childLinks = await page.evaluate((currentUrl) => {
      const current = new URL(currentUrl);
      const currentPath = current.pathname;
      const seen = new Set();
      const results = [];

      for (const anchor of Array.from(document.querySelectorAll("a"))) {
        const href = anchor.href || "";
        const text = (anchor.innerText || "").trim();
        if (!href.includes("weibo.com/")) {
          continue;
        }
        try {
          const url = new URL(href);
          if (!/^\/\d+\/[A-Za-z0-9]+/.test(url.pathname)) {
            continue;
          }
          if (url.pathname === currentPath) {
            continue;
          }
          if (/^\d{2,4}-\d{1,2}-\d{1,2}/.test(text)) {
            continue;
          }
          const normalized = `https://weibo.com${url.pathname}`;
          if (seen.has(normalized)) {
            continue;
          }
          seen.add(normalized);
          results.push(normalized);
        } catch {
          // ignore invalid href
        }
      }

      return results;
    }, finalUrl);

    const extractedPost = await page.evaluate(() => {
      const clean = (value) =>
        String(value || "")
          .replace(/\u00a0/g, " ")
          .replace(/[ \t]+/g, " ")
          .replace(/\n{3,}/g, "\n\n")
          .trim();
      const scoreText = (text) => {
        const chineseCount = (text.match(/[\u4e00-\u9fff]/g) || []).length;
        const travelHits = (text.match(/攻略|路线|景点|交通|住宿|美食|预算|门票|行程|游玩|旅行|旅游/g) || []).length;
        const noiseHits = (text.match(/登录|注册|热门|热搜|评论|转发|点赞|关注/g) || []).length;
        return chineseCount + travelHits * 40 - noiseHits * 18;
      };
      const selectors = [
        ".wbpro-feed-ogText",
        ".wbpro-feed-content",
        ".detail_wbtext",
        "[class*='detail_wbtext']",
        "[class*='feed-content']",
        "[class*='ogText']",
        "[class*='Feed_body']",
        "[class*='weibo-text']",
        "article",
      ];
      let bestText = "";
      let bestNode = null;
      for (const selector of selectors) {
        for (const node of Array.from(document.querySelectorAll(selector))) {
          const text = clean(node.innerText || node.textContent || "");
          if (text.length < 20) continue;
          if (!bestText || scoreText(text) > scoreText(bestText)) {
            bestText = text;
            bestNode = node;
          }
        }
      }
      if (!bestText) {
        bestText = clean(document.body ? document.body.innerText || "" : "");
      }
      const lines = bestText.split(/\n+/).map((item) => item.trim()).filter(Boolean);
      let title = lines.find((line) => /(攻略|路线|游玩|旅行|旅游|一日|两日|三日)/.test(line) && line.length <= 70) || "";
      let author = "";
      const article = bestNode ? bestNode.closest("article") || bestNode.parentElement : null;
      const articleLines = clean(article ? article.innerText || article.textContent || "" : "")
        .split(/\n+/)
        .map((item) => item.trim())
        .filter(Boolean);
      const publicIndex = articleLines.findIndex((line) => line === "公开");
      if (publicIndex >= 0 && articleLines[publicIndex + 1]) {
        author = articleLines[publicIndex + 1];
      }
      if (!author) {
        author =
          articleLines.find(
            (line) => /^[\u4e00-\u9fffA-Za-z0-9_\-]{2,24}$/.test(line) && !/关注|返回|公开|微博/.test(line),
          ) || "";
      }
      return { title, author, text: bestText };
    });

    const imageUrls = await page.evaluate(() => {
      const seen = new Set();
      const results = [];
      const normalize = (value) => {
        if (!value) return "";
        let url = String(value).trim().replace(/\\\//g, "/");
        if (!url || url.startsWith("data:")) return "";
        if (url.startsWith("//")) url = `https:${url}`;
        try {
          url = new URL(url, location.href).href;
        } catch {
          return "";
        }
        return url;
      };
      const remember = (value) => {
        const url = normalize(value);
        if (!url || !url.includes("sinaimg.cn") || !url.includes("wx")) return;
        if (seen.has(url)) return;
        seen.add(url);
        results.push(url);
      };

      for (const image of Array.from(document.querySelectorAll("img"))) {
        const candidates = [
          image.currentSrc,
          image.src,
          image.getAttribute("data-src"),
          image.getAttribute("data-original"),
          image.getAttribute("data-large"),
          image.getAttribute("data-lazy-src"),
          image.getAttribute("data-orig"),
        ].filter(Boolean);
        const width = image.naturalWidth || image.width || 0;
        const height = image.naturalHeight || image.height || 0;
        for (const src of candidates) {
          if (!src.includes("sinaimg.cn")) {
            continue;
          }
          if (!src.includes("wx")) {
            continue;
          }
          const useful =
            width >= 240 ||
            height >= 240 ||
            src.includes("/large/") ||
            src.includes("/orj") ||
            src.includes("/mw");
          if (!useful) {
            continue;
          }
          remember(src);
        }
      }
      const html = document.documentElement ? document.documentElement.innerHTML || "" : "";
      for (const match of html.matchAll(/(?:https?:)?\/\/wx\d+\.sinaimg\.cn\/(?:large|mw\d+|orj\d+|thumb\d+|bmiddle)\/[^"')\\\s<>]+/g)) {
        remember(match[0]);
      }

      return results;
    });

    const normalizedChildren = childLinks
      .map(normalizePostUrl)
      .filter((value) => value && !isTimestampText(value));

    const normalizedImages = imageUrls.map(normalizeImageUrl).filter(Boolean);

    console.log(
      JSON.stringify(
        {
          finalUrl: normalizePostUrl(finalUrl) || finalUrl,
          pageTitle,
          bodyText: extractedPost.text || bodyText,
          postTitle: extractedPost.title || "",
          author: extractedPost.author || "",
          childLinks: Array.from(new Set(normalizedChildren)),
          imageUrls: Array.from(new Set(normalizedImages)),
        },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
}

async function expandAndLoad(page) {
  await page.evaluate(() => {
    for (const node of Array.from(document.querySelectorAll("button, a, span, div"))) {
      const text = String(node.innerText || node.textContent || "").trim();
      if (/^(展开|展开全文|全文|更多)$/.test(text) || text.includes("展开全文")) {
        try {
          node.click();
        } catch {
          // ignore click errors
        }
      }
    }
  }).catch(() => null);
  await page.waitForTimeout(300);
  for (let index = 0; index < 2; index += 1) {
    await page.mouse.wheel(0, 900).catch(() => null);
    await page.waitForTimeout(260);
  }
  await page.evaluate(() => window.scrollTo(0, 0)).catch(() => null);
  await page.waitForTimeout(180);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
