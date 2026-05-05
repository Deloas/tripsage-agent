import {
  ArrowUpRight,
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  DatabaseZap,
  Layers3,
  Link2,
  Loader2,
  MapPinned,
  PanelRightOpen,
  RefreshCw,
  Route,
  Search,
  SendHorizonal,
  Sparkles,
  TrainFront,
  X,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { fetchGuideDetail, fetchGuideLibrary, fetchGuideRoutePreview } from "../lib/api";
import type { GuideDetail, GuideLibraryResult, GuideRoutePreviewResult, GuideSourceItem, RailwayQueryResult } from "../lib/types";

interface KnowledgeBaseWorkbenchProps {
  guideSources: GuideSourceItem[];
  guideResult?: string | null;
  crawlLoading: boolean;
  onAddGuide: () => void;
  onCrawlWeibo: () => void;
  onUseGuide: (guide: GuideDetail) => void;
  onPlanFromGuide?: (guide: GuideDetail) => void;
  onOptimizeGuide?: (guide: GuideDetail) => void;
  onSetPrimaryGuide?: (guide: GuideDetail) => void;
  onOpenImportRecord?: (recordId: number) => void;
  onGuideQuickAsk?: (guide: GuideDetail, prompt: string) => void;
  onOpenPlanningWorkspace?: () => void;
  onOpenRailwayWorkspace?: () => void;
  onQueryRailwayFromGuide?: (
    guide: GuideDetail,
    payload: { origin: string; destination: string; date: string },
  ) => Promise<RailwayQueryResult>;
  activeReferencedGuide?: GuideDetail | null;
  preselectedGuideRequest?: {
    guideId: number;
    detailMode: "preview" | "edit";
    nonce: number;
  } | null;
}

const PAGE_SIZE = 12;

const emptyLibraryResult: GuideLibraryResult = {
  items: [],
  total: 0,
  limit: PAGE_SIZE,
  offset: 0,
  filters: {
    source_types: [],
    cities: [],
    categories: [],
  },
};

export function KnowledgeBaseWorkbench({
  guideSources,
  guideResult,
  crawlLoading,
  onAddGuide,
  onCrawlWeibo,
  onUseGuide,
  onPlanFromGuide,
  onOptimizeGuide,
  onSetPrimaryGuide,
  onOpenImportRecord,
  onGuideQuickAsk,
  onOpenPlanningWorkspace,
  onOpenRailwayWorkspace,
  onQueryRailwayFromGuide,
  activeReferencedGuide,
  preselectedGuideRequest,
}: KnowledgeBaseWorkbenchProps) {
  const [library, setLibrary] = useState<GuideLibraryResult>(emptyLibraryResult);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [keywordDraft, setKeywordDraft] = useState("");
  const [keyword, setKeyword] = useState("");
  const [city, setCity] = useState("");
  const [category, setCategory] = useState("");
  const [sourceType, setSourceType] = useState("");
  const [sortBy, setSortBy] = useState<"latest" | "oldest" | "city_hot" | "source_priority">("latest");
  const [page, setPage] = useState(1);
  const [selectedGuideId, setSelectedGuideId] = useState<number | null>(null);
  const [selectedGuide, setSelectedGuide] = useState<GuideDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [previewImage, setPreviewImage] = useState<{ url: string; label: string } | null>(null);
  const [routePreview, setRoutePreview] = useState<GuideRoutePreviewResult | null>(null);
  const [routePreviewLoading, setRoutePreviewLoading] = useState(false);
  const [routePreviewError, setRoutePreviewError] = useState<string | null>(null);

  const indexedCount = guideSources.filter((item) => item.crawl_status === "indexed").length;
  const failedCount = guideSources.filter((item) => item.crawl_status === "failed" || item.crawl_status === "blocked").length;
  const pendingCount = guideSources.filter((item) => item.crawl_status === "pending").length;

  const totalPages = Math.max(1, Math.ceil(library.total / PAGE_SIZE));
  const visiblePages = buildVisiblePages(page, totalPages);

  useEffect(() => {
    let cancelled = false;

    async function loadLibrary() {
      setLoading(true);
      setError(null);
      try {
        const result = await fetchGuideLibrary({
          keyword: keyword || undefined,
          city: city || undefined,
          category: category || undefined,
          source_type: sourceType || undefined,
          sort_by: sortBy,
          limit: PAGE_SIZE,
          offset: (page - 1) * PAGE_SIZE,
        });
        if (!cancelled) {
          setLibrary(result);
        }
      } catch {
        if (!cancelled) {
          setError("攻略库暂时无法加载，请确认后端服务已经启动。");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadLibrary();
    return () => {
      cancelled = true;
    };
  }, [category, city, keyword, page, sortBy, sourceType]);

  useEffect(() => {
    if (!selectedGuideId) {
      setSelectedGuide(null);
      setRoutePreview(null);
      setRoutePreviewError(null);
      return;
    }
    setRoutePreview(null);
    setRoutePreviewError(null);
    const guideId = selectedGuideId;
    let cancelled = false;
    async function loadGuideDetail() {
      setDetailLoading(true);
      try {
        const result = await fetchGuideDetail(guideId);
        if (!cancelled) {
          setSelectedGuide(result);
          if (extractGuideMobilityNodeNames(result).length) {
            setRoutePreviewLoading(true);
            void fetchGuideRoutePreview(guideId)
              .then((preview) => {
                if (!cancelled) {
                  setRoutePreview(preview);
                  setRoutePreviewError(null);
                }
              })
              .catch(() => {
                if (!cancelled) {
                  setRoutePreviewError("已识别攻略地点，可手动重试生成高德路线。");
                }
              })
              .finally(() => {
                if (!cancelled) {
                  setRoutePreviewLoading(false);
                }
              });
          }
        }
      } catch {
        if (!cancelled) {
          setSelectedGuide(null);
        }
      } finally {
        if (!cancelled) {
          setDetailLoading(false);
        }
      }
    }
    void loadGuideDetail();
    return () => {
      cancelled = true;
    };
  }, [selectedGuideId]);

  useEffect(() => {
    if (!preselectedGuideRequest) return;
    setSelectedGuideId(preselectedGuideRequest.guideId);
  }, [preselectedGuideRequest]);

  function applyKeyword(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setKeyword(keywordDraft.trim());
  }

  function resetFilters() {
    setKeywordDraft("");
    setKeyword("");
    setCity("");
    setCategory("");
    setSourceType("");
    setSortBy("latest");
    setPage(1);
  }

  function handleUseSelectedGuide() {
    if (!selectedGuide) return;
    onUseGuide(selectedGuide);
    setSelectedGuideId(null);
  }

  async function handleBuildRoutePreview() {
    if (!selectedGuide) return;
    setRoutePreviewLoading(true);
    setRoutePreviewError(null);
    try {
      const result = await fetchGuideRoutePreview(selectedGuide.id);
      setRoutePreview(result);
    } catch {
      setRoutePreviewError("攻略地图暂时生成失败，请确认地图接口配置和后端服务状态。");
    } finally {
      setRoutePreviewLoading(false);
    }
  }

  const filterSummary = useMemo(() => {
    const parts = [
      sourceType ? `来源 ${sourceType}` : null,
      city ? `地区 ${city}` : null,
      category ? `分类 ${category}` : null,
      keyword ? `关键词 ${keyword}` : null,
    ].filter(Boolean);
    return parts.length ? parts.join(" · ") : "全部攻略";
  }, [category, city, keyword, sourceType]);

  const structured = selectedGuide?.structured;
  const importAudit = selectedGuide?.import_audit;

  return (
    <section className="page-band knowledge-library-band" aria-label="攻略库工作台">
      <div className="knowledge-library-head">
        <div>
          <div className="section-kicker">
            <DatabaseZap size={15} />
            攻略库工作台
          </div>
          <h3>本地攻略检索、筛选与规划复用</h3>
          <p>把攻略库做成可检索、可复核、可加入规划的正式知识资产，而不是只展示一段摘要。</p>
        </div>
        <div className="knowledge-library-actions">
          <button type="button" className="secondary-action" onClick={onAddGuide}>
            <Sparkles size={15} />
            添加攻略
          </button>
          <button type="button" className="primary-action" onClick={onCrawlWeibo} disabled={crawlLoading}>
            <RefreshCw size={15} className={crawlLoading ? "spin" : ""} />
            {crawlLoading ? "正在补采" : "继续补采微博"}
          </button>
        </div>
      </div>

      <div className="knowledge-library-signal-grid">
        <MetricCard label="攻略总数" value={String(library.total)} detail={filterSummary} />
        <MetricCard label="已入库源" value={String(indexedCount)} detail={`异常 ${failedCount} · 待处理 ${pendingCount}`} />
        <MetricCard label="来源类型" value={String(library.filters.source_types.length)} detail="手动入库与微博采集统一管理" />
        <MetricCard label="覆盖分类" value={String(library.filters.categories.length)} detail="支持地区、分类、来源交叉筛选" />
      </div>

      {guideResult ? <div className="knowledge-library-feedback">{guideResult}</div> : null}

      <div className="knowledge-library-shell">
        <aside className="knowledge-library-sidebar">
          <form className="knowledge-search-box" onSubmit={applyKeyword}>
            <label className="knowledge-search-input">
              <Search size={15} />
              <input
                value={keywordDraft}
                onChange={(event) => setKeywordDraft(event.target.value)}
                placeholder="搜索城市、玩法、预算、景点、美食"
              />
            </label>
            <button type="submit" className="primary-action">检索</button>
          </form>

          <div className="knowledge-filter-grid">
            <label>
              <span>来源类型</span>
              <select value={sourceType} onChange={(event) => { setSourceType(event.target.value); setPage(1); }}>
                <option value="">全部来源</option>
                {library.filters.source_types.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label} · {item.count}
                  </option>
                ))}
              </select>
            </label>

            <label>
              <span>地区 / 城市</span>
              <select value={city} onChange={(event) => { setCity(event.target.value); setPage(1); }}>
                <option value="">全部地区</option>
                {library.filters.cities.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label} · {item.count}
                  </option>
                ))}
              </select>
            </label>

            <label>
              <span>分类</span>
              <select value={category} onChange={(event) => { setCategory(event.target.value); setPage(1); }}>
                <option value="">全部分类</option>
                {library.filters.categories.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label} · {item.count}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="knowledge-filter-actions">
            <button type="button" className="secondary-action" onClick={resetFilters}>清空筛选</button>
            <span>{filterSummary}</span>
          </div>

          <div className="knowledge-facet-clusters">
            <FacetCluster
              title="热门分类"
              items={library.filters.categories.slice(0, 8)}
              onPick={(value) => {
                setCategory(value);
                setPage(1);
              }}
            />
            <FacetCluster
              title="热门地区"
              items={library.filters.cities.slice(0, 8)}
              onPick={(value) => {
                setCity(value);
                setPage(1);
              }}
            />
          </div>
        </aside>

        <div className="knowledge-library-main">
          <div className="knowledge-library-toolbar">
            <div>
              <strong>{library.total}</strong>
              <span> 条符合条件的攻略</span>
            </div>
            <div className="knowledge-toolbar-actions">
              <label className="knowledge-sort-select">
                <ChevronsUpDown size={14} />
                <select value={sortBy} onChange={(event) => { setSortBy(event.target.value as typeof sortBy); setPage(1); }}>
                  <option value="latest">最新入库</option>
                  <option value="oldest">最早入库</option>
                  <option value="city_hot">热门地区优先</option>
                  <option value="source_priority">来源优先级</option>
                </select>
              </label>
              <em>
                第 {page} / {totalPages} 页 · 每页 {PAGE_SIZE} 条
              </em>
            </div>
          </div>

          {error ? <div className="knowledge-library-empty danger">{error}</div> : null}

          {!error ? (
            <div className="knowledge-guide-grid">
              {loading
                ? Array.from({ length: 6 }).map((_, index) => (
                  <article className="knowledge-guide-card skeleton" key={`skeleton-${index}`}>
                    <div className="knowledge-guide-badges">
                      <span />
                      <span />
                      <span />
                    </div>
                    <strong />
                    <p />
                    <p />
                    <div className="knowledge-guide-footer">
                      <span />
                      <span />
                    </div>
                  </article>
                ))
                : library.items.map((guide) => (
                  <article className="knowledge-guide-card" key={guide.id}>
                    <div className="knowledge-guide-badges">
                      <span>{guide.city}</span>
                      <span>{guide.category || "未分类"}</span>
                      <span>{guide.source_type || "local"}</span>
                    </div>
                    <strong>{guide.title}</strong>
                    <p>{guide.summary}</p>
                    <div className="knowledge-guide-footer">
                      <span>{guide.crawl_status || "indexed"}</span>
                      <div className="knowledge-guide-actions">
                        <button type="button" className="guide-inline-action" onClick={() => setSelectedGuideId(guide.id)}>
                          <PanelRightOpen size={14} />
                          查看详情
                        </button>
                        {guide.source_url ? (
                          <a href={guide.source_url} target="_blank" rel="noreferrer">
                            查看来源
                            <ArrowUpRight size={14} />
                          </a>
                        ) : (
                          <em>本地条目</em>
                        )}
                      </div>
                    </div>
                  </article>
                ))}
            </div>
          ) : null}

          {!loading && !error && !library.items.length ? (
            <div className="knowledge-library-empty">
              <Layers3 size={18} />
              <span>当前筛选条件下没有攻略，换一个地区、分类或关键词试试。</span>
            </div>
          ) : null}

          <div className="knowledge-pagination">
            <button type="button" className="secondary-action" disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>
              <ChevronLeft size={14} />
              上一页
            </button>
            <div className="knowledge-page-pills">
              {visiblePages.map((item) => (
                <button
                  type="button"
                  key={item}
                  className={`knowledge-page-pill ${item === page ? "active" : ""}`}
                  onClick={() => setPage(item)}
                >
                  {item}
                </button>
              ))}
            </div>
            <button type="button" className="secondary-action" disabled={page >= totalPages} onClick={() => setPage((current) => Math.min(totalPages, current + 1))}>
              下一页
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      </div>

      {selectedGuideId ? (
        <div className="knowledge-detail-overlay" role="dialog" aria-modal="true" aria-label="攻略详情">
          <button type="button" className="knowledge-detail-backdrop" onClick={() => setSelectedGuideId(null)} aria-label="关闭攻略详情" />
          <aside className="knowledge-detail-drawer">
            <div className="knowledge-detail-head">
              <div>
                <div className="section-kicker">
                  <DatabaseZap size={15} />
                  攻略详情
                </div>
                <h4>{selectedGuide?.title || "正在加载"}</h4>
                <div className="knowledge-detail-meta">
                  <span>{selectedGuide?.city || "未知城市"}</span>
                  <span>{selectedGuide?.category || "未分类"}</span>
                  <span>{selectedGuide?.source_type || "local"}</span>
                </div>
              </div>
              <div className="knowledge-detail-head-actions">
                {selectedGuide ? (
                  <button type="button" className="primary-action" onClick={handleUseSelectedGuide}>
                    <Sparkles size={15} />
                    加入当前规划
                  </button>
                ) : null}
                {selectedGuide && onSetPrimaryGuide ? (
                  <button
                    type="button"
                    className="secondary-action"
                    onClick={() => onSetPrimaryGuide(selectedGuide)}
                    disabled={activeReferencedGuide?.id === selectedGuide.id}
                  >
                    <DatabaseZap size={15} />
                    {activeReferencedGuide?.id === selectedGuide.id ? "当前主参考攻略" : "设为主参考攻略"}
                  </button>
                ) : null}
                <button type="button" className="icon-button" onClick={() => setSelectedGuideId(null)} aria-label="关闭详情">
                  <X size={16} />
                </button>
              </div>
            </div>

            {detailLoading ? <div className="knowledge-detail-loading">正在加载攻略详情...</div> : null}

            {!detailLoading && selectedGuide ? (
              <div className="knowledge-detail-body">
                <div className="knowledge-detail-stat-grid">
                  <MetricCard label="摘要切片" value={String(selectedGuide.chunk_count)} detail="用于本地检索与命中展示" />
                  <MetricCard label="地点抽取" value={String(selectedGuide.places.length)} detail="供地图、路线与规划复用" />
                  <MetricCard label="建议天数" value={String(selectedGuide.days || structured?.days || "-")} detail="从标题与正文自动抽取" />
                </div>

                <section className="knowledge-detail-section">
                  <div className="knowledge-detail-section-head">
                    <strong>结构化信息</strong>
                    {selectedGuide.source_url ? (
                      <a href={selectedGuide.source_url} target="_blank" rel="noreferrer">
                        <Link2 size={14} />
                        打开来源
                      </a>
                    ) : (
                      <span>本地入库条目</span>
                    )}
                  </div>
                  <div className="knowledge-structured-grid">
                    <StructuredBlock title="预算参考" value={structured?.budget_range || formatBudgetRange(selectedGuide.budget_min, selectedGuide.budget_max) || "未识别"} />
                    <StructuredBlock title="交通建议" value={joinDisplay(structured?.transport_modes) || "未识别"} />
                    <StructuredBlock title="住宿建议" value={joinDisplay(structured?.lodging_suggestions) || "未识别"} />
                    <StructuredBlock title="玩法风格" value={joinDisplay(structured?.travel_style_tags) || selectedGuide.travel_style || "未识别"} />
                  </div>
                  <div className="knowledge-structured-columns">
                    <StructuredList title="核心景点" items={structured?.scenic_spots || []} />
                    <StructuredList title="美食线索" items={structured?.food_spots || []} />
                  </div>
                </section>

                <section className="knowledge-detail-section knowledge-map-section">
                  <div className="knowledge-detail-section-head">
                    <strong>攻略地图</strong>
                    <button
                      type="button"
                      className="secondary-action compact"
                      onClick={handleBuildRoutePreview}
                      disabled={routePreviewLoading || !extractGuideMobilityNodeNames(selectedGuide).length}
                    >
                      {routePreviewLoading ? <Loader2 size={14} className="spin" /> : <Route size={14} />}
                      生成路线预览
                    </button>
                  </div>
                  <GuideRoutePreviewPanel
                    guide={selectedGuide}
                    routePreview={routePreview}
                    loading={routePreviewLoading}
                    error={routePreviewError}
                    onBuild={handleBuildRoutePreview}
                    onGuideQuickAsk={onGuideQuickAsk}
                    onOpenPlanningWorkspace={onOpenPlanningWorkspace}
                    onOpenRailwayWorkspace={onOpenRailwayWorkspace}
                    onQueryRailwayFromGuide={onQueryRailwayFromGuide}
                  />
                </section>

                <section className="knowledge-detail-section knowledge-import-audit-section">
                  <div className="knowledge-detail-section-head">
                    <strong>导入质检</strong>
                    <span>{importAudit ? "图片提取、原文片段与入库结果对照" : "暂无导入质检记录"}</span>
                  </div>
                  <GuideImportAuditPanel
                    guide={selectedGuide}
                    audit={importAudit}
                    onUseGuide={onUseGuide}
                    onPlanFromGuide={onPlanFromGuide}
                    onOptimizeGuide={onOptimizeGuide}
                    onSetPrimaryGuide={onSetPrimaryGuide}
                    activeReferencedGuideId={activeReferencedGuide?.id || null}
                    onOpenImportRecord={onOpenImportRecord}
                    onPreviewImage={(url, label) => setPreviewImage({ url, label })}
                  />
                </section>

                <section className="knowledge-detail-section">
                  <div className="knowledge-detail-section-head">
                    <strong>正文</strong>
                    <span>{structured?.summary || selectedGuide.summary}</span>
                  </div>
                  <div className="knowledge-detail-content">
                    {(selectedGuide.content || "暂无正文").split(/\n{1,2}/).filter(Boolean).map((line, index) => (
                      <p key={`${index}-${line.slice(0, 18)}`}>{line}</p>
                    ))}
                  </div>
                </section>

                <section className="knowledge-detail-section">
                  <div className="knowledge-detail-section-head">
                    <strong>命中切片</strong>
                    <span>{selectedGuide.chunks.length} 条</span>
                  </div>
                  <div className="knowledge-detail-chunks">
                    {selectedGuide.chunks.map((chunk) => (
                      <article className="knowledge-detail-chunk" key={chunk.id}>
                        <span>片段 {chunk.chunk_index + 1}</span>
                        <p>{chunk.content}</p>
                      </article>
                    ))}
                  </div>
                </section>

                <section className="knowledge-detail-section">
                  <div className="knowledge-detail-section-head">
                    <strong>地点抽取</strong>
                    <span>{selectedGuide.places.length} 个</span>
                  </div>
                  <div className="knowledge-detail-places">
                    {selectedGuide.places.length ? selectedGuide.places.map((place) => (
                      <div className="knowledge-place-pill" key={`${place.name}-${place.place_type || ""}`}>
                        <MapPinned size={14} />
                        <div>
                          <strong>{place.name}</strong>
                          <span>{place.place_type || "地点"}</span>
                        </div>
                      </div>
                    )) : <div className="knowledge-facet-empty">当前还没有抽取到地点。</div>}
                  </div>
                </section>
              </div>
            ) : null}
          </aside>
        </div>
      ) : null}

      {previewImage ? (
        <ImageLightbox image={previewImage} onClose={() => setPreviewImage(null)} />
      ) : null}
    </section>
  );
}

function MetricCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <article className="knowledge-metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}

function FacetCluster({
  title,
  items,
  onPick,
}: {
  title: string;
  items: Array<{ value: string; label: string; count: number }>;
  onPick: (value: string) => void;
}) {
  return (
    <div className="knowledge-facet-cluster">
      <div className="knowledge-facet-title">{title}</div>
      <div className="knowledge-facet-pills">
        {items.length ? items.map((item) => (
          <button type="button" key={item.value} onClick={() => onPick(item.value)}>
            {item.label}
            <span>{item.count}</span>
          </button>
        )) : <span className="knowledge-facet-empty">暂无聚类</span>}
      </div>
    </div>
  );
}

function StructuredBlock({ title, value }: { title: string; value: string }) {
  return (
    <article className="knowledge-structured-card">
      <span>{title}</span>
      <strong>{value}</strong>
    </article>
  );
}

function StructuredList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="knowledge-structured-list">
      <span>{title}</span>
      {items.length ? (
        <div className="knowledge-structured-tags">
          {items.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      ) : (
        <div className="knowledge-facet-empty">暂无提取结果</div>
      )}
    </div>
  );
}

function GuideRoutePreviewPanel({
  guide,
  routePreview,
  loading,
  error,
  onBuild,
  onGuideQuickAsk,
  onOpenPlanningWorkspace,
  onOpenRailwayWorkspace,
  onQueryRailwayFromGuide,
}: {
  guide: GuideDetail;
  routePreview: GuideRoutePreviewResult | null;
  loading: boolean;
  error: string | null;
  onBuild: () => void;
  onGuideQuickAsk?: (guide: GuideDetail, prompt: string) => void;
  onOpenPlanningWorkspace?: () => void;
  onOpenRailwayWorkspace?: () => void;
  onQueryRailwayFromGuide?: (
    guide: GuideDetail,
    payload: { origin: string; destination: string; date: string },
  ) => Promise<RailwayQueryResult>;
}) {
  const candidateNodes = extractGuideMobilityNodeNames(guide);
  const sourceNodes = routePreview?.nodes.length
    ? routePreview.nodes
    : candidateNodes.map((name) => ({ name, type: "待预览", city: guide.city, source: "guide" }));
  const [orderedNodes, setOrderedNodes] = useState(sourceNodes);
  const [railwayOrigin, setRailwayOrigin] = useState("");
  const [railwayDate, setRailwayDate] = useState("");
  const [railwayLoading, setRailwayLoading] = useState(false);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const nodeCount = sourceNodes.length;
  const routeDayGroups = buildRouteDayGroups(orderedNodes, guide.days || guide.structured?.days || 1);
  const railwayDestination = routePreview?.railway_seed.destination || guide.city || "";
  const railwayStation = routePreview?.railway_seed.destination_station || railwayDestination;

  useEffect(() => {
    setOrderedNodes(sourceNodes);
    setActionNotice(null);
  }, [routePreview?.guide_id, routePreview?.nodes.length, guide.id]);

  function moveNode(index: number, direction: -1 | 1) {
    setOrderedNodes((current) => {
      const nextIndex = index + direction;
      if (nextIndex < 0 || nextIndex >= current.length) return current;
      const next = [...current];
      const item = next[index];
      next[index] = next[nextIndex];
      next[nextIndex] = item;
      return next;
    });
  }

  function sendMapToAgent() {
    if (!onGuideQuickAsk) return;
    onGuideQuickAsk(guide, buildGuideMapPrompt(guide, orderedNodes, routePreview));
    onOpenPlanningWorkspace?.();
  }

  async function syncRailway() {
    if (!onQueryRailwayFromGuide || !railwayOrigin.trim() || !railwayDate.trim() || !railwayDestination) return;
    setRailwayLoading(true);
    setActionNotice(null);
    try {
      const result = await onQueryRailwayFromGuide(guide, {
        origin: railwayOrigin.trim(),
        destination: railwayDestination,
        date: railwayDate.trim(),
      });
      setActionNotice(`已同步到铁路工作台：${result.trains.length} 条车次候选。`);
      onOpenRailwayWorkspace?.();
    } catch {
      setActionNotice("铁路同步失败，请检查 12306 MCP 或日期条件后重试。");
    } finally {
      setRailwayLoading(false);
    }
  }

  return (
    <div className="guide-mobility-panel knowledge-guide-map-panel">
      <div className="guide-mobility-head">
        <div>
          <span className="section-kicker">
            <MapPinned size={14} />
            地图路线
          </span>
          <strong>{nodeCount ? `${nodeCount} 个地点可用于路线预览` : "暂未识别到可预览地点"}</strong>
        </div>
        <button type="button" className="primary-action compact" onClick={onBuild} disabled={loading || !nodeCount}>
          {loading ? <Loader2 size={14} className="spin" /> : <MapPinned size={14} />}
          {routePreview ? "重新生成" : "查看攻略地图"}
        </button>
      </div>

      <div className="guide-mobility-node-strip">
        {orderedNodes.length
          ? orderedNodes.map((node, index) => (
            <div className={`guide-mobility-node ${routePreview ? "" : "muted"}`} key={`${node.name}-${index}`}>
              <span>{index + 1}</span>
              <strong>{node.name}</strong>
              <em>{node.type || (routePreview ? "地点" : "待预览")}</em>
            </div>
          ))
          : null}
        {!nodeCount ? <div className="summary-list-empty compact-empty">这篇攻略还没有抽取到足够的地点，可先编辑攻略补充景点或路线节点。</div> : null}
      </div>

      {error ? <div className="guide-mobility-error">{error}</div> : null}

      {orderedNodes.length ? (
        <div className="guide-route-preview-card">
          <div className="guide-route-canvas knowledge-route-canvas" aria-label="攻略地图路线预览">
            {orderedNodes.map((node, index) => (
              <div
                className="guide-route-pin"
                style={{
                  left: `${12 + (index % 4) * 24}%`,
                  top: `${20 + Math.floor(index / 4) * 32 + (index % 2) * 6}%`,
                }}
                key={`${node.name}-${index}`}
              >
                <span>{index + 1}</span>
                <strong>{node.name}</strong>
              </div>
            ))}
          </div>
          {routePreview ? (
            <>
              <div className="guide-route-summary">
                <div>
                  <span>总通勤</span>
                  <strong>{formatMeters(routePreview.total_distance_meters)} · {routePreview.total_duration_minutes || 0} 分钟</strong>
                </div>
                <div>
                  <span>路线段</span>
                  <strong>{routePreview.routes.length} 段</strong>
                </div>
                <div>
                  <span>数据源</span>
                  <strong>{routePreview.fallback ? "兜底预览" : "高德地图"}</strong>
                </div>
              </div>
              <div className="guide-route-leg-list">
                {routePreview.routes.map((route) => (
                  <article key={route.index}>
                    <strong>{route.origin.name} → {route.destination.name}</strong>
                    <span>{formatMeters(route.distance_meters || 0)} / {route.duration_minutes || 0} 分钟</span>
                  </article>
                ))}
              </div>
            </>
          ) : (
            <div className="knowledge-route-action-notice">已根据攻略地点生成路线草图，点击生成路线预览可补充真实通勤距离与耗时。</div>
          )}

          <div className="knowledge-route-product-grid">
            <section className="knowledge-route-day-board" aria-label="按天路线">
              <div className="knowledge-route-panel-head">
                <strong>按天路线</strong>
                <span>{routeDayGroups.length} 天</span>
              </div>
              <div className="knowledge-route-day-list">
                {routeDayGroups.map((group) => (
                  <article key={group.day}>
                    <span>Day {group.day}</span>
                    <strong>{group.nodes.map((node) => node.name).join(" → ")}</strong>
                  </article>
                ))}
              </div>
            </section>

            <section className="knowledge-route-order-board" aria-label="地点顺序调整">
              <div className="knowledge-route-panel-head">
                <strong>地点顺序</strong>
                <span>可调整后交给智能体优化</span>
              </div>
              <div className="knowledge-route-order-list">
                {orderedNodes.map((node, index) => (
                  <article key={`${node.name}-${index}`}>
                    <span>{index + 1}</span>
                    <strong>{node.name}</strong>
                    <div>
                      <button type="button" className="icon-button mini" onClick={() => moveNode(index, -1)} disabled={index === 0} aria-label="上移地点">
                        <ArrowUp size={13} />
                      </button>
                      <button type="button" className="icon-button mini" onClick={() => moveNode(index, 1)} disabled={index === orderedNodes.length - 1} aria-label="下移地点">
                        <ArrowDown size={13} />
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          </div>

          <div className="knowledge-route-railway-hint">
            <TrainHint
              origin={railwayOrigin}
              date={railwayDate}
              destination={railwayDestination}
              station={railwayStation}
              loading={railwayLoading}
              canSync={Boolean(onQueryRailwayFromGuide)}
              onOriginChange={setRailwayOrigin}
              onDateChange={setRailwayDate}
              onSync={syncRailway}
            />
          </div>

          <div className="knowledge-route-action-row">
            <button type="button" className="primary-action" onClick={sendMapToAgent} disabled={!onGuideQuickAsk}>
              <SendHorizonal size={15} />
              用该路线继续优化
            </button>
            <button type="button" className="secondary-action" onClick={onOpenPlanningWorkspace} disabled={!onOpenPlanningWorkspace}>
              <Route size={15} />
              打开规划页
            </button>
          </div>
          {actionNotice ? <div className="knowledge-route-action-notice">{actionNotice}</div> : null}
        </div>
      ) : null}
    </div>
  );
}

function TrainHint({
  origin,
  date,
  destination,
  station,
  loading,
  canSync,
  onOriginChange,
  onDateChange,
  onSync,
}: {
  origin: string;
  date: string;
  destination: string;
  station: string;
  loading: boolean;
  canSync: boolean;
  onOriginChange: (value: string) => void;
  onDateChange: (value: string) => void;
  onSync: () => void;
}) {
  return (
    <div className="guide-railway-seed-panel knowledge-route-train-hint">
      <div className="guide-railway-seed-copy">
        <span>铁路条件</span>
        <strong>{station || destination || "目的地待识别"}</strong>
        <p>补充出发地和日期后，可把目的地条件直接带入 12306 工作台。</p>
      </div>
      <div className="guide-railway-form knowledge-route-railway-form">
        <label>
          <span>出发城市</span>
          <input value={origin} onChange={(event) => onOriginChange(event.target.value)} placeholder="例如：上海" />
        </label>
        <label>
          <span>日期</span>
          <input value={date} onChange={(event) => onDateChange(event.target.value)} placeholder="例如：2026-05-10" />
        </label>
        <button type="button" className="primary-action" onClick={onSync} disabled={loading || !canSync || !origin.trim() || !date.trim() || !destination}>
          {loading ? <Loader2 size={15} className="spin" /> : <TrainFront size={15} />}
          同步铁路
        </button>
      </div>
    </div>
  );
}

function GuideImportAuditPanel({
  guide,
  audit,
  onUseGuide,
  onPlanFromGuide,
  onOptimizeGuide,
  onSetPrimaryGuide,
  activeReferencedGuideId,
  onOpenImportRecord,
  onPreviewImage,
}: {
  guide: GuideDetail;
  audit?: GuideDetail["import_audit"] | null;
  onUseGuide: (guide: GuideDetail) => void;
  onPlanFromGuide?: (guide: GuideDetail) => void;
  onOptimizeGuide?: (guide: GuideDetail) => void;
  onSetPrimaryGuide?: (guide: GuideDetail) => void;
  activeReferencedGuideId?: number | null;
  onOpenImportRecord?: (recordId: number) => void;
  onPreviewImage?: (url: string, label: string) => void;
}) {
  if (!audit) {
    return <div className="knowledge-facet-empty">当前攻略暂无导入质检数据</div>;
  }

  const confidenceCards = [
    { label: "总体可信度", value: audit.confidence.overall },
    { label: "抓取还原", value: audit.confidence.extraction },
    { label: "结构完整度", value: audit.confidence.structure },
    { label: "原文一致性", value: audit.confidence.source_integrity },
  ];

  return (
    <div className="knowledge-import-audit-shell">
      <div className="knowledge-import-audit-topline">
        <article className="knowledge-import-summary-card spotlight">
          <span>导入状态 / 模式</span>
          <strong>{`${audit.status} / ${audit.mode}`}</strong>
          <p>{audit.reason || audit.quality?.grade || "最近一次入库质检已经同步到详情页。"}</p>
        </article>
        <article className="knowledge-import-summary-card">
          <span>图片补充</span>
          <strong>{String(audit.image_urls.length)}</strong>
          <p>{audit.diagnostics?.content_sources?.join(" / ") || "html"}</p>
        </article>
        <article className="knowledge-import-summary-card">
          <span>最近质检</span>
          <strong>{formatAuditDate(audit.created_at)}</strong>
          <p>{audit.diagnostics?.fetch_method || "manual"}</p>
        </article>
      </div>

      <div className="knowledge-import-confidence-grid">
        {confidenceCards.map((item) => (
          <article className="knowledge-import-confidence-card" key={item.label}>
            <span>{item.label}</span>
            <strong>{Math.round(item.value)}</strong>
            <div className="knowledge-import-confidence-bar">
              <i style={{ width: `${Math.max(8, Math.min(100, item.value))}%` }} />
            </div>
          </article>
        ))}
      </div>

      <div className="knowledge-import-action-row">
        <button type="button" className="primary-action" onClick={() => onUseGuide(guide)}>
          <Sparkles size={15} />
          应用该攻略继续对话
        </button>
        {onOptimizeGuide ? (
          <button type="button" className="secondary-action" onClick={() => onOptimizeGuide(guide)}>
            <RefreshCw size={15} />
            基于该攻略二次优化
          </button>
        ) : onPlanFromGuide ? (
          <button type="button" className="secondary-action" onClick={() => onPlanFromGuide(guide)}>
            <RefreshCw size={15} />
            基于该攻略生成方案
          </button>
        ) : null}
        {onOpenImportRecord ? (
          <button type="button" className="secondary-action" onClick={() => onOpenImportRecord(audit.record_id)}>
            <PanelRightOpen size={15} />
            回看本次导入记录
          </button>
        ) : null}
        {onSetPrimaryGuide ? (
          <button
            type="button"
            className="secondary-action"
            onClick={() => onSetPrimaryGuide(guide)}
            disabled={activeReferencedGuideId === guide.id}
          >
            <DatabaseZap size={15} />
            {activeReferencedGuideId === guide.id ? "当前主参考攻略" : "设为主参考攻略"}
          </button>
        ) : null}
      </div>

      {audit.image_urls.length ? (
        <div className="knowledge-import-media-strip">
          {audit.image_urls.map((url, index) => (
            <button
              type="button"
              key={`${url}-${index}`}
              className="knowledge-import-thumb-card"
              onClick={() => onPreviewImage?.(url, `攻略导入原图 ${index + 1}`)}
            >
              <img src={url} alt={`攻略导入原图 ${index + 1}`} loading="lazy" />
              <span>{`原图 ${index + 1}`}</span>
            </button>
          ))}
        </div>
      ) : null}

      <div className="knowledge-import-preview-grid">
        <article className="knowledge-import-preview-card">
          <div className="knowledge-import-preview-head">
            <strong>原文片段</strong>
            <span>{audit.source_preview_lines.length} 条</span>
          </div>
          <div className="knowledge-import-preview-list">
            {audit.source_preview_lines.length ? audit.source_preview_lines.map((line, index) => (
              <p key={`source-${index}-${line.slice(0, 12)}`}>{line}</p>
            )) : <div className="knowledge-facet-empty">未抓取到原文片段</div>}
          </div>
        </article>
        <article className="knowledge-import-preview-card imported">
          <div className="knowledge-import-preview-head">
            <strong>入库正文</strong>
            <span>{audit.imported_preview_lines.length} 条</span>
          </div>
          <div className="knowledge-import-preview-list">
            {audit.imported_preview_lines.length ? audit.imported_preview_lines.map((line, index) => (
              <p key={`imported-${index}-${line.slice(0, 12)}`}>{line}</p>
            )) : <div className="knowledge-facet-empty">未生成入库正文片段</div>}
          </div>
        </article>
      </div>

      <div className="knowledge-import-diff-board">
        {audit.diff_blocks.length ? audit.diff_blocks.map((block, index) => (
          <article className={`knowledge-import-diff-row ${block.type}`} key={`${block.type}-${index}`}>
            <span className="knowledge-import-diff-badge">{formatDiffType(block.type)}</span>
            <div className="knowledge-import-diff-cell">
              <strong>原文</strong>
              <p>{block.source || "--"}</p>
            </div>
            <div className="knowledge-import-diff-cell imported">
              <strong>入库</strong>
              <p>{block.imported || "--"}</p>
            </div>
          </article>
        )) : <div className="knowledge-facet-empty">当前没有可展示的原文 / 入库差异</div>}
      </div>
    </div>
  );
}

function ImageLightbox({
  image,
  onClose,
}: {
  image: { url: string; label: string };
  onClose: () => void;
}) {
  return (
    <div className="knowledge-image-lightbox" role="dialog" aria-modal="true" aria-label={image.label}>
      <button type="button" className="knowledge-image-lightbox-backdrop" onClick={onClose} aria-label="关闭图片预览" />
      <div className="knowledge-image-lightbox-panel">
        <div className="knowledge-image-lightbox-head">
          <strong>{image.label}</strong>
          <button type="button" className="icon-button" onClick={onClose} aria-label="关闭图片预览">
            <X size={16} />
          </button>
        </div>
        <img src={image.url} alt={image.label} />
      </div>
    </div>
  );
}

function joinDisplay(items?: string[] | null) {
  return items?.filter(Boolean).join(" · ") || "";
}

function formatDiffType(type: string) {
  if (type === "shared") return "已核对";
  if (type === "source_only") return "原文独有";
  if (type === "import_only") return "入库新增";
  return "差异";
}

function formatAuditDate(value?: string | null) {
  if (!value) return "暂无";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function extractGuideMobilityNodeNames(guide: GuideDetail): string[] {
  const structured = guide.structured || {};
  const values = [
    ...(structured.route_nodes || []),
    ...(structured.scenic_spots || []),
    ...(structured.food_spots || []),
    ...(guide.places || []).map((place) => place.name),
  ];
  return Array.from(new Set(values.map((item) => String(item || "").trim()).filter(Boolean))).slice(0, 10);
}

function formatMeters(value: number) {
  if (!value) return "0m";
  if (value >= 1000) return `${(value / 1000).toFixed(1)}km`;
  return `${value}m`;
}

function buildRouteDayGroups(nodes: GuideRoutePreviewResult["nodes"], days: number) {
  const safeDays = Math.max(1, Math.min(days || 1, nodes.length || 1));
  const groupSize = Math.max(1, Math.ceil((nodes.length || 1) / safeDays));
  return Array.from({ length: safeDays }, (_, index) => ({
    day: index + 1,
    nodes: nodes.slice(index * groupSize, (index + 1) * groupSize),
  })).filter((group) => group.nodes.length);
}

function buildGuideMapPrompt(
  guide: GuideDetail,
  nodes: GuideRoutePreviewResult["nodes"],
  routePreview: GuideRoutePreviewResult | null,
) {
  const orderedRoute = nodes.map((node, index) => `${index + 1}. ${node.name}`).join("\n");
  const legSummary = routePreview?.routes.length
    ? routePreview.routes.map((route) => (
      `${route.origin.name} → ${route.destination.name}：${formatMeters(route.distance_meters || 0)} / ${route.duration_minutes || 0} 分钟`
    )).join("\n")
    : "暂未生成精确路线段，请根据地点顺序做合理估算。";

  return [
    `请基于《${guide.title}》和我在攻略地图中调整后的地点顺序，继续优化旅行方案。`,
    "",
    "调整后的地点顺序：",
    orderedRoute || "暂无地点",
    "",
    "当前路线段参考：",
    legSummary,
    "",
    "请输出：按天行程、每段交通建议、是否需要删减地点、雨天备选、预算影响和风险提醒。",
  ].join("\n");
}

function formatBudgetRange(min?: number | null, max?: number | null) {
  if (min == null && max == null) return "";
  if (min != null && max != null) {
    return min === max ? `约 ${min} 元` : `${min}-${max} 元`;
  }
  if (min != null) return `约 ${min} 元起`;
  return `约 ${max} 元`;
}

function buildVisiblePages(page: number, totalPages: number) {
  if (totalPages <= 5) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }
  if (page <= 3) {
    return [1, 2, 3, 4, 5];
  }
  if (page >= totalPages - 2) {
    return [totalPages - 4, totalPages - 3, totalPages - 2, totalPages - 1, totalPages];
  }
  return [page - 2, page - 1, page, page + 1, page + 2];
}
