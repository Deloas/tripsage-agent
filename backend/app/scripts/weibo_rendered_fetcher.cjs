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
    const match = url.pathname.match(/^\/7896659368\/([A-Za-z0-9]+)/);
    if (!match) {
      return null;
    }
    return `https://weibo.com/7896659368/${match[1]}`;
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
  return src.replace(/\/(?:orj360|thumb150|mw690|orj480|large)\//, "/large/");
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

    for (let attempt = 0; attempt < 3; attempt += 1) {
      await page.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 120000 });
      await page.waitForTimeout(4000 + attempt * 2500);
      bodyText = await page.locator("body").innerText();
      finalUrl = page.url();
      if (!looksLikeLoginShell(bodyText)) {
        break;
      }
      await page.reload({ waitUntil: "domcontentloaded", timeout: 120000 });
      await page.waitForTimeout(5000 + attempt * 3000);
      bodyText = await page.locator("body").innerText();
      finalUrl = page.url();
      if (!looksLikeLoginShell(bodyText)) {
        break;
      }
    }

    const pageTitle = await page.title();

    const childLinks = await page.evaluate((currentUrl) => {
      const current = new URL(currentUrl);
      const currentPath = current.pathname;
      const seen = new Set();
      const results = [];

      for (const anchor of Array.from(document.querySelectorAll("a"))) {
        const href = anchor.href || "";
        const text = (anchor.innerText || "").trim();
        if (!href.includes("weibo.com/7896659368/")) {
          continue;
        }
        try {
          const url = new URL(href);
          if (!/^\/7896659368\/[A-Za-z0-9]+/.test(url.pathname)) {
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

    const imageUrls = await page.evaluate(() => {
      const seen = new Set();
      const results = [];

      for (const image of Array.from(document.querySelectorAll("img"))) {
        const src = image.currentSrc || image.src || "";
        const width = image.naturalWidth || 0;
        const height = image.naturalHeight || 0;
        if (!src.includes("sinaimg.cn")) {
          continue;
        }
        if (width < 500 && height < 500) {
          continue;
        }
        if (!src.includes("wx")) {
          continue;
        }
        if (seen.has(src)) {
          continue;
        }
        seen.add(src);
        results.push(src);
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
          bodyText,
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

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
