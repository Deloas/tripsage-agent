import { FormEvent, useState } from "react";
import { CloudDownload, X } from "lucide-react";

interface AddGuideModalProps {
  open: boolean;
  loading: boolean;
  crawlLoading: boolean;
  result: string | null;
  onClose: () => void;
  onSubmit: (payload: { title: string; content: string; source_url?: string }) => Promise<void>;
  onCrawlWeibo: () => Promise<void>;
}

export function AddGuideModal({
  open,
  loading,
  crawlLoading,
  result,
  onClose,
  onSubmit,
  onCrawlWeibo,
}: AddGuideModalProps) {
  const [title, setTitle] = useState("苏州两天一夜补充攻略");
  const [sourceUrl, setSourceUrl] = useState("");
  const [content, setContent] = useState(
    "苏州两天一夜可以第一天去拙政园、苏州博物馆和平江路，晚上吃苏帮菜。第二天去虎丘或留园，再到山塘街。雨天可以增加博物馆、评弹茶馆和室内餐饮时间。",
  );
  const canSubmit = title.trim().length >= 2 && content.trim().length >= 20 && !loading;

  if (!open) return null;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    // 前端先做最小校验，后端仍负责最终入库校验与切片。
    if (!canSubmit) return;
    await onSubmit({ title, content, source_url: sourceUrl || undefined });
  }

  return (
    <div className="modal-backdrop">
      <section className="guide-modal" role="dialog" aria-modal="true" aria-label="添加攻略">
        <div className="modal-header">
          <div>
            <div className="section-kicker">攻略入库</div>
            <h2>添加一份新的旅行经验</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="关闭">
            <X size={18} />
          </button>
        </div>
        <div className="crawl-strip">
          <div>
            <strong>微博公开攻略合集</strong>
            <span>只抓取公开可访问内容，抓不到正文的链接会保存为待处理来源。</span>
          </div>
          <button className="secondary-action" onClick={onCrawlWeibo} disabled={crawlLoading}>
            <CloudDownload size={16} />
            {crawlLoading ? "采集中" : "采集微博"}
          </button>
        </div>
        <form onSubmit={handleSubmit} className="guide-form">
          <label>
            <span>标题</span>
            <input value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label>
            <span>来源链接</span>
            <input value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} />
          </label>
          <label>
            <span>正文</span>
            <textarea value={content} onChange={(event) => setContent(event.target.value)} rows={8} />
          </label>
          {result && <div className="modal-result">{result}</div>}
          <button className="primary-action wide" disabled={!canSubmit}>
            {loading ? "入库中" : "确认入库"}
          </button>
        </form>
      </section>
    </div>
  );
}
