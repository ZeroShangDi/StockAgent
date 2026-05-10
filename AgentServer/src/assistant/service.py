"""
智能工作台服务。

第一版目标：
- 提供聊天会话持久化
- 提供只读分析工具的安全执行入口
- 生成可预览的 HTML artifact

当前安全边界：
- 只开放声明式、只读工具
- 不允许模型直接执行任意代码
- HTML 产物由服务端模板渲染，并做基础清洗
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from jinja2 import Template

from core.managers import llm_manager, mongo_manager


@dataclass
class AssistantPlan:
    intent: str = "general_chat"
    should_generate_html: bool = False
    artifact_title: str = ""
    window_days: int = 30
    min_return_pct: float = 20.0
    bucket_step_pct: float = 20.0


class AssistantService:
    CONVERSATION_COLLECTION = "assistant_conversations"
    ARTIFACT_COLLECTION = "assistant_artifacts"
    MAX_CONTEXT_MESSAGES = 8
    LLM_PLAN_TIMEOUT_SECONDS = 8
    LLM_STREAM_TIMEOUT_SECONDS = 45
    LLM_ARTIFACT_TIMEOUT_SECONDS = 8

    def __init__(self) -> None:
        self._stock_report_template = Template(
            """
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{{ title }}</title>
    <style>
      :root {
        color-scheme: light;
        --bg: #f4efe4;
        --panel: rgba(255, 252, 245, 0.9);
        --ink: #172030;
        --muted: #5f6b7a;
        --line: rgba(23, 32, 48, 0.12);
        --accent: #ca5d34;
        --accent-soft: rgba(202, 93, 52, 0.14);
        --good: #bf4b30;
        --card-shadow: 0 24px 60px rgba(23, 32, 48, 0.12);
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: "SF Pro Display", "PingFang SC", "Hiragino Sans GB", sans-serif;
        color: var(--ink);
        background:
          radial-gradient(circle at top left, rgba(202, 93, 52, 0.18), transparent 32%),
          linear-gradient(135deg, #f8f4ea 0%, #efe8d8 100%);
      }
      .page {
        max-width: 1120px;
        margin: 0 auto;
        padding: 36px 24px 64px;
      }
      .hero {
        display: grid;
        gap: 18px;
        padding: 32px;
        border: 1px solid var(--line);
        border-radius: 28px;
        background: linear-gradient(145deg, rgba(255,255,255,0.82), rgba(255,248,239,0.92));
        box-shadow: var(--card-shadow);
      }
      .eyebrow {
        margin: 0;
        font-size: 12px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--accent);
      }
      h1 {
        margin: 0;
        font-size: 36px;
        line-height: 1.08;
      }
      .subtitle {
        margin: 0;
        font-size: 16px;
        color: var(--muted);
        line-height: 1.7;
      }
      .hero-grid,
      .bucket-grid {
        display: grid;
        gap: 16px;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      }
      .metric,
      .bucket-card,
      .section {
        border: 1px solid var(--line);
        background: var(--panel);
        border-radius: 22px;
        padding: 20px;
        backdrop-filter: blur(12px);
      }
      .metric-label,
      .bucket-label {
        color: var(--muted);
        font-size: 13px;
      }
      .metric-value,
      .bucket-value {
        margin-top: 8px;
        font-size: 28px;
        font-weight: 700;
      }
      .section {
        margin-top: 18px;
      }
      .section h2 {
        margin: 0 0 14px;
        font-size: 20px;
      }
      .highlights {
        margin: 0;
        padding-left: 18px;
        color: var(--ink);
        line-height: 1.8;
      }
      table {
        width: 100%;
        border-collapse: collapse;
      }
      th, td {
        text-align: left;
        padding: 12px 10px;
        border-bottom: 1px solid var(--line);
        font-size: 14px;
      }
      th {
        color: var(--muted);
        font-weight: 600;
      }
      .tag {
        display: inline-flex;
        align-items: center;
        padding: 4px 10px;
        border-radius: 999px;
        background: var(--accent-soft);
        color: var(--accent);
        font-size: 12px;
        font-weight: 600;
      }
      .footnote {
        margin-top: 18px;
        color: var(--muted);
        font-size: 13px;
      }
      @media (max-width: 720px) {
        .page { padding: 20px 14px 40px; }
        .hero { padding: 22px; border-radius: 22px; }
        h1 { font-size: 28px; }
      }
    </style>
  </head>
  <body>
    <main class="page">
      <section class="hero">
        <div>
          <p class="eyebrow">StockAgent Workspace</p>
          <h1>{{ title }}</h1>
          <p class="subtitle">{{ summary }}</p>
        </div>
        <div class="hero-grid">
          <article class="metric">
            <div class="metric-label">统计窗口</div>
            <div class="metric-value">{{ context.window_days }} 天</div>
          </article>
          <article class="metric">
            <div class="metric-label">最新交易日</div>
            <div class="metric-value">{{ result.latest_trade_date }}</div>
          </article>
          <article class="metric">
            <div class="metric-label">纳入比较股票数</div>
            <div class="metric-value">{{ result.qualified_count }}</div>
          </article>
          <article class="metric">
            <div class="metric-label">最高区间涨幅</div>
            <div class="metric-value">{{ result.max_return_pct }}%</div>
          </article>
        </div>
      </section>

      <section class="section">
        <h2>分层统计</h2>
        <div class="bucket-grid">
          {% for bucket in result.buckets %}
          <article class="bucket-card">
            <div class="bucket-label">{{ bucket.label }}</div>
            <div class="bucket-value">{{ bucket.count }}</div>
            <div class="tag">占比 {{ bucket.share_pct }}%</div>
          </article>
          {% endfor %}
        </div>
      </section>

      <section class="section">
        <h2>模型观察</h2>
        <ul class="highlights">
          {% for item in highlights %}
          <li>{{ item }}</li>
          {% endfor %}
        </ul>
      </section>

      <section class="section">
        <h2>分层明细</h2>
        {% for bucket in result.bucket_details %}
        <div style="margin-bottom: 22px;">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px;">
            <strong>{{ bucket.label }}</strong>
            <span class="tag">{{ bucket.count }} 只 / {{ bucket.share_pct }}%</span>
          </div>
          <table>
            <thead>
              <tr>
                <th>名称</th>
                <th>代码</th>
                <th>近30天涨幅</th>
              </tr>
            </thead>
            <tbody>
              {% for row in bucket.stocks %}
              <tr>
                <td>{{ row.name }}</td>
                <td>{{ row.ts_code }}</td>
                <td>{{ row.return_pct }}%</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
        {% endfor %}
        <div class="footnote">
          说明：该页面由安全工作台生成。模型只拿到受控的只读结果数据，实际 HTML 由服务端模板渲染。
        </div>
      </section>
    </main>
  </body>
