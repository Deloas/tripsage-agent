import { useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  ChevronLeft,
  CheckCircle2,
  DatabaseZap,
  Eye,
  ImageIcon,
  Link2,
  Loader2,
  MapPinned,
  RefreshCw,
  ScanSearch,
  Sparkles,
  Trash2,
  WandSparkles,
  X,
} from "lucide-react";

import { fetchGuideDetail } from "../lib/api";
import type {
  GuideDetail,
  GuideImportRecordItem,
  GuideImportTaskItem,
  GuideLinkImportResult,
  GuideLinkPreviewResult,
  GuideStructuredDraft,
} from "../lib/types";

interface AddGuideModalProps {
  open: boolean;
  loading: boolean;
  crawlLoading: boolean;
  result: string | null;
  preselectedRecordId?: number | null;
  onClose: () => void;
  onSubmit: (payload: { title: string; content: string; source_url?: string }) => Promise<void>;
  onImportLink: (payload: { url: string; category?: string; force_reimport?: boolean }) => Promise<GuideLinkImportResult | null>;
  onPreviewLink: (payload: { url: string; category?: string }) => Promise<GuideLinkPreviewResult | null>;
  onConfirmImport: (payload: {
    url: string;
    title: string;
    content: string;
    category?: string;
    source_type?: string;
    resolved_url?: string;
    author?: string | null;
    structured?: Record<string, unknown> | null;
  }) => Promise<GuideLinkImportResult | null>;
  onCrawlWeibo: () => Promise<void>;
  importedGuide?: GuideDetail | null;
  importResult?: GuideLinkImportResult | null;
  previewResult?: GuideLinkPreviewResult | null;
  importRecords: GuideImportRecordItem[];
  importTasks?: GuideImportTaskItem[];
  activeImportTask?: GuideImportTaskItem | null;
  onDeleteImportRecord: (recordId: number) => Promise<void>;
  onUseImportedGuide: (guide: GuideDetail) => void;
  onOptimizeImportedGuide: (guide: GuideDetail) => void;
  onSetPrimaryGuide: (guide: GuideDetail) => void;
}

type ImportMode = "link" | "manual";
type HistoryView = "list" | "detail";
type ImagePreviewState = { url: string; label: string } | null;

interface PreviewDraft {
  title: string;
  content: string;
  category: string;
  source_type: string;
  resolved_url: string;
  author: string;
  structured: GuideStructuredDraft;
}

const EMPTY_STRUCTURED: GuideStructuredDraft = {
  city: "",
  days: null,
  summary: "",
  travel_style_tags: [],
  scenic_spots: [],
  route_nodes: [],
  budget_tips: [],
  risk_notes: [],
};

