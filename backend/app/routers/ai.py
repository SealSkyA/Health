"""AI 能力 REST API：
- POST /ai/analyze-report   报告 AI 分析（整检查记录 / 单份报告），结果落库
- POST /ai/analyze-report-stream  同上，但流式（SSE）返回生成过程，前端实时可见
- GET  /ai/analyses          分析历史
- DELETE /ai/analyses/{id}   删除一条分析
- GET  /ai/skills            已安装技能列表（SKILL.md 目录）
- POST /ai/skills/install    上传安装技能（SKILL.md）
- POST /ai/agent-chat        AI 问数助手（function calling，写操作进入待确认；支持思考深度/技能）
- POST /ai/agent-compact     上下文压缩（生成历史摘要）
- POST /ai/agent-execute     确认后执行写操作
"""
import asyncio
import functools
import html as _html
import json
import os
import queue as qmod
import re
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal, get_db
from app.models.ai_agent_tasks import AiAgentTask
from app.models.ai_analyses import AiAnalysis
from app.models.ai_models import AiModel
from app.models.ai_sessions import AiChatSession
from app.models.med_records import MedicationItem, Prescription
from app.models.reports import Report, ReportDoc
from app.models.user import User
from app.routers.auth import _get_user_by_token, _token_from, user_has_perm
from app.services.llm import AgentCancelled, RETRY_WAITS, call_chat, call_chat_stream, tool_result_message

import logging
logger = logging.getLogger("3healthtrends.ai.task")

router = APIRouter()


# ---------- 数据隔离 helper（admin 全量；普通用户仅本人数据，存量 NULL 归 admin） ----------
def _sc_report(user: User):
    return None if user.role == "admin" else Report.user_id == user.id


def _sc_rx(user: User):
    return None if user.role == "admin" else Prescription.user_id == user.id


def _sc_analysis(user: User):
    return None if user.role == "admin" else AiAnalysis.user_id == user.id


async def _cur_user(request: Request, db: AsyncSession) -> User:
    """从请求解析当前登录用户（AI 各入口鉴权）。"""
    return await _get_user_by_token(db, _token_from(request))

# ---------- 技能（SKILL.md 目录） ----------
SKILLS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "skills"))


def _load_skills() -> dict:
    out = {}
    if not os.path.isdir(SKILLS_DIR):
        return out
    for d in sorted(os.listdir(SKILLS_DIR)):
        f = os.path.join(SKILLS_DIR, d, "SKILL.md")
        if not os.path.isfile(f):
            continue
        try:
            text = open(f, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        name = d
        description = ""
        body = text
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
        if m:
            fm, body = m.group(1), m.group(2)
            for line in fm.splitlines():
                if line.lower().startswith("name:"):
                    name = line.split(":", 1)[1].strip().strip('"\'')
                elif line.lower().startswith("description:"):
                    description = line.split(":", 1)[1].strip().strip('"\'')
        out[name] = {"name": name, "description": description, "prompt": body.strip()}
    return out


SKILLS = _load_skills()


# ---------- 工具 ----------
def _parse_items(items) -> list[dict]:
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except (ValueError, TypeError):
            return []
    out = []
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "ref_range": it.get("ref_range") or "",
            "unit": it.get("unit") or "",
            "value": str(it.get("value") or "").strip() or "",
            "result": _calc_result(str(it.get("value") or ""), it.get("ref_range") or ""),
        })
    return out


def _calc_result(v: str, ref: str) -> str:
    if not v or not ref:
        return ""
    try:
        n = float(v)
    except (ValueError, TypeError):
        return "normal" if (v == ref) else "abnormal"
    if "-" in ref:
        try:
            lo, hi = (float(x.strip()) for x in ref.split("-", 1))
            return "normal" if lo <= n <= hi else ("high" if n > hi else "low")
        except (ValueError, TypeError):
            return ""
    if ref.startswith(("<", ">")):
        try:
            lim = float(ref[1:].strip())
            return "normal" if (("<" in ref and n < lim) or (">" in ref and n > lim)) else "abnormal"
        except (ValueError, TypeError):
            return ""
    return ""


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def _fmt_items(items: list[dict]) -> str:
    if not items:
        return "（无明细）"
    lines = []
    for i, it in enumerate(items, 1):
        flag = {"high": " ↑偏高", "low": " ↓偏低", "abnormal": " ⚠异常"}.get(it.get("result"), "")
        lines.append(f"{i}. {it['name']} {it.get('value') or '—'}{it.get('unit') or ''} "
                     f"(参考 {it.get('ref_range') or '—'}){flag}")
    return "\n".join(lines)


def _fmt_doc(doc: ReportDoc) -> str:
    items = _parse_items(doc.items_json)
    head = f"【报告】{doc.name or '未命名'}（#{doc.id}）"
    note = f"\n备注：{doc.note}" if doc.note else ""
    return head + note + "\n" + _fmt_items(items)


# ---------- Schemas ----------
class AnalyzeIn(BaseModel):
    record_id: int
    doc_id: Optional[int] = None
    alias: str
    model: str
    question: Optional[str] = None


class AnalysisOut(BaseModel):
    id: int
    record_id: int
    doc_id: Optional[int] = None
    alias: str = ""
    model: str = ""
    question: str = ""
    result: str = ""
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


async def _get_model_conf(db, alias: str, model: str) -> AiModel:
    res = await db.execute(select(AiModel).where(
        AiModel.alias == alias, AiModel.name == model, AiModel.enabled == True  # noqa: E712
    ))
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=400, detail="未找到该别名下的可用模型，请先在 AI 配置中启用")
    return obj


def _fmt_record(record: Report, docs: list[ReportDoc]) -> str:
    lines = ["【检查记录】",
             f"类别：{record.category or '—'}｜检查时间：{record.checked_at or '—'}｜机构：{record.addr or '—'}｜负责人：{record.doctor or '—'}"]
    if record.note:
        lines.append(f"备注：{record.note}")
    if not docs:
        lines.append("（该记录下暂无报告）")
    for d in docs:
        lines.append("")
        lines.append(_fmt_doc(d))
    return "\n".join(lines)


async def _prepare_analysis(db, data: AnalyzeIn, user: User = None):
    """加载记录/报告并组装分析提示词，返回 (record, docs, conf, scope, prompt)。

    user 提供数据归属校验：非 admin 只能分析自己创建的检查记录。
    """
    stmt = select(Report).where(Report.id == data.record_id)
    if user is not None:
        _sc = _sc_report(user)
        if _sc is not None:
            stmt = stmt.where(_sc)
    record = (await db.execute(stmt)).scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="检查记录不存在")
    res = await db.execute(select(ReportDoc).where(ReportDoc.report_id == data.record_id).order_by(ReportDoc.id))
    docs = res.scalars().all()
    if data.doc_id:
        docs = [d for d in docs if d.id == data.doc_id]
        if not docs:
            raise HTTPException(status_code=404, detail="报告不存在")
        scope = f"单份报告：{docs[0].name or '未命名'}"
    else:
        scope = f"整条检查记录（{len(docs)} 份报告）"

    conf = await _get_model_conf(db, data.alias, data.model)
    question = (data.question or "").strip()
    q = f"\n用户的补充问题：{question}" if question else ""
    prompt = (
        "你是一位资深的检验医学分析助手。请基于下面的检查报告数据，为用户做通俗、专业的解读：\n"
        "1. 逐项说明关键指标及其临床意义；\n"
        "2. 重点标注异常项（偏高/偏低/异常）并解释可能原因；\n"
        "3. 总结整体健康状况，给出进一步检查或复查的建议；\n"
        "4. 条理清晰、分点输出，专业但不堆砌术语。\n"
        "重要声明：分析仅供参考，不能替代执业医师的诊断。\n\n"
        f"分析范围：{scope}\n"
        "检查数据如下：\n" + _fmt_record(record, docs) + q
    )
    return record, docs, conf, scope, prompt


