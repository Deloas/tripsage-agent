import assert from "node:assert/strict";
import { chromium, request } from "playwright";

const frontendBase = process.env.TRIPSAGE_FRONTEND_URL || "http://127.0.0.1:5173";
const backendBase = process.env.TRIPSAGE_BACKEND_URL || "http://127.0.0.1:8000/api/";
const seedUrl = `https://example.com/tripsage-guide-import-regression-${Date.now()}`;

async function main() {
  // 中文注释：先通过后端创建一条临时导入记录，确保后续 UI 回归有稳定目标。
  const api = await request.newContext({
    baseURL: backendBase,
    extraHTTPHeaders: {
      "X-Client-Name": "TripSage Web",
    },
  });

  try {
    const previewResponse = await api.post("guides/import-link/preview", {
      data: {
        url: seedUrl,
        category: "回归测试",
        force_reimport: true,
      },
      timeout: 120000,
    });
    assert.equal(previewResponse.ok(), true, "导入预览接口返回非 2xx");
    const previewBody = await previewResponse.json();
    assert.equal(previewBody.code, 0, "导入预览接口返回失败");
    const createdRecord = previewBody.data?.record;
    assert.ok(createdRecord?.id, "未创建可回归测试的导入记录");

    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1520, height: 1240 } });

    try {
      await page.goto(frontendBase, { waitUntil: "load" });
      await page.locator(".top-nav-text-action").first().click({ timeout: 15000 });
      await page.getByTestId("guide-import-modal").waitFor({ state: "visible", timeout: 15000 });
      await page.getByTestId("guide-import-history-list").waitFor({ state: "visible", timeout: 15000 });

      const openButton = page.getByTestId(`guide-import-record-open-${createdRecord.id}`);
      await openButton.waitFor({ state: "visible", timeout: 15000 });
      await openButton.click({ timeout: 15000 });

      const detailPanel = page.getByTestId("guide-import-record-detail");
      await detailPanel.waitFor({ state: "visible", timeout: 15000 });
      const detailUrlText = await page.getByTestId("guide-import-detail-url").textContent();
      assert.ok((detailUrlText || "").includes(seedUrl), "详情页没有正确展示临时导入记录");

      await page.getByTestId("guide-import-detail-delete-trigger").click({ timeout: 15000 });
      await page.getByTestId("guide-import-delete-dialog").waitFor({ state: "visible", timeout: 15000 });
      await page.getByTestId("guide-import-delete-cancel").click({ timeout: 15000 });
      await page.getByTestId("guide-import-delete-dialog").waitFor({ state: "hidden", timeout: 15000 });

      const urlAfterCancel = await page.getByTestId("guide-import-detail-url").textContent();
      assert.ok((urlAfterCancel || "").includes(seedUrl), "取消删除后记录详情状态被意外改变");

      // 中文注释：第一轮删除先撤销，验证倒计时删除提示条和撤销恢复链路。
      await page.getByTestId("guide-import-detail-delete-trigger").click({ timeout: 15000 });
      await page.getByTestId("guide-import-delete-confirm").click({ timeout: 15000 });
      await page.getByTestId("guide-import-delete-dialog").waitFor({ state: "hidden", timeout: 15000 }).catch(() => {});
      await page.getByTestId("guide-import-recent-action").waitFor({ state: "visible", timeout: 15000 });
      await page.getByTestId("guide-import-undo-delete").click({ timeout: 15000 });

      const urlAfterUndo = await page.getByTestId("guide-import-detail-url").textContent().catch(() => "");
      assert.ok((urlAfterUndo || "").includes(seedUrl), "撤销删除后记录详情未恢复");

      // 中文注释：第二轮删除等待倒计时结束，验证真正删除和自动切换。
      await page.getByTestId("guide-import-detail-delete-trigger").click({ timeout: 15000 });
      await page.getByTestId("guide-import-delete-confirm").click({ timeout: 15000 });
      await page.getByTestId("guide-import-delete-dialog").waitFor({ state: "hidden", timeout: 15000 }).catch(() => {});
      await page.getByTestId("guide-import-recent-action").waitFor({ state: "visible", timeout: 15000 });
      await page.waitForTimeout(7200);

      const detailStillVisible = await detailPanel.isVisible().catch(() => false);
      if (detailStillVisible) {
        const currentUrl = await page.getByTestId("guide-import-detail-url").textContent().catch(() => "");
        assert.ok(!(currentUrl || "").includes(seedUrl), "删除后没有自动切换到下一条记录");
      } else {
        await page.getByTestId("guide-import-history-list").waitFor({ state: "visible", timeout: 15000 });
      }

      const remainingResponse = await api.get(`guides/import-records/${createdRecord.id}`).catch(() => null);
      const remainingBody = remainingResponse ? await remainingResponse.json().catch(() => null) : null;
      assert.ok(
        !remainingResponse || remainingBody?.code !== 0,
        "删除确认后记录仍然存在，倒计时提交未生效",
      );

      console.log(
        JSON.stringify(
          {
            ok: true,
            seedUrl,
            recordId: createdRecord.id,
            message: "导入记录删除确认、撤销恢复与倒计时提交回归通过",
          },
          null,
          2,
        ),
      );
    } finally {
      await browser.close();
    }
  } finally {
    await api.dispose();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