export function AddGuideModal({
  open,
  loading,
  crawlLoading,
  result,
  preselectedRecordId = null,
  onClose,
  onSubmit,
  onImportLink,
  onPreviewLink,
  onConfirmImport,
  onCrawlWeibo,
  importedGuide = null,
  importResult = null,
  previewResult = null,
  importRecords,
  importTasks = [],
  activeImportTask = null,
  onDeleteImportRecord,
  onUseImportedGuide,
  onOptimizeImportedGuide,
  onSetPrimaryGuide,
}: AddGuideModalProps) {
  const [mode, setMode] = useState<ImportMode>("link");
  const [manualTitle, setManualTitle] = useState("");
  const [manualContent, setManualContent] = useState("");
  const [manualSourceUrl, setManualSourceUrl] = useState("");
  const [linkUrl, setLinkUrl] = useState("");
  const [linkCategory, setLinkCategory] = useState("微博攻略");
  const [previewDraft, setPreviewDraft] = useState<PreviewDraft | null>(null);
  const [selectedRecordId, setSelectedRecordId] = useState<number | null>(preselectedRecordId);
  const [selectedRecordGuide, setSelectedRecordGuide] = useState<GuideDetail | null>(null);
  const [selectedRecordGuideLoading, setSelectedRecordGuideLoading] = useState(false);
  const [previewImage, setPreviewImage] = useState<ImagePreviewState>(null);
  const [historyView, setHistoryView] = useState<HistoryView>("list");
  const [selectedRecordSnapshot, setSelectedRecordSnapshot] = useState<GuideImportRecordItem | null>(null);

  const selectedRecord = useMemo(
    () => {
      const current = importRecords.find((item) => String(item.id) === String(selectedRecordId)) || null;
      if (current) return current;
      if (selectedRecordSnapshot && String(selectedRecordSnapshot.id) === String(selectedRecordId)) {
        return selectedRecordSnapshot;
      }
      return null;
    },
    [importRecords, selectedRecordId, selectedRecordSnapshot],
  );

  const currentQuality =
    importResult?.quality
    || previewResult?.quality
    || selectedRecord?.quality
    || null;

  const currentDiagnostics =
    importResult?.diagnostics
    || previewResult?.diagnostics
    || selectedRecord?.diagnostics
    || null;

  const importedOrDuplicatedGuide =
    importedGuide
    || importResult?.guide
    || (selectedRecordGuide && selectedRecordGuide.id === selectedRecord?.guide_id ? selectedRecordGuide : null);

  const shouldShowHistoryList = historyView === "list";

  useEffect(() => {
    if (!open) return undefined;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (previewImage) {
          setPreviewImage(null);
          return;
        }
        onClose();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose, open, previewImage]);

  useEffect(() => {
    if (!open) return;
    if (preselectedRecordId) {
      setSelectedRecordId(preselectedRecordId);
      setSelectedRecordSnapshot(importRecords.find((item) => String(item.id) === String(preselectedRecordId)) || null);
      setHistoryView("detail");
      return;
    }
    if (importResult?.record?.id) {
      setSelectedRecordId(importResult.record.id);
      setSelectedRecordSnapshot(importResult.record);
      return;
    }
    if (previewResult?.record?.id) {
      setSelectedRecordId(previewResult.record.id);
      setSelectedRecordSnapshot(previewResult.record);
      return;
    }
    if (!selectedRecordId && importRecords.length) {
      setSelectedRecordId(importRecords[0].id);
      setSelectedRecordSnapshot(importRecords[0]);
    }
  }, [importRecords, importResult?.record?.id, open, preselectedRecordId, previewResult?.record?.id, selectedRecordId]);

  useEffect(() => {
    if (!previewResult) {
      return;
    }

    // 预览结果进入编辑态时，单独维护一份草稿，避免用户修订内容时被后续请求覆盖。
    setPreviewDraft({
      title: previewResult.title || "",
      content: previewResult.content || "",
      category: previewResult.category || "",
      source_type: previewResult.source_type || "link_import",
      resolved_url: previewResult.resolved_url || linkUrl,
      author: previewResult.author || "",
      structured: cloneStructured(previewResult.structured),
    });
  }, [linkUrl, previewResult]);

  useEffect(() => {
    if (!selectedRecord?.guide_id) {
      setSelectedRecordGuide(null);
      return;
    }
    const guideId = selectedRecord.guide_id;
    if (importedGuide && importedGuide.id === selectedRecord.guide_id) {
      setSelectedRecordGuide(importedGuide);
      return;
    }

    let cancelled = false;

    async function loadGuideDetail() {
      setSelectedRecordGuideLoading(true);
      try {
        const detail = await fetchGuideDetail(guideId);
        if (!cancelled) {
          setSelectedRecordGuide(detail);
        }
      } catch {
        if (!cancelled) {
          setSelectedRecordGuide(null);
        }
      } finally {
        if (!cancelled) {
          setSelectedRecordGuideLoading(false);
        }
      }
    }

    void loadGuideDetail();
    return () => {
      cancelled = true;
    };
  }, [importedGuide, selectedRecord?.guide_id]);

  if (!open) return null;

  const canSubmitManual = manualTitle.trim().length > 0 && manualContent.trim().length > 0;
  const canPreviewLink = linkUrl.trim().length > 0 && !loading;
  const canConfirmImport = Boolean(previewDraft?.title.trim() && previewDraft?.content.trim() && !loading);

  async function handleManualSubmit() {
    if (!canSubmitManual) return;
    await onSubmit({
      title: manualTitle.trim(),
      content: manualContent.trim(),
      source_url: manualSourceUrl.trim() || undefined,
    });
    setManualTitle("");
    setManualContent("");
    setManualSourceUrl("");
    setMode("manual");
  }

  async function handlePreview() {
    if (!linkUrl.trim()) return;
    setMode("link");
    const next = await onPreviewLink({
      url: linkUrl.trim(),
      category: linkCategory.trim() || undefined,
    });
    if (next?.record?.id) {
      setSelectedRecordId(next.record.id);
      setSelectedRecordSnapshot(next.record);
    }
  }

  async function handleDirectImport(forceReimport = false) {
    if (!linkUrl.trim()) return;
    setMode("link");
    const next = await onImportLink({
      url: linkUrl.trim(),
      category: linkCategory.trim() || undefined,
      force_reimport: forceReimport,
    });
    if (next?.record?.id) {
      setSelectedRecordId(next.record.id);
      setSelectedRecordSnapshot(next.record);
    }
  }

  async function handleConfirmImport() {
    if (!previewDraft || !canConfirmImport) return;
    const next = await onConfirmImport({
      url: linkUrl.trim() || previewDraft.resolved_url || previewResult?.resolved_url || "",
      title: previewDraft.title.trim(),
      content: previewDraft.content.trim(),
      category: previewDraft.category.trim() || undefined,
      source_type: previewDraft.source_type || previewResult?.source_type || "link_import",
      resolved_url: previewDraft.resolved_url.trim() || undefined,
      author: previewDraft.author.trim() || undefined,
      structured: previewDraft.structured as Record<string, unknown>,
    });
    if (next?.record?.id) {
      setSelectedRecordId(next.record.id);
      setSelectedRecordSnapshot(next.record);
    }
  }

  function openRecordDetail(record: GuideImportRecordItem) {
    setSelectedRecordId(record.id);
    setSelectedRecordSnapshot(record);
    setHistoryView("detail");
  }

  function loadRecordToEditor(record: GuideImportRecordItem) {
    setMode("link");
    setLinkUrl(record.resolved_url || record.url);
    setLinkCategory(record.category || "微博攻略");
    setPreviewDraft({
      title: record.title || "未命名导入攻略",
      content: record.content || "",
      category: record.category || "",
      source_type: record.source_type || "link_import",
      resolved_url: record.resolved_url || record.url,
      author: record.author || "",
      structured: cloneStructured(record.structured),
    });
  }

  async function handleDeleteRecord(recordId: number) {
    await onDeleteImportRecord(recordId);
    if (selectedRecordId === recordId) {
      setSelectedRecordId(null);
      setSelectedRecordSnapshot(null);
      setHistoryView("list");
    }
  }

  return (
    <>
      <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
        <section className="guide-modal guide-modal-upgraded" aria-label="攻略导入工作台">
          <header className="guide-modal-header">
            <div className="guide-modal-topline">
              <div>
                <div className="section-kicker">
                  <DatabaseZap size={15} />
                  攻略导入工作台
                </div>
                <h2>链接抓取、正文校对、入库复用在一处完成</h2>
                <p className="guide-side-note">
                  支持正文链接、图文混合来源与手动补录，入库后可直接作为当前规划的主参考攻略。
                </p>
              </div>
              <div className="guide-modal-header-actions">
                <button type="button" className="secondary-action" onClick={() => void onCrawlWeibo()} disabled={crawlLoading}>
                  <RefreshCw size={15} className={crawlLoading ? "spin" : ""} />
                  {crawlLoading ? "采集中" : "继续补采微博"}
                </button>
                <button type="button" className="icon-button" aria-label="关闭攻略导入" onClick={onClose}>
                  <X size={18} />
                </button>
              </div>
            </div>
          </header>

          <div className="guide-import-shell">
            <main className="guide-import-primary">
              <div className="guide-import-visual-panel">
                <div className="guide-import-visual-head">
                  <div>
                    <span>导入状态</span>
                    <strong>{buildHeadline(importResult, previewResult, selectedRecord)}</strong>
                  </div>
                  <div className="guide-import-visual-badges">
                    <span>{buildStatusText(importResult?.status || previewResult?.status || selectedRecord?.status || "ready")}</span>
                    {currentQuality?.grade ? <span>质量 {currentQuality.grade}</span> : null}
                    {currentDiagnostics?.fetch_method ? <span>{currentDiagnostics.fetch_method}</span> : null}
                  </div>
                </div>

                <div className="guide-import-visual-stats">
                  <div>
                    <span>当前入口</span>
                    <strong>{mode === "link" ? "智能链接导入" : "手动补录入库"}</strong>
                  </div>
                  <div>
                    <span>记录数量</span>
                    <strong>{String(importRecords.length)}</strong>
                  </div>
                  <div>
                    <span>图文增强</span>
                    <strong>{resolveEnhancementLabel(currentDiagnostics)}</strong>
                  </div>
                </div>
              </div>

              {result ? <div className="guide-import-status-banner">{result}</div> : null}

              {(activeImportTask || importTasks.length > 0) ? (
                <section className="guide-import-task-panel">
                  <div className="guide-import-task-head">
                    <div>
                      <span className="section-kicker">
                        <Loader2 size={14} className={activeImportTask?.status === "running" ? "spin" : ""} />
                        后台导入任务
                      </span>
                      <strong>{activeImportTask ? buildTaskTitle(activeImportTask) : "最近任务"}</strong>
                    </div>
                    {activeImportTask ? <span>{buildTaskStatus(activeImportTask.status)}</span> : null}
                  </div>
                  {activeImportTask ? (
                    <div className="guide-import-task-active">
                      <div className="guide-import-task-meter" aria-label="攻略导入任务进度">
                        <span style={{ width: `${Math.max(5, Math.min(100, activeImportTask.progress || 0))}%` }} />
                      </div>
                      <div className="guide-import-task-meta">
                        <span>{String(activeImportTask.progress || 0)}%</span>
                        <span>{buildTaskStage(activeImportTask.stage)}</span>
                        <span>{activeImportTask.message || "正在处理"}</span>
                      </div>
                    </div>
                  ) : null}
                  {importTasks.length ? (
                    <div className="guide-import-task-list">
                      {importTasks.slice(0, 4).map((task) => (
                        <div key={task.id} className={`guide-import-task-row status-${task.status}`}>
                          <div>
                            <strong>{task.title || task.url}</strong>
                            <p>{task.message || task.url}</p>
                          </div>
                          <span>{String(task.progress || 0)}%</span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </section>
              ) : null}

              <div className="mode-switch guide-mode-switch" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
                <button
                  type="button"
                  className={mode === "link" ? "active" : ""}
                  onClick={() => setMode("link")}
                >
                  <Link2 size={15} />
                  智能链接导入
                </button>
                <button
                  type="button"
                  className={mode === "manual" ? "active" : ""}
                  onClick={() => setMode("manual")}
                >
                  <Sparkles size={15} />
                  手动补录
                </button>
              </div>

              {mode === "link" ? (
                <section className="guide-preview-editor">
                  <div className="guide-preview-editor-head">
                    <div>
                      <div className="section-kicker">
                        <ScanSearch size={15} />
                        链接解析
                      </div>
                      <h3>先抓正文，再决定直接入库还是人工修订</h3>
                    </div>
                    {currentQuality?.grade ? (
                      <span className={`guide-health-badge grade-${currentQuality.grade}`}>
                        {currentQuality.grade} / {String(currentQuality.score)}
                      </span>
                    ) : null}
                  </div>

                  <div className="guide-link-input-grid">
                    <label className="guide-form">
                      <span>攻略链接</span>
                      <input
                        value={linkUrl}
                        onChange={(event) => setLinkUrl(event.target.value)}
                        placeholder="粘贴微博、图文页或公开攻略链接"
                      />
                    </label>
                    <label className="guide-form">
                      <span>攻略分类</span>
                      <input
                        value={linkCategory}
                        onChange={(event) => setLinkCategory(event.target.value)}
                        placeholder="例如：周末短途 / 城市漫游 / 亲子"
                      />
                    </label>
                  </div>

                  <div className="guide-link-action-row">
                    <button type="button" className="secondary-action" onClick={() => void handlePreview()} disabled={!canPreviewLink}>
                      {loading ? <Loader2 size={15} className="spin" /> : <Eye size={15} />}
                      抓取并编辑
                    </button>
                    <button type="button" className="primary-action" onClick={() => void handleDirectImport(false)} disabled={!canPreviewLink}>
                      {loading ? <Loader2 size={15} className="spin" /> : <WandSparkles size={15} />}
                      直接入库
                    </button>
                  </div>

                  {previewDraft ? (
                    <>
                      <div className="guide-editor-grid">
                        <label className="guide-form">
                          <span>标题</span>
                          <input
                            value={previewDraft.title}
                            onChange={(event) => setPreviewDraft((current) => current ? { ...current, title: event.target.value } : current)}
                            placeholder="编辑导入后的正式标题"
                          />
                        </label>
                        <label className="guide-form">
                          <span>作者 / 来源</span>
                          <input
                            value={previewDraft.author}
                            onChange={(event) => setPreviewDraft((current) => current ? { ...current, author: event.target.value } : current)}
                            placeholder="可留空"
                          />
                        </label>
                        <label className="guide-form">
                          <span>分类</span>
                          <input
                            value={previewDraft.category}
                            onChange={(event) => setPreviewDraft((current) => current ? { ...current, category: event.target.value } : current)}
                            placeholder="导入分类"
                          />
                        </label>
                        <label className="guide-form">
                          <span>解析后的来源链接</span>
                          <input
                            value={previewDraft.resolved_url}
                            onChange={(event) => setPreviewDraft((current) => current ? { ...current, resolved_url: event.target.value } : current)}
                            placeholder="解析跳转后的真实地址"
                          />
                        </label>
                      </div>

                      <label className="guide-form guide-editor-content">
                        <span>正文</span>
                        <textarea
                          value={previewDraft.content}
                          onChange={(event) => setPreviewDraft((current) => current ? { ...current, content: event.target.value } : current)}
                          placeholder="这里可以对抓到的正文做精修，再确认入库"
                        />
                      </label>

                      <div className="structured-review-panel">
                        <div className="structured-review-head">
                          <div>
                            <span>结构化草稿</span>
                            <strong>把核心行程信息整理成可被规划器复用的字段</strong>
                          </div>
                        </div>

                        <div className="guide-editor-grid">
                          <label className="guide-form">
                            <span>目的地城市</span>
                            <input
                              value={previewDraft.structured.city || ""}
                              onChange={(event) => updateStructuredDraft(setPreviewDraft, "city", event.target.value)}
                              placeholder="例如：杭州"
                            />
                          </label>
                          <label className="guide-form">
                            <span>建议天数</span>
                            <input
                              value={previewDraft.structured.days != null ? String(previewDraft.structured.days) : ""}
                              onChange={(event) => updateStructuredDraft(setPreviewDraft, "days", normalizeOptionalNumber(event.target.value))}
                              placeholder="例如：3"
                            />
                          </label>
                        </div>

                        <label className="guide-form">
                          <span>摘要</span>
                          <textarea
                            value={previewDraft.structured.summary || ""}
                            onChange={(event) => updateStructuredDraft(setPreviewDraft, "summary", event.target.value)}
                            placeholder="简要概括这篇攻略的玩法与价值"
                          />
                        </label>

                        <div className="guide-editor-grid">
                          <label className="guide-form">
                            <span>玩法标签</span>
                            <input
                              value={formatList(previewDraft.structured.travel_style_tags)}
                              onChange={(event) => updateStructuredDraft(setPreviewDraft, "travel_style_tags", parseList(event.target.value))}
                              placeholder="轻松, citywalk, 美食"
                            />
                          </label>
                          <label className="guide-form">
                            <span>重点景点</span>
                            <input
                              value={formatList(previewDraft.structured.scenic_spots)}
                              onChange={(event) => updateStructuredDraft(setPreviewDraft, "scenic_spots", parseList(event.target.value))}
                              placeholder="西湖, 灵隐寺, 河坊街"
                            />
                          </label>
                          <label className="guide-form">
                            <span>路线节点</span>
                            <input
                              value={formatList(previewDraft.structured.route_nodes)}
                              onChange={(event) => updateStructuredDraft(setPreviewDraft, "route_nodes", parseList(event.target.value))}
                              placeholder="高铁站, 酒店, 景区"
                            />
                          </label>
                          <label className="guide-form">
                            <span>预算提示</span>
                            <input
                              value={formatList(previewDraft.structured.budget_tips)}
                              onChange={(event) => updateStructuredDraft(setPreviewDraft, "budget_tips", parseList(event.target.value))}
                              placeholder="周中入住更划算, 景区联票"
                            />
                          </label>
                        </div>
                      </div>

                      <div className="guide-link-action-row">
                        <button type="button" className="secondary-action" onClick={() => void handleDirectImport(true)} disabled={loading}>
                          {loading ? <Loader2 size={15} className="spin" /> : <RefreshCw size={15} />}
                          强制重新抓取
                        </button>
                        <button type="button" className="primary-action" onClick={() => void handleConfirmImport()} disabled={!canConfirmImport}>
                          {loading ? <Loader2 size={15} className="spin" /> : <CheckCircle2 size={15} />}
                          确认入库
                        </button>
                      </div>
                    </>
                  ) : null}

                  {currentDiagnostics ? (
                    <GuideImportDiagnosticsPanel
                      diagnostics={currentDiagnostics}
                      quality={currentQuality}
                      onPreviewImage={setPreviewImage}
                    />
                  ) : null}

                  {importedOrDuplicatedGuide ? (
                    <ImportedGuidePreview
                      guide={importedOrDuplicatedGuide}
                      quality={currentQuality}
                      onUseGuide={() => onUseImportedGuide(importedOrDuplicatedGuide)}
                      onOptimizeGuide={() => onOptimizeImportedGuide(importedOrDuplicatedGuide)}
                      onSetPrimaryGuide={() => onSetPrimaryGuide(importedOrDuplicatedGuide)}
                    />
                  ) : null}
                </section>
              ) : (
                <section className="guide-preview-editor">
                  <div className="guide-preview-editor-head">
                    <div>
                      <div className="section-kicker">
                        <MapPinned size={15} />
                        手动补录
                      </div>
                      <h3>当平台正文受限时，直接补录正式攻略文本</h3>
                    </div>
                  </div>

                  <div className="guide-form field-grid">
                    <label>
                      <span>攻略标题</span>
                      <input
                        value={manualTitle}
                        onChange={(event) => setManualTitle(event.target.value)}
                        placeholder="例如：苏州两天一夜慢游"
                      />
                    </label>
                    <label>
                      <span>来源链接</span>
                      <input
                        value={manualSourceUrl}
                        onChange={(event) => setManualSourceUrl(event.target.value)}
                        placeholder="可选，用于保留出处"
                      />
                    </label>
                    <label>
                      <span>正文内容</span>
                      <textarea
                        value={manualContent}
                        onChange={(event) => setManualContent(event.target.value)}
                        placeholder="粘贴完整正文，系统会自动切片与入库"
                        rows={14}
                      />
                    </label>
                  </div>

                  <div className="guide-link-action-row">
                    <button type="button" className="primary-action" onClick={() => void handleManualSubmit()} disabled={!canSubmitManual || loading}>
                      {loading ? <Loader2 size={15} className="spin" /> : <DatabaseZap size={15} />}
                      正式入库
                    </button>
                  </div>
                </section>
              )}
            </main>

            <aside className="guide-import-aside">
              {shouldShowHistoryList ? (
              <section className="guide-import-history-panel">
                <div className="guide-import-history-head">
                  <div>
                    <span className="section-kicker">
                      <RefreshCw size={14} />
                      导入记录
                    </span>
                    <strong>最近导入与抓取结果</strong>
                  </div>
                  <span className="history-status-pill">{String(importRecords.length)} 条</span>
                </div>

                {importRecords.length ? (
                  <div className="guide-import-history-list">
                    {importRecords.map((record) => (
                      <article
                        key={record.id}
                        className={`guide-import-history-item ${record.id === selectedRecordId ? "active" : ""}`}
                      >
                        <button type="button" className="guide-import-history-main" onClick={() => openRecordDetail(record)}>
                          <div>
                            <strong>{record.title || record.url}</strong>
                            <p>{record.url}</p>
                          </div>
                          <span className={`history-status-pill status-${record.status}`}>
                            {buildStatusText(record.status)}
                          </span>
                        </button>
                        <div className="guide-import-history-actions">
                          <button type="button" onClick={() => openRecordDetail(record)}>
                            <Eye size={12} />
                            查看
                          </button>
                          <button type="button" className="danger" onClick={() => void handleDeleteRecord(record.id)}>
                            <Trash2 size={12} />
                            删除
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="guide-import-empty">
                    还没有导入记录。先从左侧输入链接，系统会把抓取、OCR、视觉补全文链路沉淀到这里。
                  </div>
                )}
              </section>
              ) : null}

              {!shouldShowHistoryList ? (
                <section className="guide-import-history-detail">
                  <div className="guide-import-detail-toolbar">
                    <button type="button" className="secondary-action compact" onClick={() => setHistoryView("list")}>
                      <ChevronLeft size={14} />
                      返回记录
                    </button>
                    {selectedRecord ? (
                      <button type="button" className="secondary-action compact danger" onClick={() => void handleDeleteRecord(selectedRecord.id)}>
                        <Trash2 size={14} />
                        删除记录
                      </button>
                    ) : null}
                  </div>
                  {selectedRecord ? (
                    <>
                  <div className="guide-import-history-detail-head">
                    <div className="guide-record-header-copy">
                      <strong>{selectedRecord.title || selectedRecord.url}</strong>
                      <p className="guide-side-note">{selectedRecord.url}</p>
                    </div>
                    <span className={`history-status-pill status-${selectedRecord.status}`}>
                      {buildStatusText(selectedRecord.status)}
                    </span>
                  </div>

                  <div className="guide-import-history-detail-grid">
                    <div>
                      <span>导入模式</span>
                      <strong>{selectedRecord.mode || "-"}</strong>
                    </div>
                    <div>
                      <span>来源类型</span>
                      <strong>{selectedRecord.source_type || "-"}</strong>
                    </div>
                    <div>
                      <span>质量评级</span>
                      <strong>{selectedRecord.quality?.grade ? `${selectedRecord.quality.grade} / ${selectedRecord.quality.score}` : "-"}</strong>
                    </div>
                    <div>
                      <span>导入时间</span>
                      <strong>{formatDateTime(selectedRecord.created_at)}</strong>
                    </div>
                  </div>

                  {selectedRecord.message || selectedRecord.reason ? (
                    <div className="guide-import-history-detail-note">
                      <span>处理说明</span>
                      <strong>{selectedRecord.message || selectedRecord.reason}</strong>
                    </div>
                  ) : null}

                  {selectedRecord.content ? (
                    <section className="guide-import-record-preview">
                      <div className="guide-import-record-preview-head">
                        <div>
                          <span>可编辑预览正文</span>
                          <strong>{selectedRecord.content.length} 字，已可恢复到左侧编辑区</strong>
                        </div>
                        <button type="button" className="primary-action compact" onClick={() => loadRecordToEditor(selectedRecord)}>
                          <CheckCircle2 size={14} />
                          载入编辑区
                        </button>
                      </div>
                      <div className="guide-import-record-preview-body">
                        {selectedRecord.content}
                      </div>
                    </section>
                  ) : (
                    <div className="guide-import-history-detail-note">
                      <span>预览正文</span>
                      <strong>该旧记录没有保存完整正文，可重新抓取一次，后续记录会自动保留全文。</strong>
                    </div>
                  )}

                  {(selectedRecordGuideLoading || importedOrDuplicatedGuide) ? (
                    <div className="guide-import-history-detail-actions">
                      <button
                        type="button"
                        className="secondary-action"
                        onClick={() => importedOrDuplicatedGuide && onUseImportedGuide(importedOrDuplicatedGuide)}
                        disabled={!importedOrDuplicatedGuide || selectedRecordGuideLoading}
                      >
                        应用到当前规划
                      </button>
                      <button
                        type="button"
                        className="secondary-action"
                        onClick={() => importedOrDuplicatedGuide && onOptimizeImportedGuide(importedOrDuplicatedGuide)}
                        disabled={!importedOrDuplicatedGuide || selectedRecordGuideLoading}
                      >
                        基于该攻略继续优化
                      </button>
                      <button
                        type="button"
                        className="primary-action"
                        onClick={() => importedOrDuplicatedGuide && onSetPrimaryGuide(importedOrDuplicatedGuide)}
                        disabled={!importedOrDuplicatedGuide || selectedRecordGuideLoading}
                      >
                        设为主参考攻略
                      </button>
                    </div>
                  ) : null}

                  {selectedRecord.guide_id ? (
                    <div className="guide-import-history-detail-note">
                      <span>关联攻略</span>
                      <strong>
                        {selectedRecordGuideLoading
                          ? "正在加载关联攻略详情..."
                          : selectedRecordGuide
                            ? `${selectedRecordGuide.title} / ${selectedRecordGuide.city || "未知城市"}`
                            : `已关联攻略 #${selectedRecord.guide_id}`}
                      </strong>
                    </div>
                  ) : null}

                  {selectedRecord.diagnostics ? (
                    <GuideImportDiagnosticsPanel
                      diagnostics={selectedRecord.diagnostics}
                      quality={selectedRecord.quality}
                      compact
                      onPreviewImage={setPreviewImage}
                    />
                  ) : null}
                    </>
                  ) : (
                    <div className="guide-import-empty">
                      正在加载该导入记录详情，若长时间未出现，请返回记录列表重新选择。
                    </div>
                  )}
                </section>
              ) : null}
            </aside>
          </div>
        </section>
      </div>

      {previewImage ? (
        <div className="guide-import-image-lightbox" role="dialog" aria-modal="true" aria-label="导入图片预览">
          <button
            type="button"
            className="guide-import-image-lightbox-backdrop"
            aria-label="关闭图片预览"
            onClick={() => setPreviewImage(null)}
          />
          <div className="guide-import-image-lightbox-panel">
            <div className="guide-import-image-lightbox-head">
              <strong>{previewImage.label}</strong>
              <button type="button" className="icon-button" onClick={() => setPreviewImage(null)}>
                <X size={18} />
              </button>
            </div>
            <img src={previewImage.url} alt={previewImage.label} />
          </div>
        </div>
      ) : null}
    </>
  );
}

function ImportedGuidePreview({
  guide,
  quality,
  onUseGuide,
  onOptimizeGuide,
  onSetPrimaryGuide,
}: {
  guide: GuideDetail;
  quality: GuideLinkImportResult["quality"];
  onUseGuide: () => void;
  onOptimizeGuide: () => void;
  onSetPrimaryGuide: () => void;
}) {
  return (
    <section className="imported-guide-preview">
      <div className="imported-guide-preview-head">
        <div>
          <span className="guide-import-success-badge">
            <CheckCircle2 size={15} />
            已接入攻略库
          </span>
          <h3>{guide.title}</h3>
          <p>{guide.summary || guide.content.slice(0, 140)}</p>
        </div>
        <div className="imported-guide-score">
          <span>质量评分</span>
          <strong>{String(quality?.score || 0)}</strong>
          <em>{quality?.grade || "待评估"}</em>
        </div>
      </div>

      <div className="imported-guide-chip-row">
        <span>{guide.city || "未知城市"}</span>
        {guide.category ? <span>{guide.category}</span> : null}
        {guide.days ? <span>{guide.days} 天</span> : null}
        {guide.source_type ? <span>{guide.source_type}</span> : null}
        <span>{guide.chunk_count} 段切片</span>
      </div>

      <div className="imported-guide-preview-copy">
        <p>{guide.content}</p>
      </div>

      <div className="imported-guide-actions">
        <button type="button" className="secondary-action" onClick={onUseGuide}>
          应用到当前规划
        </button>
        <button type="button" className="secondary-action" onClick={onOptimizeGuide}>
          基于该攻略继续优化
        </button>
        <button type="button" className="primary-action" onClick={onSetPrimaryGuide}>
          设为主参考攻略
        </button>
      </div>
    </section>
  );
}

function GuideImportDiagnosticsPanel({
  diagnostics,
  quality,
  compact = false,
  onPreviewImage,
}: {
  diagnostics: NonNullable<GuideLinkImportResult["diagnostics"]>;
  quality?: GuideLinkImportResult["quality"];
  compact?: boolean;
  onPreviewImage: (value: ImagePreviewState) => void;
}) {
  const contentSources = diagnostics.content_sources || [];
  const previewGroups = [
    { key: "source", label: "原文片段", lines: diagnostics.source_preview_lines || [] },
    { key: "final", label: "入库正文", lines: diagnostics.final_preview_lines || [] },
    { key: "ocr", label: "OCR 提取", lines: diagnostics.ocr_preview_lines || [] },
    { key: "vision", label: "视觉补全", lines: diagnostics.vision_preview_lines || [] },
    { key: "html", label: "HTML 抽取", lines: diagnostics.html_preview_lines || [] },
  ].filter((item) => item.lines.length);

  return (
    <section className={`guide-import-visual-panel ${compact ? "compact" : ""}`}>
      <div className="guide-import-visual-head">
        <div>
          <span>抓取诊断</span>
          <strong>
            {diagnostics.fetch_method || "未记录抓取方式"}
            {quality?.grade ? ` · 质量 ${quality.grade}` : ""}
          </strong>
        </div>
        <div className="guide-import-visual-badges">
          {diagnostics.ocr_used ? <span>OCR 已参与</span> : null}
          {diagnostics.vision_used ? <span>视觉补全已参与</span> : null}
          {typeof diagnostics.image_count === "number" ? <span>{diagnostics.image_count} 张图</span> : null}
        </div>
      </div>

      <div className="guide-import-visual-stats">
        <div>
          <span>正文长度</span>
          <strong>{String(diagnostics.final_content_length || 0)}</strong>
        </div>
        <div>
          <span>OCR 字数</span>
          <strong>{String(diagnostics.ocr_text_length || 0)}</strong>
        </div>
        <div>
          <span>OCR 覆盖</span>
          <strong>
            {diagnostics.ocr_target_count
              ? `${String(diagnostics.ocr_success_count || 0)} / ${String(diagnostics.ocr_target_count)}`
              : "-"}
          </strong>
        </div>
        <div>
          <span>视觉字数</span>
          <strong>{String(diagnostics.vision_text_length || 0)}</strong>
        </div>
      </div>

      {contentSources.length ? (
        <div className="guide-import-source-grid">
          {contentSources.map((item) => (
            <div key={item} className="guide-import-source-card active">
              <span>{item}</span>
              <strong className="guide-import-source-value">已参与正文汇总</strong>
              <div className="guide-import-source-meter">
                <span style={{ width: "100%" }} />
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {previewGroups.length ? (
        <div className="guide-import-snippet-grid">
          {previewGroups.slice(0, compact ? 2 : 4).map((group) => (
            <div key={group.key} className="guide-import-snippet-card">
              <strong>{group.label}</strong>
              <div className="guide-import-snippet-list">
                {group.lines.slice(0, compact ? 3 : 5).map((line, index) => (
                  <p key={`${group.key}-${index}`}>{line}</p>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {diagnostics.image_urls?.length ? (
        <div className="guide-import-inline-media-strip">
          {diagnostics.image_urls.slice(0, compact ? 4 : 8).map((url, index) => (
            <button
              key={`${url}-${index}`}
              type="button"
              className="guide-import-inline-thumb"
              onClick={() => onPreviewImage({ url, label: `导入原图 ${index + 1}` })}
            >
              <img src={url} alt={`导入原图 ${index + 1}`} />
              <span>
                <ImageIcon size={13} />
                原图 {index + 1}
              </span>
            </button>
          ))}
        </div>
      ) : null}

      {diagnostics.attempts?.length ? (
        <div className="guide-import-preview-list">
          {diagnostics.attempts.slice(0, compact ? 3 : 6).map((attempt, index) => (
            <div key={`${attempt.method || "attempt"}-${index}`} className="guide-import-attempt-item">
              <div>
                <span>尝试 {index + 1}</span>
                <strong>{attempt.method || "unknown"}</strong>
              </div>
              <div>
                <span>状态</span>
                <strong>{attempt.issue_code || String(attempt.status_code || "-")}</strong>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function cloneStructured(value: GuideStructuredDraft | null | undefined): GuideStructuredDraft {
  return {
    ...EMPTY_STRUCTURED,
    ...(value || {}),
    travel_style_tags: [...(value?.travel_style_tags || [])],
    scenic_spots: [...(value?.scenic_spots || [])],
    route_nodes: [...(value?.route_nodes || [])],
    budget_tips: [...(value?.budget_tips || [])],
    risk_notes: [...(value?.risk_notes || [])],
  };
}

function updateStructuredDraft(
  setter: React.Dispatch<React.SetStateAction<PreviewDraft | null>>,
  key: keyof GuideStructuredDraft,
  value: GuideStructuredDraft[keyof GuideStructuredDraft],
) {
  setter((current) => {
    if (!current) return current;
    return {
      ...current,
      structured: {
        ...current.structured,
        [key]: value,
      },
    };
  });
}

function parseList(value: string) {
  return value
    .split(/[\n,，、]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatList(value?: string[] | null) {
  return (value || []).join(", ");
}

function normalizeOptionalNumber(value: string) {
  const next = Number(value);
  return Number.isFinite(next) && next > 0 ? next : null;
}

function buildHeadline(
  importResult: GuideLinkImportResult | null,
  previewResult: GuideLinkPreviewResult | null,
  selectedRecord: GuideImportRecordItem | null,
) {
  if (importResult?.title) {
    return `已完成导入：${importResult.title}`;
  }
  if (previewResult?.title) {
    return `已生成预览：${previewResult.title}`;
  }
  if (selectedRecord?.title) {
    return `历史记录：${selectedRecord.title}`;
  }
  return "准备接收新的攻略来源";
}

function buildStatusText(status: string) {
  const mapping: Record<string, string> = {
    indexed: "已入库",
    duplicate: "重复命中",
    pending: "待补录",
    preview_ready: "可编辑预览",
    failed: "抓取失败",
    blocked: "访问受限",
    ready: "待开始",
  };
  return mapping[status] || status;
}

function buildTaskTitle(task: GuideImportTaskItem) {
  if (task.title) return task.title;
  if (task.status === "succeeded") return "导入预览已完成";
  if (task.status === "failed") return "导入任务失败";
  return "正在后台抓取攻略";
}

function buildTaskStatus(status: string) {
  const mapping: Record<string, string> = {
    queued: "排队中",
    running: "处理中",
    succeeded: "已完成",
    failed: "失败",
  };
  return mapping[status] || status;
}

function buildTaskStage(stage: string) {
  const mapping: Record<string, string> = {
    queued: "等待",
    fetching: "抓取页面",
    extracting: "解析图文",
    finalizing: "生成预览",
    done: "完成",
    failed: "失败",
  };
  return mapping[stage] || stage;
}

function resolveEnhancementLabel(diagnostics: GuideLinkImportResult["diagnostics"]) {
  if (!diagnostics) return "待执行";
  if (diagnostics.vision_used && diagnostics.ocr_used) return "OCR + 视觉";
  if (diagnostics.vision_used) return "视觉补全";
  if (diagnostics.ocr_used) return "OCR 提取";
  return "正文直抽";
}

function formatDateTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