</html>
"""
        )
        self._generic_template = Template(
            """
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{{ title }}</title>
    <style>
      :root {
        --bg: #fbf8f1;
        --panel: #fffdf8;
        --ink: #152032;
        --muted: #657285;
        --line: rgba(21, 32, 50, 0.1);
        --accent: #1d7a63;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        background:
          radial-gradient(circle at top right, rgba(29, 122, 99, 0.18), transparent 28%),
          linear-gradient(180deg, #fffdf7 0%, #f5efe2 100%);
        color: var(--ink);
        font-family: "SF Pro Display", "PingFang SC", "Hiragino Sans GB", sans-serif;
      }
      .page {
        max-width: 980px;
        margin: 0 auto;
        padding: 36px 24px 56px;
      }
      .panel {
        border-radius: 30px;
        border: 1px solid var(--line);
        background: var(--panel);
        box-shadow: 0 20px 60px rgba(21, 32, 50, 0.08);
        overflow: hidden;
      }
      .hero {
        padding: 30px;
        background: linear-gradient(145deg, rgba(29, 122, 99, 0.08), rgba(255,255,255,0.8));
      }
      .eyebrow {
        margin: 0 0 10px;
        font-size: 12px;
        color: var(--accent);
        letter-spacing: 0.18em;
        text-transform: uppercase;
      }
      h1 {
        margin: 0 0 10px;
        font-size: 34px;
      }
      .summary {
        margin: 0;
        color: var(--muted);
        line-height: 1.8;
      }
      .section {
        padding: 24px 30px;
        border-top: 1px solid var(--line);
      }
      .section h2 {
        margin: 0 0 12px;
        font-size: 19px;
      }
      .section p {
        margin: 0;
        line-height: 1.8;
        color: var(--ink);
      }
      .section ul {
        margin: 0;
        padding-left: 18px;
        line-height: 1.9;
      }
    </style>
  </head>
  <body>
    <main class="page">
      <article class="panel">
        <section class="hero">
          <p class="eyebrow">StockAgent Workspace</p>
          <h1>{{ title }}</h1>
          <p class="summary">{{ summary }}</p>
        </section>
        {% for section in sections %}
        <section class="section">
          <h2>{{ section.heading }}</h2>
          {% if section.paragraph %}
          <p>{{ section.paragraph }}</p>
          {% endif %}
          {% if section.bullets %}
          <ul>
            {% for bullet in section.bullets %}
            <li>{{ bullet }}</li>
            {% endfor %}
          </ul>
          {% endif %}
        </section>
        {% endfor %}
      </article>
    </main>
  </body>
</html>
"""
        )

    async def create_conversation(self, user_id: str, title: Optional[str] = None) -> Dict[str, Any]:
        conversation_id = uuid.uuid4().hex
        now = datetime.now(UTC)
        doc = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "title": (title or "新对话").strip()[:80],
            "messages": [],
            "latest_artifact_id": None,
            "created_at": now,
            "updated_at": now,
            "last_message_at": None,
        }
        await mongo_manager.update_one(
            self.CONVERSATION_COLLECTION,
            {"conversation_id": conversation_id},
            {"$set": doc},
            upsert=True,
        )
        return self._serialize_conversation_summary(doc)

    async def list_conversations(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        docs = await mongo_manager.find_many(
            self.CONVERSATION_COLLECTION,
            {"user_id": user_id},
            sort=[("updated_at", -1)],
            limit=limit,
        )
        return [self._serialize_conversation_summary(doc) for doc in docs]

    async def get_conversation(self, user_id: str, conversation_id: str) -> Dict[str, Any]:
        doc = await self._require_conversation(user_id, conversation_id)
        artifacts = await mongo_manager.find_many(
            self.ARTIFACT_COLLECTION,
            {"conversation_id": conversation_id, "user_id": user_id},
            sort=[("created_at", -1)],
            limit=10,
        )
        return {
            **self._serialize_conversation_summary(doc),
            "messages": [self._serialize_message(item) for item in doc.get("messages", [])],
            "artifacts": [self._serialize_artifact_meta(item) for item in artifacts],
        }

    async def get_artifact(self, user_id: str, artifact_id: str) -> Optional[Dict[str, Any]]:
        doc = await mongo_manager.find_one(
            self.ARTIFACT_COLLECTION,
            {"artifact_id": artifact_id, "user_id": user_id},
        )
        if not doc:
            return None
        return {
            **self._serialize_artifact_meta(doc),
            "html": doc.get("html", ""),
        }

    async def stream_message(
        self,
        user_id: str,
        conversation_id: str,
        content: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        conversation = await self._require_conversation(user_id, conversation_id)
        user_message = await self._append_message(
            conversation,
            role="user",
            content=content,
        )
        yield {
            "type": "message_ack",
            "conversation_id": conversation_id,
            "message": self._serialize_message(user_message),
        }

        yield {"type": "status", "phase": "planning", "label": "正在规划安全执行路径"}
        plan = await self._plan_request(content)

        tool_result: Optional[Dict[str, Any]] = None
        if plan.intent == "stock_return_buckets":
            try:
                yield {"type": "status", "phase": "tool", "label": "正在执行只读股票筛选工具"}
                tool_result = await self._run_stock_return_buckets(plan)
                yield {
                    "type": "tool_result",
                    "tool_name": "stock_return_buckets",
                    "summary": {
                        "latest_trade_date": tool_result.get("latest_trade_date"),
                        "qualified_count": tool_result.get("qualified_count"),
                        "max_return_pct": tool_result.get("max_return_pct"),
                    },
                }
            except Exception as exc:
                yield {
                    "type": "tool_error",
                    "tool_name": "stock_return_buckets",
                    "detail": str(exc),
                }
                assistant_text = (
                    "这次筛选任务在数据统计阶段失败了，已中止本轮工具执行。"
                    f"错误信息：{exc}"
                )
                refreshed = await self._require_conversation(user_id, conversation_id)
                assistant_message = await self._append_message(
                    refreshed,
                    role="assistant",
                    content=assistant_text,
                    artifacts=[],
                )
                yield {
                    "type": "done",
                    "conversation_id": conversation_id,
                    "message": self._serialize_message(assistant_message),
                }
                return

        yield {"type": "status", "phase": "answer", "label": "正在生成模型回复"}
        assistant_chunks: List[str] = []
        preface = self._build_preface(plan, tool_result)
        if preface:
            assistant_chunks.append(preface)
            yield {"type": "assistant_delta", "content": preface}
        if plan.intent == "stock_return_buckets" and tool_result:
            deterministic = self._build_stock_return_markdown(plan, tool_result)
            assistant_chunks.append(deterministic)
            yield {"type": "assistant_delta", "content": deterministic}
        else:
            try:
                await self._ensure_llm()
                async with asyncio.timeout(self.LLM_STREAM_TIMEOUT_SECONDS):
                    async for chunk in llm_manager.chat_stream(
                        self._build_chat_messages(conversation, content, plan, tool_result),
                        temperature=0.3,
                        max_tokens=1200,
                    ):
                        if not chunk:
                            continue
                        assistant_chunks.append(chunk)
                        yield {"type": "assistant_delta", "content": chunk}
            except Exception as exc:
                fallback = self._build_fallback_reply(plan, tool_result, exc)
                assistant_chunks.append(fallback)
                yield {"type": "assistant_delta", "content": fallback}

        assistant_text = "".join(assistant_chunks).strip()
        artifact_doc: Optional[Dict[str, Any]] = None

        if plan.should_generate_html:
            yield {"type": "status", "phase": "artifact", "label": "正在生成安全 HTML 预览"}
            artifact_doc = await self._create_artifact(
                user_id=user_id,
                conversation_id=conversation_id,
                prompt=content,
                plan=plan,
                tool_result=tool_result,
                assistant_text=assistant_text,
            )
            if artifact_doc:
                yield {
                    "type": "artifact",
                    "artifact": {
                        **self._serialize_artifact_meta(artifact_doc),
                        "html": artifact_doc.get("html", ""),
                    },
                }

        refreshed = await self._require_conversation(user_id, conversation_id)
        assistant_message = await self._append_message(
            refreshed,
            role="assistant",
            content=assistant_text,
            artifacts=[self._serialize_artifact_meta(artifact_doc)] if artifact_doc else [],
        )
        yield {
            "type": "done",
            "conversation_id": conversation_id,
            "message": self._serialize_message(assistant_message),
        }

    async def _append_message(
        self,
        conversation: Dict[str, Any],
        role: str,
        content: str,
        artifacts: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        message = {
            "message_id": uuid.uuid4().hex,
            "role": role,
            "content": content.strip(),
            "artifacts": artifacts or [],
            "created_at": datetime.now(UTC),
        }
        messages = list(conversation.get("messages", []))
        messages.append(message)
        title = conversation.get("title") or "新对话"
        if role == "user" and (not title or title == "新对话"):
            title = self._build_title_from_prompt(content)
        await mongo_manager.update_one(
            self.CONVERSATION_COLLECTION,
            {"conversation_id": conversation["conversation_id"]},
            {
                "$set": {
                    "messages": messages,
                    "title": title,
                    "last_message_at": message["created_at"],
                    "latest_artifact_id": (artifacts or [{}])[0].get("artifact_id") if artifacts else conversation.get("latest_artifact_id"),
                }
            },
        )
        return message

    async def _create_artifact(
        self,
        user_id: str,
        conversation_id: str,
        prompt: str,
        plan: AssistantPlan,
        tool_result: Optional[Dict[str, Any]],
        assistant_text: str,
    ) -> Optional[Dict[str, Any]]:
        artifact_id = uuid.uuid4().hex
        spec = await self._build_artifact_spec(prompt, plan, tool_result, assistant_text)

        if plan.intent == "stock_return_buckets" and tool_result:
            html = self._stock_report_template.render(
                title=spec.get("title") or plan.artifact_title or "涨幅分层统计",
                summary=spec.get("summary") or assistant_text[:180],
                highlights=spec.get("highlights") or [],
                result=tool_result,
                context={
                    "window_days": plan.window_days,
                    "min_return_pct": plan.min_return_pct,
                    "bucket_step_pct": plan.bucket_step_pct,
                },
            )
        else:
            html = self._generic_template.render(
                title=spec.get("title") or plan.artifact_title or "智能工作台结果",
                summary=spec.get("summary") or assistant_text[:180],
                sections=spec.get("sections") or [
                    {
                        "heading": "模型回复",
                        "paragraph": assistant_text,
                        "bullets": [],
                    }
                ],
            )

        sanitized_html = self._sanitize_html(html)
        doc = {
            "artifact_id": artifact_id,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "title": (spec.get("title") or plan.artifact_title or "HTML 结果").strip()[:120],
            "artifact_type": "html",
            "intent": plan.intent,
            "html": sanitized_html,
            "prompt_excerpt": prompt.strip()[:240],
            "meta": {
                "tool_result_summary": {
                    "qualified_count": tool_result.get("qualified_count"),
                    "latest_trade_date": tool_result.get("latest_trade_date"),
                } if tool_result else None,
            },
            "created_at": datetime.now(UTC),
        }
        await mongo_manager.update_one(
            self.ARTIFACT_COLLECTION,
            {"artifact_id": artifact_id},
            {"$set": doc},
            upsert=True,
        )
        await mongo_manager.update_one(
            self.CONVERSATION_COLLECTION,
            {"conversation_id": conversation_id},
            {"$set": {"latest_artifact_id": artifact_id}},
        )
        return doc

    async def _build_artifact_spec(
        self,
        prompt: str,
        plan: AssistantPlan,
        tool_result: Optional[Dict[str, Any]],
        assistant_text: str,
    ) -> Dict[str, Any]:
        default_spec = {
            "title": plan.artifact_title or "智能工作台结果",
            "summary": assistant_text[:180],
            "highlights": [],
            "sections": [
                {
                    "heading": "任务说明",
                    "paragraph": prompt.strip(),
                    "bullets": [],
                },
                {
                    "heading": "模型结论",
                    "paragraph": assistant_text.strip(),
                    "bullets": [],
                },
            ],
        }
        if plan.intent == "stock_return_buckets" and tool_result:
            default_spec["highlights"] = self._build_bucket_highlights(plan, tool_result)
            return default_spec
        try:
            await self._ensure_llm()
            payload = {
                "prompt": prompt,
                "intent": plan.intent,
                "assistant_text": assistant_text,
                "tool_result": tool_result,
            }
            async with asyncio.timeout(self.LLM_ARTIFACT_TIMEOUT_SECONDS):
                raw = await llm_manager.chat(
                    [
                        {
                            "role": "system",
                            "content": (
                                "你是一个安全 HTML 页面策划器。"
                                "请根据输入返回 JSON，不要输出 Markdown 代码块。"
                                "字段：title, summary, highlights, sections。"
                                "highlights 为字符串数组；sections 为对象数组，每个对象含 heading, paragraph, bullets。"
                                "所有内容都用中文，简洁、可信，不要虚构不存在的数据。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(payload, ensure_ascii=False),
                        },
                    ],
                    temperature=0.2,
                    max_tokens=900,
                )
            parsed = self._extract_json_object(raw)
            if isinstance(parsed, dict):
                default_spec.update(parsed)
        except Exception:
            pass
        return default_spec

    async def _plan_request(self, prompt: str) -> AssistantPlan:
        normalized = prompt.strip()
        should_generate_html = any(token in normalized.lower() for token in ["html", "页面", "热力图", "图表", "预览"])

        bucket_match = (
            ("涨幅" in normalized or "涨跌幅" in normalized)
            and ("统计" in normalized or "筛选" in normalized)
            and ("股票" in normalized or "个股" in normalized)
        )

        plan = AssistantPlan(
            should_generate_html=should_generate_html,
            artifact_title="智能工作台结果",
        )
        if bucket_match:
            window_days = self._extract_int(normalized, r"近(\d{1,3})天", 30)
            min_return = self._extract_int(normalized, r"超过(\d{1,3})%+", 20)
            step = self._extract_int(normalized, r"按(\d{1,3})%一层", 20)
            plan.intent = "stock_return_buckets"
            plan.should_generate_html = True
            plan.artifact_title = f"近{window_days}天涨幅分层统计"
            plan.window_days = max(5, min(window_days, 240))
            plan.min_return_pct = float(max(5, min(min_return, 200)))
            plan.bucket_step_pct = float(max(5, min(step, 100)))
            return plan

        try:
            await self._ensure_llm()
            async with asyncio.timeout(self.LLM_PLAN_TIMEOUT_SECONDS):
                raw = await llm_manager.chat(
                    [
                        {
                            "role": "system",
                            "content": (
                                "你是一个安全工作台的任务规划器。"
                                "请根据用户请求返回 JSON，不要输出代码块。"
                                "字段：intent, should_generate_html, artifact_title。"
                                "intent 只能是 general_chat 或 stock_return_buckets。"
                                "只有当用户明确提到分层统计近N天股票涨幅时，才选择 stock_return_buckets。"
                            ),
                        },
                        {"role": "user", "content": normalized},
                    ],
                    temperature=0,
                    max_tokens=200,
                )
            parsed = self._extract_json_object(raw)
            if isinstance(parsed, dict):
                plan.intent = parsed.get("intent") or plan.intent
                plan.should_generate_html = bool(parsed.get("should_generate_html", plan.should_generate_html))
                plan.artifact_title = str(parsed.get("artifact_title") or plan.artifact_title)[:80]
        except Exception:
            pass
        return plan

    async def _run_stock_return_buckets(self, plan: AssistantPlan) -> Dict[str, Any]:
        latest_date_docs = await mongo_manager.aggregate(
            "stock_daily",
            [
                {"$group": {"_id": "$trade_date"}},
                {"$sort": {"_id": -1}},
                {"$limit": max(plan.window_days + 5, 60)},
            ],
        )
        trade_dates = [str(item.get("_id")) for item in latest_date_docs if item.get("_id")]
        if not trade_dates:
            return {
                "latest_trade_date": "",
                "qualified_count": 0,
                "max_return_pct": 0,
                "buckets": [],
                "top_stocks": [],
            }

        latest_trade_date = trade_dates[0]
        start_index = min(plan.window_days - 1, len(trade_dates) - 1)
        start_trade_date = trade_dates[start_index]
        baseline_candidate_dates = trade_dates[start_index : min(start_index + 5, len(trade_dates))]

        latest_docs = await mongo_manager.find_many(
            "stock_daily",
            {"trade_date": latest_trade_date},
            projection={"ts_code": 1, "trade_date": 1, "close": 1},
        )
        baseline_raw_docs = await mongo_manager.find_many(
            "stock_daily",
            {"trade_date": {"$in": baseline_candidate_dates}},
            projection={"ts_code": 1, "trade_date": 1, "close": 1},
            sort=[("ts_code", 1), ("trade_date", -1)],
        )

        baseline_map: Dict[str, Dict[str, Any]] = {}
        for doc in baseline_raw_docs:
            ts_code = str(doc.get("ts_code") or "").upper()
            if not ts_code or ts_code in baseline_map:
                continue
            baseline_map[ts_code] = doc

        latest_map = {
            str(doc.get("ts_code") or "").upper(): doc
            for doc in latest_docs
            if doc.get("ts_code") and doc.get("close")
        }

        result_rows: List[Dict[str, Any]] = []
        for ts_code, latest in latest_map.items():
            baseline = baseline_map.get(ts_code)
            if not baseline:
                continue
            start_close = float(baseline.get("close") or 0)
            latest_close = float(latest.get("close") or 0)
            if start_close <= 0 or latest_close <= 0:
                continue
            return_pct = round((latest_close / start_close - 1) * 100, 2)
            if return_pct < plan.min_return_pct:
                continue
            result_rows.append(
                {
                    "ts_code": ts_code,
                    "start_trade_date": str(baseline.get("trade_date") or ""),
                    "latest_trade_date": str(latest.get("trade_date") or latest_trade_date),
                    "start_close": round(start_close, 3),
                    "latest_close": round(latest_close, 3),
                    "return_pct": return_pct,
                }
            )

        result_rows.sort(key=lambda item: item["return_pct"], reverse=True)
        names = await self._load_stock_names([item["ts_code"] for item in result_rows])
        for row in result_rows:
            row["name"] = names.get(row["ts_code"], row["ts_code"])

        qualified_count = len(result_rows)
        max_return_pct = round(max((item["return_pct"] for item in result_rows), default=0), 2)
        buckets: List[Dict[str, Any]] = []
        bucket_details: List[Dict[str, Any]] = []
        bucket_ranges = [
            (20.0, 40.0, "20%-40%"),
            (40.0, 60.0, "40%-60%"),
            (60.0, 80.0, "60%-80%"),
            (80.0, 100.0, "80%-100%"),
            (100.0, None, "100%+"),
        ]
        for lower, upper, label in bucket_ranges:
            if upper is None:
                bucket_stocks = [item for item in result_rows if item["return_pct"] >= lower]
            else:
                bucket_stocks = [item for item in result_rows if lower <= item["return_pct"] < upper]
            count = len(bucket_stocks)
            share_pct = round((count / qualified_count) * 100, 2) if qualified_count else 0
            buckets.append(
                {
                    "label": label,
                    "count": count,
                    "share_pct": share_pct,
                }
            )
            bucket_details.append(
                {
                    "label": label,
                    "count": count,
                    "share_pct": share_pct,
                    "stocks": [
                        {
                            "name": item["name"],
                            "ts_code": item["ts_code"],
                            "return_pct": item["return_pct"],
                        }
                        for item in bucket_stocks
                    ],
                }
            )

        top_stocks = result_rows[:20]
        return {
            "latest_trade_date": latest_trade_date,
            "start_trade_date": start_trade_date,
            "qualified_count": qualified_count,
            "max_return_pct": max_return_pct,
            "buckets": buckets,
            "bucket_details": bucket_details,
            "top_stocks": top_stocks,
        }

    async def _load_stock_names(self, ts_codes: List[str]) -> Dict[str, str]:
        unique_codes = list(sorted({str(code or "").upper() for code in ts_codes if str(code or "").strip()}))
        if not unique_codes:
            return {}
        docs = await mongo_manager.find_many(
            "stock_basic",
            {"ts_code": {"$in": unique_codes}},
            projection={"ts_code": 1, "name": 1},
        )
        return {
            str(doc.get("ts_code") or "").upper(): str(doc.get("name") or "").strip()
            for doc in docs
            if doc.get("ts_code")
        }

    def _build_chat_messages(
        self,
        conversation: Dict[str, Any],
        latest_prompt: str,
        plan: AssistantPlan,
        tool_result: Optional[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        history = conversation.get("messages", [])[-self.MAX_CONTEXT_MESSAGES :]
        messages: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "你是 StockAgent 的智能工作台助手。"
                    "你的职责是帮助用户理解股票数据、复盘数据和系统能力。"
                    "当前环境强调安全：不要声称自己执行了未被明确提供的数据写入、联网或任意代码执行。"
                    "如果有工具结果，请基于真实结果给出简洁、可信、偏交易研究风格的回答。"
                    "如果任务超出当前安全沙箱能力，要明确说明目前边界，并给出下一步建议。"
                ),
            }
        ]
        if tool_result:
            messages.append(
                {
                    "role": "system",
                    "content": "以下是本轮只读工具返回的结构化结果，请基于这些真实数据作答：" + json.dumps(tool_result, ensure_ascii=False),
                }
            )
        messages.extend(
            {
                "role": item.get("role", "user"),
                "content": str(item.get("content") or ""),
            }
            for item in history
            if item.get("content")
        )
        messages.append({"role": "user", "content": latest_prompt})
        return messages

    def _build_fallback_reply(
        self,
        plan: AssistantPlan,
        tool_result: Optional[Dict[str, Any]],
        exc: Exception,
    ) -> str:
        if plan.intent == "stock_return_buckets" and tool_result:
            return (
                f"本轮我已经完成了近 {plan.window_days} 天涨幅分层统计，但模型总结阶段失败。"
                f"当前纳入比较的股票有 {tool_result.get('qualified_count', 0)} 只，"
                f"最新交易日为 {tool_result.get('latest_trade_date', '-')}"
                f"。你仍然可以在右侧查看生成的 HTML 结果。"
            )
        return f"本轮模型响应失败：{exc}。第一版工作台仍然保留了安全边界，没有执行任何越权动作。"

    def _build_preface(
        self,
        plan: AssistantPlan,
        tool_result: Optional[Dict[str, Any]],
    ) -> str:
        if plan.intent == "stock_return_buckets" and tool_result:
            return (
                f"已完成第一步筛选：以 {tool_result.get('latest_trade_date') or '-'} 为最新交易日，"
                f"近 {plan.window_days} 天内共有 {tool_result.get('qualified_count', 0)} 只股票满足"
                f"涨幅超过 {int(plan.min_return_pct)}% 的条件。\n\n"
            )
        return ""

    def _build_bucket_highlights(
        self,
        plan: AssistantPlan,
        tool_result: Dict[str, Any],
    ) -> List[str]:
        buckets = tool_result.get("buckets") or []
        top_bucket = max(buckets, key=lambda item: item.get("count", 0), default=None)
        highlights = [
            f"统计窗口为近 {plan.window_days} 天，阈值从 {int(plan.min_return_pct)}% 起按 {int(plan.bucket_step_pct)}% 分层。",
            f"本轮共有 {tool_result.get('qualified_count', 0)} 只股票进入统计，最高区间涨幅达到 {tool_result.get('max_return_pct', 0)}%。",
        ]
        if top_bucket:
            highlights.append(
                f"数量最多的区间为 {top_bucket.get('label')}，共有 {top_bucket.get('count', 0)} 只，占比 {top_bucket.get('share_pct', 0)}%。"
            )
        return highlights

    def _build_stock_return_markdown(
        self,
        plan: AssistantPlan,
        tool_result: Dict[str, Any],
    ) -> str:
        bucket_lines = [
            f"- `{bucket.get('label')}`: {bucket.get('count', 0)} 只，占比 {bucket.get('share_pct', 0)}%"
            for bucket in (tool_result.get("buckets") or [])
        ]
        return (
            "右侧已经生成完整 HTML 结果页，按固定分层表格展示了全部股票明细。\n\n"
            f"- 统计窗口：近 {plan.window_days} 天\n"
            f"- 最新交易日：`{tool_result.get('latest_trade_date', '-')}`\n"
            f"- 满足条件股票数：`{tool_result.get('qualified_count', 0)}`\n"
            f"- 最高区间涨幅：`{tool_result.get('max_return_pct', 0)}%`\n\n"
            "**分层汇总**\n"
            + "\n".join(bucket_lines)
            + "\n\n"
            "右侧每个阶段的表格都包含：`名称`、`代码`、`近30天涨幅`。"
        )

    async def _require_conversation(self, user_id: str, conversation_id: str) -> Dict[str, Any]:
        doc = await mongo_manager.find_one(
            self.CONVERSATION_COLLECTION,
            {"conversation_id": conversation_id, "user_id": user_id},
        )
        if not doc:
            raise ValueError("Conversation not found")
        return doc

    async def _ensure_llm(self) -> None:
        if not llm_manager.is_initialized:
            await llm_manager.initialize()

    def _serialize_conversation_summary(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "conversation_id": doc.get("conversation_id"),
            "title": doc.get("title") or "新对话",
            "latest_artifact_id": doc.get("latest_artifact_id"),
            "message_count": len(doc.get("messages", [])),
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
            "last_message_at": doc.get("last_message_at"),
        }

    def _serialize_message(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "message_id": doc.get("message_id"),
            "role": doc.get("role"),
            "content": doc.get("content") or "",
            "artifacts": doc.get("artifacts") or [],
            "created_at": doc.get("created_at"),
        }

    def _serialize_artifact_meta(self, doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not doc:
            return {}
        return {
            "artifact_id": doc.get("artifact_id"),
            "title": doc.get("title"),
            "artifact_type": doc.get("artifact_type") or "html",
            "intent": doc.get("intent"),
            "created_at": doc.get("created_at"),
        }

    def _build_title_from_prompt(self, prompt: str) -> str:
        compact = re.sub(r"\s+", " ", prompt.strip())
        return compact[:30] or "新对话"

    def _extract_int(self, text: str, pattern: str, default: int) -> int:
        matched = re.search(pattern, text)
        if not matched:
            return default
        try:
            return int(matched.group(1))
        except ValueError:
            return default

    def _extract_json_object(self, text: str) -> Dict[str, Any]:
        content = str(text or "").strip()
        code_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, flags=re.S)
        if code_match:
            content = code_match.group(1)
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            content = content[start : end + 1]
        return json.loads(content)

    def _sanitize_html(self, html: str) -> str:
        sanitized = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
        sanitized = re.sub(r"\son[a-zA-Z]+\s*=\s*(['\"]).*?\1", "", sanitized, flags=re.I | re.S)
        sanitized = sanitized.replace("javascript:", "")
        sanitized = sanitized.replace("<iframe", "&lt;iframe")
        return sanitized


assistant_service = AssistantService()
