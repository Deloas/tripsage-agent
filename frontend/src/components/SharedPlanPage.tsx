import { ArrowLeft, CalendarDays, DatabaseZap, Link2, TrainFront } from "lucide-react";
import { useEffect, useState } from "react";

import { fetchSharedPlan } from "../lib/api";
import type { SharedPlan } from "../lib/types";

export function SharedPlanPage({ shareId }: { shareId: string }) {
  const [plan, setPlan] = useState<SharedPlan | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    // 分享页只读取本地后端的只读方案，不触发智能体和外部工具。
    fetchSharedPlan(shareId)
      .then(setPlan)
      .catch(() => setError("分享方案不存在或后端未启动。"));
  }, [shareId]);

  if (error) {
    return (
      <main className="share-page">
        <section className="share-empty">{error}</section>
      </main>
    );
  }

  if (!plan) {
    return (
      <main className="share-page">
        <section className="share-empty">正在读取分享方案...</section>
      </main>
    );
  }

  const response = plan.response;
  const itinerary = response.itinerary || [];

  return (
    <main className="share-page">
      <a className="share-back" href="/">
        <ArrowLeft size={16} />
        返回工作台
      </a>
      <section className="share-hero">
        <div>
          <span>TripSage Shared Plan</span>
          <h1>{plan.title}</h1>
          <p>{response.answer}</p>
        </div>
        <div className="share-hero-stats">
          <div>
            <CalendarDays size={17} />
            <strong>{itinerary.length || 0}</strong>
            <span>行程天数</span>
          </div>
          <div>
            <TrainFront size={17} />
            <strong>{response.tool_calls.length}</strong>
            <span>工具调用</span>
          </div>
          <div>
            <DatabaseZap size={17} />
            <strong>{response.sources.length}</strong>
            <span>引用来源</span>
          </div>
        </div>
      </section>

      {itinerary.length ? (
        <section className="share-section">
          <div className="section-kicker">行程安排</div>
          <div className="share-itinerary">
            {itinerary.map((day) => (
              <article key={day.day}>
                <span>DAY {day.day}</span>
                <h2>{day.title}</h2>
                {day.items.map((item, index) => (
                  <div className="share-item" key={`${day.day}-${index}`}>
                    <strong>{item.time}</strong>
                    <div>
                      <b>{item.title}</b>
                      <p>{item.detail}</p>
                    </div>
                  </div>
                ))}
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {response.decision_modules.length ? (
        <section className="share-section">
          <div className="section-kicker">决策提示</div>
          <div className="share-modules">
            {response.decision_modules.map((module) => (
              <article key={`${module.type}-${module.title}`}>
                <strong>{module.title}</strong>
                <p>{module.summary}</p>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      <section className="share-section">
        <div className="section-kicker">
          <Link2 size={15} />
          引用来源
        </div>
        <div className="share-sources">
          {response.sources.map((source) => (
            <a href={source.url || "#"} target="_blank" rel="noreferrer" key={`${source.title}-${source.url}`}>
              {source.title}
            </a>
          ))}
          {!response.sources.length ? <span>暂无引用来源</span> : null}
        </div>
      </section>
    </main>
  );
}