# ---------- 报告 AI 分析 ----------
@router.post("/ai/analyze-report", response_model=AnalysisOut)
async def analyze_report(data: AnalyzeIn, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _cur_user(request, db)
    record, docs, conf, scope, prompt = await _prepare_analysis(db, data, user)
    messages = [{"role": "user", "content": prompt}]
    msg = call_chat(conf.addr, conf.api_key, conf.name, messages, temperature=0.3, timeout=180)
    result = (msg.get("content") or "（模型未返回内容）").strip()

    obj = AiAnalysis(
        user_id=user.id,
        record_id=data.record_id, doc_id=data.doc_id,
        alias=data.alias, model=data.model,
        question=((data.question or "").strip()) or f"分析{scope}",
        result=result,
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


def _stream_reader(addr: str, api_key: str, model: str, messages: list, q: qmod.Queue, errq: qmod.Queue):
    """线程内流式读取 LLM 输出（含 429 退避重试），逐块放队列。
    队列元素：(kind, value)，kind ∈ {"delta","retry"}，结束放 None。"""
    body = {"model": model, "messages": messages, "temperature": 0.3, "stream": True}
    headers = {"Content-Type": "application/json"}
    if (api_key or "").strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    url = addr.rstrip("/") + "/chat/completions"
    for attempt in range(len(RETRY_WAITS) + 1):
        req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                     headers=headers, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=240)
            for raw in resp:
                for line in raw.decode("utf-8", "replace").split("\n"):
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        q.put(None)
                        return
                    try:
                        obj = json.loads(payload)
                        delta = obj["choices"][0].get("delta") or {}
                    except (KeyError, IndexError, ValueError):
                        delta = {}
                    content = delta.get("content")
                    if content:
                        q.put(("delta", content))
            q.put(None)
            return
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < len(RETRY_WAITS):
                # 向前端推送重试事件，让用户看到"仍在运行"
                q.put(("retry", attempt + 1))
                threading.Event().wait(RETRY_WAITS[attempt])  # 限流退避：3/6/12/24/40/60s
                continue
            errq.put(f"AI 服务返回 {e.code}：{e.read().decode('utf-8', 'replace')[:200]}")
            q.put(None)
            return
        except Exception as ex:
            errq.put(f"AI 服务调用失败：{ex}")
            q.put(None)
            return
    errq.put(f"AI 服务繁忙（限流），已自动重试 {len(RETRY_WAITS)} 次仍失败，请稍后再试")
    q.put(None)


@router.post("/ai/analyze-report-stream")
async def analyze_report_stream(data: AnalyzeIn, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _cur_user(request, db)
    record, docs, conf, scope, prompt = await _prepare_analysis(db, data, user)
    messages = [{"role": "user", "content": prompt}]

    async def gen():
        loop = asyncio.get_running_loop()
        q, errq = qmod.Queue(), qmod.Queue()
        loop.run_in_executor(None, _stream_reader, conf.addr, conf.api_key, conf.name, messages, q, errq)
        full = ""
        while True:
            item = await loop.run_in_executor(None, q.get)
            if item is None:
                break
            kind, val = item
            if kind == "retry":
                yield "data: " + _j({"retry": True, "attempt": val, "message": "AI 服务繁忙，自动重试中…"}) + "\n\n"
                continue
            full += val
            yield "data: " + _j({"delta": val}) + "\n\n"
        if not errq.empty():
            err = errq.get_nowait()
            yield "data: " + _j({"error": err}) + "\n\n"
            return
        # 生成完成，落库
        obj = AiAnalysis(
            user_id=user.id,
            record_id=data.record_id, doc_id=data.doc_id,
            alias=data.alias, model=data.model,
            question=((data.question or "").strip()) or f"分析{scope}",
            result=full.strip() or "（模型未返回内容）",
        )
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        yield "data: " + _j({"done": True, "id": obj.id}) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/ai/analyses", response_model=list[AnalysisOut])
async def list_analyses(
    record_id: int = Query(0),
    doc_id: int = Query(0),
    limit: int = Query(50, ge=1, le=200),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    user = await _cur_user(request, db)
    stmt = select(AiAnalysis).order_by(AiAnalysis.id.desc()).limit(limit)
    _sc = _sc_analysis(user)
    if _sc is not None:
        stmt = stmt.where(_sc)
    if record_id:
        stmt = stmt.where(AiAnalysis.record_id == record_id)
        if doc_id:
            stmt = stmt.where(AiAnalysis.doc_id == doc_id)
    res = await db.execute(stmt)
    return res.scalars().all()


@router.delete("/ai/analyses/{aid}", status_code=204)
async def delete_analysis(aid: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _cur_user(request, db)
    stmt = select(AiAnalysis).where(AiAnalysis.id == aid)
    _sc = _sc_analysis(user)
    if _sc is not None:
        stmt = stmt.where(_sc)
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="分析记录不存在")
    await db.delete(obj)
    await db.commit()


# ---------- AI 问数助手（工具调用） ----------
_READ_TOOLS = [
    {"type": "function", "function": {"name": "list_reports", "description": "查检查记录列表（支持 q 关键字/category 类别）",
        "parameters": {"type": "object", "properties": {
            "q": {"type": "string"}, "category": {"type": "string"},
            "limit": {"type": "integer"}, "offset": {"type": "integer"}}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "get_report", "description": "取某检查记录完整详情（含报告与检验明细）",
        "parameters": {"type": "object", "properties": {"record_id": {"type": "integer"}},
        "required": ["record_id"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "get_doc", "description": "取某份报告详情",
        "parameters": {"type": "object", "properties": {"doc_id": {"type": "integer"}},
        "required": ["doc_id"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "list_prescriptions", "description": "查用药开方列表（q/patient）",
        "parameters": {"type": "object", "properties": {
            "q": {"type": "string"}, "patient": {"type": "string"}, "limit": {"type": "integer"}}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "get_prescription", "description": "取某开方详情（含药品明细）",
        "parameters": {"type": "object", "properties": {"id": {"type": "integer"}},
        "required": ["id"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "stats", "description": "系统概览统计（记录/报告/用药数、分类分布、异常项Top）",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "web_search", "description": "联网搜索（Bing）：需要最新资料、外部信息、实时数据、政策资讯等系统内没有的内容时使用，返回标题/链接/摘要",
        "parameters": {"type": "object", "properties": {
            "q": {"type": "string", "description": "搜索关键词（尽量精确，中文亦可）"},
            "n": {"type": "integer", "description": "返回条数，默认5，最多8"}}, "required": ["q"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "web_fetch", "description": "读取指定网页正文（深入查看网页搜索结果内容时使用，返回纯文本）",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "网页完整 URL"},
            "limit": {"type": "integer", "description": "截取字数，默认3000"}},
        "required": ["url"], "additionalProperties": False}}},
]

_WRITE_TOOLS = [
    {"type": "function", "function": {"name": "create_report", "description": "新增检查记录",
        "parameters": {"type": "object", "properties": {
            "category": {"type": "string"}, "checked_at": {"type": "string", "description": "YYYY-MM-DD"},
            "addr": {"type": "string"}, "doctor": {"type": "string"}, "note": {"type": "string"}}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "update_report", "description": "修改检查记录",
        "parameters": {"type": "object", "properties": {
            "record_id": {"type": "integer"}, "category": {"type": "string"}, "checked_at": {"type": "string"},
            "addr": {"type": "string"}, "doctor": {"type": "string"}, "note": {"type": "string"}},
        "required": ["record_id"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "delete_report", "description": "删除检查记录及其报告",
        "parameters": {"type": "object", "properties": {"record_id": {"type": "integer"}},
        "required": ["record_id"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "create_doc", "description": "在检查记录下新增报告，items=[{name,ref_range,unit,value}]",
        "parameters": {"type": "object", "properties": {
            "record_id": {"type": "integer"}, "name": {"type": "string"},
            "note": {"type": "string"}, "items": {"type": "array"}},
        "required": ["record_id", "name"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "update_doc", "description": "修改报告名称/备注/明细",
        "parameters": {"type": "object", "properties": {
            "doc_id": {"type": "integer"}, "name": {"type": "string"},
            "note": {"type": "string"}, "items": {"type": "array"}},
        "required": ["doc_id"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "delete_doc", "description": "删除一份报告",
        "parameters": {"type": "object", "properties": {"doc_id": {"type": "integer"}},
        "required": ["doc_id"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "create_prescription", "description": "新增用药开方",
        "parameters": {"type": "object", "properties": {
            "patient": {"type": "string"}, "org_dept": {"type": "string"},
            "doctor": {"type": "string"}, "prescribed_at": {"type": "string"}, "note": {"type": "string"}},
        "required": ["patient"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "update_prescription", "description": "修改用药开方",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "integer"}, "patient": {"type": "string"}, "org_dept": {"type": "string"},
            "doctor": {"type": "string"}, "prescribed_at": {"type": "string"}, "note": {"type": "string"}},
        "required": ["id"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "delete_prescription", "description": "删除用药开方",
        "parameters": {"type": "object", "properties": {"id": {"type": "integer"}},
        "required": ["id"], "additionalProperties": False}}},
]

_TOOLS = _READ_TOOLS + _WRITE_TOOLS
_WRITE_NAMES = {t["function"]["name"] for t in _WRITE_TOOLS}

_SYSTEM_PROMPT = (
    "你是「壹健康」系统的数据助手。你可以查询系统里的检查记录、报告、用药记录并回答统计问题。\n"
    "规则：\n"
    "1. 查询数据时优先调用只读工具获取真实数据，不要编造。\n"
    "2. 当用户要求新增/修改/删除数据时，你必须调用对应的写工具，把要执行的内容作为工具参数传入"
    "（写工具不会真正执行，只进入待确认清单）；调用工具后，在回复中向用户说明你打算执行的操作内容，等待用户确认。\n"
    "3. 回答要简洁、分点，涉及医疗内容注明'仅供参考'。\n"
    "4. 禁止在回答中泄露 API Key。"
)


def _dt(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", ""))
    except ValueError:
        return None


async def _h_list_reports(args, db, user=None):
    stmt = select(Report).order_by(Report.id.desc()).limit(min(int(args.get("limit") or 20), 100)).offset(int(args.get("offset") or 0))
    if user is not None:
        _sc = _sc_report(user)
        if _sc is not None:
            stmt = stmt.where(_sc)
    q = (args.get("q") or "").strip()
    cat = (args.get("category") or "").strip()
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Report.addr.like(like) | Report.doctor.like(like) | (Report.note or "").like(like))
    if cat:
        stmt = stmt.where(Report.category == cat)
    res = await db.execute(stmt)
    records = res.scalars().all()
    out = []
    for r in records:
        cnt = await db.scalar(select(func.count()).select_from(ReportDoc).where(ReportDoc.report_id == r.id))
        out.append({"id": r.id, "category": r.category, "checked_at": r.checked_at,
                    "addr": r.addr, "doctor": r.doctor, "doc_count": cnt or 0, "note": r.note})
    return _j(out)


async def _h_get_report(args, db, user=None):
    stmt = select(Report).where(Report.id == int(args["record_id"]))
    if user is not None:
        _sc = _sc_report(user)
        if _sc is not None:
            stmt = stmt.where(_sc)
    r = (await db.execute(stmt)).scalar_one_or_none()
    if not r:
        return "检查记录不存在"
    res = await db.execute(select(ReportDoc).where(ReportDoc.report_id == r.id).order_by(ReportDoc.id))
    docs = res.scalars().all()
    return _fmt_record(r, list(docs))


async def _h_get_doc(args, db, user=None):
    d = await db.get(ReportDoc, int(args["doc_id"]))
    if not d:
        return "报告不存在"
    if user is not None and user.role != "admin":
        rep = await db.get(Report, d.report_id)
        if not rep or rep.user_id != user.id:
            return "报告不存在"
    return _fmt_doc(d)


async def _h_list_prescriptions(args, db, user=None):
    stmt = select(Prescription).order_by(Prescription.id.desc()).limit(min(int(args.get("limit") or 20), 100))
    if user is not None:
        _sc = _sc_rx(user)
        if _sc is not None:
            stmt = stmt.where(_sc)
    q = (args.get("q") or "").strip()
    patient = (args.get("patient") or "").strip()
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Prescription.patient.like(like) | Prescription.org_dept.like(like))
    if patient:
        stmt = stmt.where(Prescription.patient.like(f"%{patient}%"))
    res = await db.execute(stmt)
    out = []
    for p in res.scalars().all():
        cnt = await db.scalar(select(func.count()).select_from(MedicationItem).where(MedicationItem.prescription_id == p.id))
        out.append({"id": p.id, "patient": p.patient, "org_dept": p.org_dept, "doctor": p.doctor,
                    "prescribed_at": p.prescribed_at, "item_count": cnt or 0, "note": p.note})
    return _j(out)


async def _h_get_prescription(args, db, user=None):
    stmt = select(Prescription).where(Prescription.id == int(args["id"]))
    if user is not None:
        _sc = _sc_rx(user)
        if _sc is not None:
            stmt = stmt.where(_sc)
    p = (await db.execute(stmt)).scalar_one_or_none()
    if not p:
        return "开方记录不存在"
    res = await db.execute(select(MedicationItem).where(MedicationItem.prescription_id == p.id).order_by(MedicationItem.id))
    items = [{"name": i.name, "spec": i.spec, "frequency": i.frequency, "usage": i.usage,
              "status": i.status, "note": i.note} for i in res.scalars().all()]
    return _j({"id": p.id, "patient": p.patient, "org_dept": p.org_dept, "doctor": p.doctor,
               "prescribed_at": p.prescribed_at, "note": p.note, "items": items})


async def _h_stats(args, db, user=None):
    """统计概览（按当前用户可访问的数据范围统计）。"""
    mine = user is not None and user.role != "admin"

    n_records = await db.scalar(
        select(func.count()).select_from(Report).where(_sc_report(user) if mine else True)) or 0
    n_rx = await db.scalar(
        select(func.count()).select_from(Prescription).where(_sc_rx(user) if mine else True)) or 0
    if mine:
        n_docs = await db.scalar(
            select(func.count()).select_from(ReportDoc).join(Report, ReportDoc.report_id == Report.id)
            .where(Report.user_id == user.id)) or 0
    else:
        n_docs = await db.scalar(select(func.count()).select_from(ReportDoc)) or 0
    cats = (await db.execute(
        select(Report.category, func.count()).where(Report.user_id == user.id if mine else True)
        .group_by(Report.category))).all()
    # 异常项 Top（仅统计用户可见的报告明细）
    abnormal = {}
    docs_stmt = select(ReportDoc).join(Report, ReportDoc.report_id == Report.id)
    if mine:
        docs_stmt = docs_stmt.where(Report.user_id == user.id)
    rows = (await db.execute(docs_stmt)).scalars().all()
    for doc in rows:
        for it in _parse_items(doc.items_json or "[]"):
            if it.get("result") not in ("", "normal"):
                key = it["name"]
                abnormal[key] = abnormal.get(key, 0) + 1
    top = sorted(abnormal.items(), key=lambda x: -x[1])[:10]
    return _j({"check_records": n_records, "reports": n_docs, "prescriptions": n_rx,
               "category_dist": [{"category": c, "count": n} for c, n in cats],
               "abnormal_top": [{"name": k, "count": v} for k, v in top]})


# ---------- 联网搜索 / 读网页（Bing，免 key：服务器国内可达） ----------
_SEARCH_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
}


def _http_get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=_SEARCH_UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def _h_web_search_result(args: dict) -> dict:
    """抓 Bing 搜索并解析为结构化结果 {query, results:[{title,url,snippet}]}。"""
    q = str(args.get("q") or "").strip()
    n = int(args.get("n") or 5)
    n = max(1, min(n, 8))
    out = {"query": q, "error": "", "results": []}
    if not q:
        out["error"] = "搜索关键词为空"
        return out
    try:
        html_text = _http_get("https://www.bing.com/search?q=" + urllib.parse.quote(q))
    except Exception as ex:  # noqa: BLE001
        out["error"] = f"联网搜索失败：{ex}"
        return out
    for it in re.findall(r'<li class="b_algo".*?</li>', html_text, re.S)[:n]:
        t = re.search(r'<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', it, re.S)
        if not t:
            continue
        sn = re.search(r'<p[^>]*>(.*?)</p>', it, re.S)
        out["results"].append({
            "title": _strip_tags(_html.unescape(t.group(2))),
            "url": t.group(1),
            "snippet": _strip_tags(_html.unescape(sn.group(1))) if sn else "",
        })
    if not out["results"]:
        out["error"] = f"未找到与「{q}」相关的搜索结果"
    return out


def _fmt_search_text(info: dict) -> str:
    lines = [f"联网搜索结果（关键词：{info['query']}）："]
    if info.get("error"):
        lines.append(info["error"])
        return "\n".join(lines)
    for i, r in enumerate(info["results"], 1):
        lines.append(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet'][:150]}")
    return "\n".join(lines)


async def _h_web_search(args, db, user=None) -> str:
    info = await asyncio.get_running_loop().run_in_executor(None, _h_web_search_result, args)
    return _fmt_search_text(info)


def _h_web_fetch_raw(url: str, limit: int = 3000) -> str:
    url = str(url or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return "URL 无效"
    try:
        raw = _http_get(url, timeout=15)
    except Exception as ex:  # noqa: BLE001
        return f"读取网页失败：{ex}"
    raw = re.sub(r"<(script|style|noscript|iframe|svg)[\s\S]*?</\1>", " ", raw, flags=re.I)
    text = _strip_tags(raw)
    if len(text) > limit:
        text = text[:limit] + "…"
    return f"网页内容（{url}）：\n{text}"


async def _h_web_fetch(args, db, user=None) -> str:
    return await asyncio.get_running_loop().run_in_executor(
        None, _h_web_fetch_raw, args.get("url"), int(args.get("limit") or 3000))


_WRITE_PERM = {
    "create_report": "op.report.write", "update_report": "op.report.write", "delete_report": "op.report.write",
    "create_doc": "op.report.write", "update_doc": "op.report.write", "delete_doc": "op.report.write",
    "create_prescription": "op.med.write", "update_prescription": "op.med.write", "delete_prescription": "op.med.write",
}


async def _perm_ok(db, user, fn: str) -> bool:
    """AI 写工具权限判定（admin 恒放行）。"""
    perm = _WRITE_PERM.get(fn)
    if not perm:
        return False
    return await user_has_perm(db, user, perm)


def _deny() -> str:
    return "你的账号没有执行该操作的权限，已拒绝执行"


async def _h_create_report(args, db, user):
    if not await _perm_ok(db, user, "create_report"):
        return _deny()
    obj = Report(user_id=user.id, category=args.get("category") or "体检", checked_at=_dt(args.get("checked_at")),
                 addr=args.get("addr"), doctor=args.get("doctor"), note=args.get("note"))
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _j({"id": obj.id, "ok": True})


async def _h_update_report(args, db, user):
    if not await _perm_ok(db, user, "update_report"):
        return _deny()
    stmt = select(Report).where(Report.id == int(args["record_id"]))
    if user.role != "admin":
        stmt = stmt.where(Report.user_id == user.id)
    r = (await db.execute(stmt)).scalar_one_or_none()
    if not r:
        return "检查记录不存在"
    for f in ("category", "addr", "doctor", "note"):
        if args.get(f) is not None:
            setattr(r, f, args[f])
    if args.get("checked_at") is not None:
        r.checked_at = _dt(args["checked_at"])
    await db.commit()
    return "更新成功"


async def _h_delete_report(args, db, user):
    if not await _perm_ok(db, user, "delete_report"):
        return _deny()
    stmt = select(Report).where(Report.id == int(args["record_id"]))
    if user.role != "admin":
        stmt = stmt.where(Report.user_id == user.id)
    r = (await db.execute(stmt)).scalar_one_or_none()
    if not r:
        return "检查记录不存在"
    res = await db.execute(select(ReportDoc).where(ReportDoc.report_id == r.id))
    for d in res.scalars().all():
        await db.delete(d)
    await db.delete(r)
    await db.commit()
    return "删除成功"


async def _h_create_doc(args, db, user):
    if not await _perm_ok(db, user, "create_doc"):
        return _deny()
    stmt = select(Report).where(Report.id == int(args["record_id"]))
    if user.role != "admin":
        stmt = stmt.where(Report.user_id == user.id)
    r = (await db.execute(stmt)).scalar_one_or_none()
    if not r:
        return "检查记录不存在"
    obj = ReportDoc(report_id=r.id, name=str(args["name"]).strip(), note=args.get("note"),
                    items_json=_j(_parse_items(args.get("items") or [])))
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _j({"id": obj.id, "ok": True})


async def _h_update_doc(args, db, user):
    if not await _perm_ok(db, user, "update_doc"):
        return _deny()
    d = await db.get(ReportDoc, int(args["doc_id"]))
    if not d:
        return "报告不存在"
    if user.role != "admin":
        rep = await db.get(Report, d.report_id)
        if not rep or rep.user_id != user.id:
            return "报告不存在"
    if args.get("name") is not None:
        d.name = str(args["name"]).strip()
    if args.get("note") is not None:
        d.note = args["note"]
    if args.get("items") is not None:
        d.items_json = _j(_parse_items(args["items"]))
    await db.commit()
    return "更新成功"


async def _h_delete_doc(args, db, user):
    if not await _perm_ok(db, user, "delete_doc"):
        return _deny()
    d = await db.get(ReportDoc, int(args["doc_id"]))
    if not d:
        return "报告不存在"
    if user.role != "admin":
        rep = await db.get(Report, d.report_id)
        if not rep or rep.user_id != user.id:
            return "报告不存在"
    await db.delete(d)
    await db.commit()
    return "删除成功"


async def _h_create_prescription(args, db, user):
    if not await _perm_ok(db, user, "create_prescription"):
        return _deny()
    obj = Prescription(user_id=user.id, patient=str(args["patient"]).strip(), org_dept=args.get("org_dept"),
                       doctor=args.get("doctor"), prescribed_at=_dt(args.get("prescribed_at")),
                       note=args.get("note"))
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _j({"id": obj.id, "ok": True})


async def _h_update_prescription(args, db, user):
    if not await _perm_ok(db, user, "update_prescription"):
        return _deny()
    stmt = select(Prescription).where(Prescription.id == int(args["id"]))
    if user.role != "admin":
        stmt = stmt.where(Prescription.user_id == user.id)
    p = (await db.execute(stmt)).scalar_one_or_none()
    if not p:
        return "开方记录不存在"
    for f in ("patient", "org_dept", "doctor", "note"):
        if args.get(f) is not None:
            setattr(p, f, args[f])
    if args.get("prescribed_at") is not None:
        p.prescribed_at = _dt(args["prescribed_at"])
    await db.commit()
    return "更新成功"


async def _h_delete_prescription(args, db, user):
    if not await _perm_ok(db, user, "delete_prescription"):
        return _deny()
    stmt = select(Prescription).where(Prescription.id == int(args["id"]))
    if user.role != "admin":
        stmt = stmt.where(Prescription.user_id == user.id)
    p = (await db.execute(stmt)).scalar_one_or_none()
    if not p:
        return "开方记录不存在"
    res = await db.execute(select(MedicationItem).where(MedicationItem.prescription_id == p.id))
    for i in res.scalars().all():
        await db.delete(i)
    await db.delete(p)
    await db.commit()
    return "删除成功"


_READ_HANDLERS = {
    "list_reports": _h_list_reports,
    "get_report": _h_get_report,
    "get_doc": _h_get_doc,
    "list_prescriptions": _h_list_prescriptions,
    "get_prescription": _h_get_prescription,
    "stats": _h_stats,
    "web_search": _h_web_search,
    "web_fetch": _h_web_fetch,
}

_WRITE_HANDLERS = {
    "create_report": _h_create_report,
    "update_report": _h_update_report,
    "delete_report": _h_delete_report,
    "create_doc": _h_create_doc,
    "update_doc": _h_update_doc,
    "delete_doc": _h_delete_doc,
    "create_prescription": _h_create_prescription,
    "update_prescription": _h_update_prescription,
    "delete_prescription": _h_delete_prescription,
}


class AgentChatIn(BaseModel):
    alias: str
    model: str
    message: str
    history: list = []   # [{role, content}] 之前的对话
    think: str = "low"   # off | low | medium | high（思考深度）
    skills: list = []    # 启用的技能名


class PendingAction(BaseModel):
    id: str
    name: str
    args: dict
    desc: str


class AgentChatOut(BaseModel):
    reply: str = ""
    thinking: str = ""                     # 模型的推理过程（reasoning，若有）
    pending_actions: list[PendingAction] = []


_THINK_PROMPTS = {
    "off": "请简洁直接地回答，不要多余推理。",
    "low": "请给出清晰、有条理的回答。",
    "medium": "请先分步推理，再给出结论，适当展开分析。",
    "high": "请深入分析：先拆解问题、考虑多种可能，逐步推演后再给出结论。",
}


@router.post("/ai/agent-chat", response_model=AgentChatOut)
async def agent_chat(data: AgentChatIn, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _cur_user(request, db)
    conf = await _get_model_conf(db, data.alias, data.model)
    # 思考深度 + 启用技能 → 拼入系统提示
    extra = ""
    think_p = _THINK_PROMPTS.get(data.think or "low")
    if think_p:
        extra += "\n思考深度：" + think_p
    skill_parts = []
    for s in (data.skills or [])[:8]:
        sk = SKILLS.get(s)
        if sk:
            skill_parts.append(f"[技能 {sk['name']}] {sk['description']}\n{sk['prompt'][:1000]}")
    if skill_parts:
        extra += "\n\n已启用技能（请按其要求工作）：\n" + "\n\n".join(skill_parts)
    messages = [{"role": "system", "content": _SYSTEM_PROMPT + extra}]
    for h in (data.history or [])[-20:]:
        role = h.get("role")
        if role in ("user", "assistant", "tool", "system"):
            messages.append({"role": role, "content": str(h.get("content") or "")})
    messages.append({"role": "user", "content": data.message})

    pending: list[PendingAction] = []
    last_msg = None
    for _ in range(6):
        msg = call_chat(conf.addr, conf.api_key, conf.name, messages, tools=_TOOLS, timeout=180)
        last_msg = msg
        tcs = msg.get("tool_calls") or []
        if not tcs:
            break
        for tc in tcs:
            fn = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except (ValueError, TypeError):
                args = {}
            if fn in _WRITE_NAMES:
                if not await _perm_ok(db, user, fn):
                    content = _deny()
                else:
                    pa = PendingAction(id=uuid.uuid4().hex[:8], name=fn, args=args,
                                       desc=_describe_action(fn, args))
                    pending.append(pa)
                    content = f"写操作 {fn} 已列入待确认清单（编号 {pa.id}），请勿直接执行，回复用户说明将执行的操作并等待确认。"
            else:
                try:
                    handler = _READ_HANDLERS.get(fn)
                    content = await handler(args, db, user) if handler else f"未知工具 {fn}"
                except Exception as ex:  # noqa: BLE001
                    content = f"执行 {fn} 失败：{ex}"
            messages.append(tool_result_message(tc["id"], content))
        if pending:
            # 已有待确认操作：让模型基于现状给出说明性回复
            await asyncio.sleep(1.2)   # 连续调用间隔，规避 BurstRate
            msg2 = call_chat(conf.addr, conf.api_key, conf.name, messages, timeout=180)
            last_msg = msg2
            break
        await asyncio.sleep(1.2)       # 每轮工具循环之间留间隔
    reply = (last_msg.get("content") or "").strip() or "（模型未返回内容）"
    thinking = str(last_msg.get("reasoning_content") or last_msg.get("reasoning") or "").strip()
    return AgentChatOut(reply=reply, thinking=thinking, pending_actions=pending)


@router.post("/ai/agent-chat-stream")
async def agent_chat_stream(data: AgentChatIn, request: Request, db: AsyncSession = Depends(get_db)):
    """流式问数助手：工具调用步骤（尤其 web_search）实时推给前端展示搜索小窗。
    SSE 事件：{"type":"web_search", query, status:"running"|"done", results:[{title,url,snippet}]}
    → 最终 {"type":"done", reply, thinking, pending_actions}。"""
    user = await _cur_user(request, db)
    conf = await _get_model_conf(db, data.alias, data.model)
    extra = ""
    think_p = _THINK_PROMPTS.get(data.think or "low")
    if think_p:
        extra += "\n思考深度：" + think_p
    skill_parts = []
    for s in (data.skills or [])[:8]:
        sk = SKILLS.get(s)
        if sk:
            skill_parts.append(f"[技能 {sk['name']}] {sk['description']}\n{sk['prompt'][:1000]}")
    if skill_parts:
        extra += "\n\n已启用技能（请按其要求工作）：\n" + "\n\n".join(skill_parts)
    messages = [{"role": "system", "content": _SYSTEM_PROMPT + extra}]
    for h in (data.history or [])[-20:]:
        role = h.get("role")
        if role in ("user", "assistant", "tool", "system"):
            messages.append({"role": role, "content": str(h.get("content") or "")})
    messages.append({"role": "user", "content": data.message})

    async def gen():
        loop = asyncio.get_running_loop()
        busyq: asyncio.Queue = asyncio.Queue()
        done_box: dict = {}

        def _busy_sender(attempt, wait):
            # call_chat 的 on_retry 回调（在后台线程内调用）：把重试进度送回事件循环
            try:
                asyncio.run_coroutine_threadsafe(busyq.put(("busy", attempt, wait)), loop)
            except Exception:
                pass

        async def chat_call(msgs, tools=None):
            async def run_with_busy(task):
                # 调用在后台线程执行，期间轮询 busyq 推送"排队重试"进度
                while not task.done():
                    try:
                        _, attempt, wait = busyq.get_nowait()
                        yield "data: " + _j({"type": "busy", "attempt": attempt, "wait": wait}) + "\n\n"
                    except asyncio.QueueEmpty:
                        pass
                    await asyncio.sleep(0.15)
                if task.cancelled():
                    raise asyncio.CancelledError
                ex = task.exception()
                if ex:
                    raise ex

            task = asyncio.ensure_future(loop.run_in_executor(
                None, functools.partial(call_chat, conf.addr, conf.api_key, conf.name, msgs,
                                        tools, None, 0.7, 180, _busy_sender)))
            async for _retry in run_with_busy(task):
                yield _retry
            done_box["msg"] = task.result()

        pending: list[PendingAction] = []
        last_msg = None
        try:
            for _ in range(4):   # 工具循环上限 4 轮（压缩无谓调用，省 tpm）
                async for _ev in chat_call(messages, _TOOLS):
                    yield _ev
                msg = done_box["msg"]
                last_msg = msg
                tcs = msg.get("tool_calls") or []
                if not tcs:
                    break
                for tc in tcs:
                    fn = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except (ValueError, TypeError):
                        args = {}
                    if fn in _WRITE_NAMES:
                        if not await _perm_ok(db, user, fn):
                            content = _deny()
                        else:
                            pa = PendingAction(id=uuid.uuid4().hex[:8], name=fn, args=args,
                                               desc=_describe_action(fn, args))
                            pending.append(pa)
                            content = f"写操作 {fn} 已列入待确认清单（编号 {pa.id}），请勿直接执行，回复用户说明将执行的操作并等待确认。"
                    elif fn == "web_search":
                        info = await loop.run_in_executor(None, _h_web_search_result, args)
                        q_ = info.get("query") or args.get("q") or ""
                        yield "data: " + _j({"type": "web_search", "query": q_, "status": "running", "results": []}) + "\n\n"
                        if info.get("error"):
                            yield "data: " + _j({"type": "web_search", "query": q_, "status": "done",
                                                 "results": [], "error": info["error"]}) + "\n\n"
                        else:
                            yield "data: " + _j({"type": "web_search", "query": q_, "status": "done",
                                                 "results": info["results"]}) + "\n\n"
                        content = _fmt_search_text(info)
                    else:
                        try:
                            handler = _READ_HANDLERS.get(fn)
                            content = await handler(args, db, user) if handler else f"未知工具 {fn}"
                        except Exception as ex:  # noqa: BLE001
                            content = f"执行 {fn} 失败：{ex}"
                    messages.append(tool_result_message(tc["id"], content))
                if pending:
                    await asyncio.sleep(1.2)   # 连续调用间隔，规避供应商 BurstRate 突发限流
                    async for _ev in chat_call(messages):
                        yield _ev
                    msg2 = done_box["msg"]
                    last_msg = msg2
                    break
                await asyncio.sleep(1.2)       # 每轮工具循环之间留间隔，避免短窗口内连打
            else:
                # 4 轮内模型一直调工具未产出文字：强制补一次不带工具的收尾对话
                async for _ev in chat_call(messages):
                    yield _ev
                last_msg = done_box["msg"]
            reply = (last_msg.get("content") or "").strip() or "（模型未返回内容）"
            thinking = str(last_msg.get("reasoning_content") or last_msg.get("reasoning") or "").strip()
        except Exception as ex:  # noqa: BLE001
            yield "data: " + _j({"type": "error", "message": f"AI 服务调用失败：{ex}"}) + "\n\n"
            return
        yield "data: " + _j({"type": "done", "reply": reply, "thinking": thinking,
                             "pending_actions": [
                                 {"id": p.id, "name": p.name, "args": p.args, "desc": p.desc} for p in pending]}) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class WebFetchIn(BaseModel):
    url: str
    limit: Optional[int] = 3000


@router.post("/ai/web-fetch")
async def web_fetch_ep(data: WebFetchIn):
    """前端"阅读全文"：抓指定网页正文（纯文本）。"""
    text = await asyncio.get_running_loop().run_in_executor(
        None, _h_web_fetch_raw, data.url, int(data.limit or 3000))
    prefix = "网页内容（"
    if text.startswith(prefix):
        body = text[len(prefix):]
        text = body.split('）：\n', 1)[-1]
    return {"url": data.url, "text": text}


def _step_desc(fn: str, args: dict) -> str:
    """把一次工具调用转成用户可读的"执行步骤"文案（MonkeyCode 式任务列表）。"""
    if fn == "web_search":
        q = (args.get("q") or "").strip()
        return f"联网搜索：{q}" if q else "联网搜索"
    if fn == "web_fetch":
        return "阅读网页正文"
    zh = {
        "list_reports": "查询检查记录列表",
        "get_report": "查看检查记录明细",
        "get_doc": "查看报告详情",
        "list_prescriptions": "查询用药开方",
        "get_prescription": "查看开方详情",
        "stats": "统计系统概览",
        "create_report": "新增检查记录", "update_report": "修改检查记录", "delete_report": "删除检查记录",
        "create_doc": "新增报告", "update_doc": "修改报告", "delete_doc": "删除报告",
        "create_prescription": "新增用药开方", "update_prescription": "修改用药开方", "delete_prescription": "删除用药开方",
    }
    base = zh.get(fn, f"工具 {fn}")
    extra = ""
    if fn in ("get_report",) and args.get("record_id"):
        extra = f" #{args['record_id']}"
    elif fn in ("get_doc",) and args.get("doc_id"):
        extra = f" #{args['doc_id']}"
    elif fn in ("get_prescription",) and args.get("id"):
        extra = f" #{args['id']}"
    elif fn in ("list_reports", "list_prescriptions") and (args.get("q") or args.get("category")):
        parts = []
        q = (args.get("q") or "").strip()
        cat = (args.get("category") or "").strip()
        if q:
            parts.append(f"关键字 {q}")
        if cat:
            parts.append(f"类别 {cat}")
        extra = f"（{'、'.join(parts)}）"
    elif fn == "create_doc" and args.get("name"):
        extra = f"「{args['name']}」"
    elif fn == "create_prescription" and args.get("patient"):
        extra = f"（患者：{args['patient']}）"
    elif fn == "create_report" and args.get("category"):
        extra = f"（类别：{args['category']}）"
    return base + extra


def _describe_action(name: str, args: dict) -> str:
    zh = {
        "create_report": "新增检查记录", "update_report": "修改检查记录", "delete_report": "删除检查记录",
        "create_doc": "新增报告", "update_doc": "修改报告", "delete_doc": "删除报告",
        "create_prescription": "新增用药开方", "update_prescription": "修改用药开方", "delete_prescription": "删除用药开方",
    }
    base = zh.get(name, name)
    if name == "delete_report":
        return f"删除检查记录 #{args.get('record_id')}"
    if name == "delete_doc":
        return f"删除报告 #{args.get('doc_id')}"
    if name == "delete_prescription":
        return f"删除用药开方 #{args.get('id')}"
    if name == "create_report":
        return f"新增检查记录（{args.get('category') or '体检'} / {args.get('checked_at') or '?'} / {args.get('addr') or '?'}）"
    if name == "create_doc":
        return f"在检查记录 #{args.get('record_id')} 下新增报告「{args.get('name')}」（{len(args.get('items') or [])} 项明细）"
    if name == "update_report":
        return f"修改检查记录 #{args.get('record_id')}"
    if name == "update_doc":
        return f"修改报告 #{args.get('doc_id')}"
    if name == "create_prescription":
        return f"新增用药开方（患者：{args.get('patient')}）"
    if name == "update_prescription":
        return f"修改用药开方 #{args.get('id')}"
    return f"{base}（{args}）"


class AgentExecIn(BaseModel):
    action: PendingAction


@router.post("/ai/agent-execute")
async def agent_execute(data: AgentExecIn, request: Request, db: AsyncSession = Depends(get_db)):
    """执行确认后的写操作，返回结果文本。"""
    user = await _cur_user(request, db)
    handler = _WRITE_HANDLERS.get(data.action.name)
    if not handler:
        raise HTTPException(status_code=400, detail="不支持的操作类型")
    try:
        result = await handler(data.action.args, db, user)
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"执行失败：{ex}")
    return {"ok": True, "result_text": f"已执行 {_describe_action(data.action.name, data.action.args)}：{result}"}


# ---------- 会话持久化（整份数据存 DB，刷新/换设备不丢失） ----------
class SessionsSaveIn(BaseModel):
    groups: list = []
    sessions: list = []
    ver: int = 0   # 前端维护的单调递增版本（Date.now()），用于刷新时判定新旧


@router.get("/ai/sessions")
async def get_sessions(request: Request, db: AsyncSession = Depends(get_db)):
    """读取当前用户保存的 AI 问数会话。"""
    user = await _get_user_by_token(db, _token_from(request))
    res = await db.execute(select(AiChatSession).where(AiChatSession.user_id == user.id))
    row = res.scalar_one_or_none()
    if not row or not row.data:
        return {"ver": 0, "user_id": user.id, "groups": [], "sessions": []}
    try:
        data = json.loads(row.data)
    except (ValueError, TypeError):
        return {"ver": 0, "user_id": user.id, "groups": [], "sessions": []}
    return {"ver": int(data.get("ver") or 0),
            "user_id": user.id,
            "groups": data.get("groups", []),
            "sessions": data.get("sessions", [])}


@router.post("/ai/sessions")
async def save_sessions(data: SessionsSaveIn, request: Request, db: AsyncSession = Depends(get_db)):
    """整体保存当前用户的 AI 问数会话（upsert 单行）。"""
    user = await _get_user_by_token(db, _token_from(request))
    payload = json.dumps({"ver": int(data.ver or 0),
                          "groups": data.groups or [],
                          "sessions": data.sessions or []}, ensure_ascii=False)
    res = await db.execute(select(AiChatSession).where(AiChatSession.user_id == user.id))
    row = res.scalar_one_or_none()
    if row:
        row.data = payload
        row.updated_at = datetime.utcnow()
    else:
        db.add(AiChatSession(user_id=user.id, data=payload))
    await db.commit()
    return {"ok": True, "n": len(data.sessions or []), "ver": int(data.ver or 0)}


# ---------- 技能管理 ----------
@router.get("/ai/skills")
async def list_skills():
    """返回已安装技能（含默认技能）。"""
    return [{"name": s["name"], "description": s["description"]} for s in SKILLS.values()]


@router.post("/ai/skills/install")
async def install_skill(file: UploadFile = File(...)):
    """上传 SKILL.md 安装新技能，命名取 frontmatter 的 name 或文件名。"""
    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="技能文件必须为 UTF-8 编码的 Markdown")
    name = os.path.splitext(os.path.basename(file.filename or ""))[0].strip().replace(" ", "-")
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if line.lower().startswith("name:"):
                name = line.split(":", 1)[1].strip().strip('"\'')
    if not name or not re.match(r"^[A-Za-z0-9_-]{1,40}$", name):
        raise HTTPException(status_code=400, detail="技能名不合法（仅字母数字-_，最长 40）")
    d = os.path.join(SKILLS_DIR, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(text)
    SKILLS.update(_load_skills())
    return {"ok": True, "name": name, "description": SKILLS.get(name, {}).get("description", "")}


# ---------- 上下文压缩 ----------
class CompactIn(BaseModel):
    alias: str
    model: str
    history: list = []   # [{role, content}]


@router.post("/ai/agent-compact")
async def agent_compact(data: CompactIn, db: AsyncSession = Depends(get_db)):
    """把历史对话压缩成一段精炼摘要（MonkeyCode compact 机制）。"""
    conf = await _get_model_conf(db, data.alias, data.model)
    msgs = []
    for h in (data.history or [])[-40:]:
        role = h.get("role")
        if role in ("user", "assistant", "system", "tool"):
            msgs.append({"role": role, "content": str(h.get("content") or "")})
    if not msgs:
        return {"summary": ""}
    body = "\n".join(f"{m['role']}: {m['content']}" for m in msgs)
    prompt = (
        "请把下面的对话压缩成一段精炼的中文摘要，保留关键问题、已得出的结论、待办事项"
        "以及尚未确认的写操作，尽量保留数字与事实，不超过 600 字。\n\n对话内容：\n" + body
    )
    msg = call_chat(conf.addr, conf.api_key, conf.name,
                    [{"role": "user", "content": prompt}], temperature=0.2, timeout=120)
    return {"summary": (msg.get("content") or "").strip()}


# ================= AI 问数后台任务（断线/离开页面继续执行） =================
# 与 HTTP 生命周期解耦：任务在服务器端 asyncio 后台执行，SSE 只是"订阅视图"，
# 前端断开/刷新/退出都不影响任务本体；不设时间限制，除非用户主动取消。
_AGENT_TASKS: dict[str, dict] = {}


def _build_agent_messages(data: AgentChatIn) -> list[dict]:
    extra = ""
    think_p = _THINK_PROMPTS.get(data.think or "low")
    if think_p:
        extra += "\n思考深度：" + think_p
    skill_parts = []
    for s in (data.skills or [])[:8]:
        sk = SKILLS.get(s)
        if sk:
            skill_parts.append(f"[技能 {sk['name']}] {sk['description']}\n{sk['prompt'][:1000]}")
    if skill_parts:
        extra += "\n\n已启用技能（请按其要求工作）：\n" + "\n\n".join(skill_parts)
    messages = [{"role": "system", "content": _SYSTEM_PROMPT + extra}]
    for h in (data.history or [])[-20:]:
        role = h.get("role")
        if role in ("user", "assistant", "tool", "system"):
            messages.append({"role": role, "content": str(h.get("content") or "")})
    messages.append({"role": "user", "content": data.message})
    return messages


async def _run_agent_task(task_id: str, conf, messages: list, user: User):
    """后台执行完整问数任务（工具链 + 无限重试），进度写进 _AGENT_TASKS[task_id]。"""
    st = _AGENT_TASKS[task_id]
    loop = asyncio.get_running_loop()
    logger.info("AGENT TASK start id=%s model=%s q=%s", task_id, conf.name,
                str(messages[-1].get("content") or "")[:80])

    def _emit(ev: dict):
        st["events"].append(ev)
        try:
            st["cv"].notify_all()   # 同步方法，线程/协程均可调用
        except Exception:
            pass

    async def chat_call(msgs, tools=None):
        # 流式读取：正文/推理逐字推送 SSE（delta/think），前端实时打字显示
        def _on_llm(kind, val):
            if kind == "delta":
                if isinstance(st.get("reply"), str):
                    st["reply"] = st["reply"] + val
                else:
                    st["reply"] = val
                _emit({"type": "delta", "text": val})
            elif kind == "think":
                if isinstance(st.get("thinking"), str):
                    st["thinking"] = st["thinking"] + val
                else:
                    st["thinking"] = val
                _emit({"type": "think", "text": val})
            elif kind == "reset":
                n, m = val.get("content") or 0, val.get("think") or 0
                if isinstance(st.get("reply"), str):
                    st["reply"] = st["reply"][:n]
                if isinstance(st.get("thinking"), str):
                    st["thinking"] = st["thinking"][:m]
                _emit({"type": "delta_reset", "content": n, "think": m})
            elif kind == "retry":
                a, w = val
                _emit({"type": "busy", "attempt": a, "wait": w})
        return await loop.run_in_executor(None, functools.partial(
            call_chat_stream, conf.addr, conf.api_key, conf.name, msgs, tools, 0.7, 300,
            _on_llm, st["cancel"]))

    pending: list[PendingAction] = []
    last_msg = None
    try:
        # 独立数据库会话供只读工具使用（请求 session 已随 HTTP 结束）
        async with AsyncSessionLocal() as task_db:
            for _ in range(4):   # 工具循环上限 4 轮（压缩无谓调用，省 tpm）
                msg = await chat_call(messages, _TOOLS)
                last_msg = msg
                tcs = msg.get("tool_calls") or []
                if not tcs:
                    break
                for tc in tcs:
                    fn = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except (ValueError, TypeError):
                        args = {}
                    logger.info("AGENT TASK %s call fn=%s args=%s", task_id, fn,
                                json.dumps(args, ensure_ascii=False)[:200])
                    if fn in _WRITE_NAMES:
                        if not await _perm_ok(task_db, user, fn):
                            content = _deny()
                        else:
                            pa = PendingAction(id=uuid.uuid4().hex[:8], name=fn, args=args,
                                               desc=_describe_action(fn, args))
                            pending.append(pa)
                            content = f"写操作 {fn} 已列入待确认清单（编号 {pa.id}），请勿直接执行，回复用户说明将执行的操作并等待确认。"
                    else:
                        # 执行步骤（MonkeyCode 式任务列表）：running → done 推进进度条
                        st["step_seq"] = st.get("step_seq", 0) + 1
                        sid = f"st{st['step_seq']}"
                        sdesc = _step_desc(fn, args)
                        _emit({"type": "step", "id": sid, "fn": fn, "desc": sdesc, "status": "running"})
                        try:
                            if fn == "web_search":
                                info = await loop.run_in_executor(None, _h_web_search_result, args)
                                q_ = info.get("query") or args.get("q") or ""
                                _emit({"type": "web_search", "query": q_, "status": "running", "results": []})
                                if info.get("error"):
                                    _emit({"type": "web_search", "query": q_, "status": "done",
                                           "results": [], "error": info["error"]})
                                else:
                                    _emit({"type": "web_search", "query": q_, "status": "done",
                                           "results": info["results"]})
                                st["searches"].append({"q": q_,
                                                       "done": not info.get("error"),
                                                       "error": info.get("error") or "",
                                                       "results": info["results"]})
                                content = _fmt_search_text(info)
                            else:
                                handler = _READ_HANDLERS.get(fn)
                                content = await handler(args, task_db, user) if handler else f"未知工具 {fn}"
                        except Exception as ex:  # noqa: BLE001
                            st["steps"] = (st.get("steps") or []) + [{"id": sid, "desc": sdesc, "status": "error"}]
                            content = f"执行 {fn} 失败：{ex}"
                        else:
                            st["steps"] = (st.get("steps") or []) + [{"id": sid, "desc": sdesc, "status": "done"}]
                            _emit({"type": "step", "id": sid, "fn": fn, "desc": sdesc, "status": "done"})
                    messages.append(tool_result_message(tc["id"], content))
                if pending:
                    await asyncio.sleep(1.2)   # 连续调用间隔，规避供应商 BurstRate 突发限流
                    last_msg = await chat_call(messages)
                    break
                await asyncio.sleep(1.2)       # 每轮工具循环之间留间隔
            else:
                # 4 轮内模型一直调工具未产出文字（如搜索后还想再查数据）：
                # 强制补一次不带工具的收尾对话，模型此时必须给出文字回答
                logger.info("AGENT TASK %s rounds exhausted, force final answer", task_id)
                last_msg = await chat_call(messages)
        # 流式期间已累积正文/推理（st["reply"]/st["thinking"]）；为空才用最后消息兜底
        st["reply"] = str(st.get("reply") or "").strip() or (last_msg.get("content") or "").strip() or "（模型未返回内容）"
        st["thinking"] = str(st.get("thinking") or "").strip() or str(
            last_msg.get("reasoning_content") or last_msg.get("reasoning") or "").strip()
        st["pending"] = [{"id": p.id, "name": p.name, "args": p.args, "desc": p.desc} for p in pending]
        st["status"] = "done"
        logger.info("AGENT TASK %s done reply_len=%d", task_id, len(st["reply"]))
    except AgentCancelled:
        st["status"] = "cancelled"
        st["error"] = "用户已取消"
        logger.info("AGENT TASK %s cancelled", task_id)
    except HTTPException as ex:
        st["status"] = "error"
        st["error"] = str(ex.detail)
        logger.warning("AGENT TASK %s error: %s", task_id, str(ex.detail)[:300])
    except Exception as ex:  # noqa: BLE001
        st["status"] = "error"
        st["error"] = f"AI 服务调用失败：{ex}"
        logger.exception("AGENT TASK %s exception", task_id)
    # 落库存档（重启后仍可查到最终结果）
    try:
        async with AsyncSessionLocal() as s:
            row = await s.get(AiAgentTask, task_id)
            if row:
                row.status = st["status"]
                row.reply = st["reply"]
                row.thinking = st["thinking"]
                row.pending = json.dumps(st["pending"], ensure_ascii=False)
                row.searches = json.dumps(st["searches"], ensure_ascii=False)
                row.error = st["error"]
                row.finished_at = datetime.utcnow()
                await s.commit()
    except Exception:
        pass
    _emit({"type": "status", "status": st["status"]})
    try:
        st["cv"].notify_all()
    except Exception:
        pass

    # 终态后延迟清理内存任务（60 分钟）：给"离开页面后回来补看"留足回放窗口，
    # 之后仅数据库保留终态记录；避免反复发起/停止导致内存缓慢增长
    async def _expire():
        await asyncio.sleep(3600)
        _AGENT_TASKS.pop(task_id, None)

    try:
        loop.create_task(_expire())
    except Exception:
        pass


@router.post("/ai/agent-chat-task")
async def create_agent_task(data: AgentChatIn, request: Request, db: AsyncSession = Depends(get_db)):
    """创建后台问数任务：立即返回 task_id；任务在服务器端持续执行，不受前端连接影响。"""
    user = await _get_user_by_token(db, _token_from(request))
    conf = await _get_model_conf(db, data.alias, data.model)
    messages = _build_agent_messages(data)
    task_id = uuid.uuid4().hex
    st = {"user_id": user.id, "status": "running", "searches": [], "events": [],
          "reply": None, "thinking": None, "pending": [], "error": None,
          "cancel": threading.Event(), "cv": asyncio.Condition()}
    _AGENT_TASKS[task_id] = st
    db.add(AiAgentTask(id=task_id, user_id=user.id, status="running", message=data.message))
    await db.commit()
    asyncio.get_running_loop().create_task(_run_agent_task(task_id, conf, messages, user))
    return {"task_id": task_id, "status": "running"}


@router.get("/ai/agent-chat-task/{task_id}/stream")
async def agent_task_stream(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """订阅任务进度（SSE）。断开只影响本订阅，任务继续执行；重连即从事件日志继续。"""
    user = await _get_user_by_token(db, _token_from(request))
    st = _AGENT_TASKS.get(task_id)
    if not st:
        raise HTTPException(status_code=404, detail="任务不存在")
    if st.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="无权访问该任务")

    async def gen():
        idx = 0
        last_yield = time.time()
        # 进度快照：正文/推理已流式推送进事件日志（跳过回放，避免二次拼接），
        # 新连接/刷新后直接从当前进度续看
        if st.get("reply") or st.get("thinking"):
            yield "data: " + _j({"type": "cur", "reply": st.get("reply") or "",
                                 "thinking": st.get("thinking") or ""}) + "\n\n"
        # 阶段一：回放历史事件。内容类（delta/think/delta_reset）跳过——
        # 文本已由上方 cur 快照全量给出，避免与新内容重复拼接。
        skip = {"delta", "think", "delta_reset"}
        while idx < len(st["events"]):
            ev = st["events"][idx]
            idx += 1
            if ev.get("type") in skip:
                continue
            yield "data: " + _j(ev) + "\n\n"
            last_yield = time.time()
        # 阶段二：实时增量——此后到达的事件（含 delta/think）全部实时推送，
        # 前端在 cur 快照基础上继续追加，逐字输出。
        while True:
            while idx < len(st["events"]):
                ev = st["events"][idx]
                idx += 1
                yield "data: " + _j(ev) + "\n\n"
                last_yield = time.time()
            if st["status"] != "running":
                break
            now = time.time()
            if now - last_yield >= 12:
                yield ": keepalive\n\n"
                last_yield = now
            await asyncio.sleep(0.3)   # 轮询：内容事件来自流读取线程，不用 asyncio.Condition
        # 终态元事件（含搜索结果，供重连接续渲染搜索小窗）
        if st["status"] == "done":
            yield "data: " + _j({"type": "done", "reply": st["reply"], "thinking": st["thinking"],
                                 "pending_actions": st["pending"], "searches": st["searches"]}) + "\n\n"
        elif st["status"] == "error":
            yield "data: " + _j({"type": "error", "message": st["error"] or "任务失败"}) + "\n\n"
        else:
            yield "data: " + _j({"type": "cancelled", "message": st["error"] or "任务已取消"}) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/ai/agent-chat-task/{task_id}/cancel")
async def cancel_agent_task(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """取消后台任务：立即中断当前退避/重试，任务标记 cancelled；不产生时间限制。"""
    user = await _get_user_by_token(db, _token_from(request))
    st = _AGENT_TASKS.get(task_id)
    if not st:
        raise HTTPException(status_code=404, detail="任务不存在")
    if st.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="无权访问该任务")
    st["cancel"].set()
    if st["status"] == "running":
        st["status"] = "cancelled"
        st["error"] = "用户已取消"
    async with st["cv"]:
        st["cv"].notify_all()
    return {"ok": True}
