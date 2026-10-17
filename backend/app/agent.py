from typing import Any
from .config import API_KEY, BASE_URL, MODEL, SYSTEM_PROMPT
from .tools import *

def _llm_enhance(text: str, draft: str) -> str:
    if not API_KEY:
        return draft
    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model=MODEL, api_key=API_KEY, base_url=BASE_URL, temperature=0)
        prompt = f"{SYSTEM_PROMPT}\n用户问题：{text}\n已核验的业务结果：{draft}\n请只基于业务结果，用简洁中文回答。"
        return llm.invoke(prompt).content
    except Exception:
        return draft

def _repair_reply(db, session_id: str, text: str):
    if any(keyword in text for keyword in ["取消报修", "不用报修", "不报修了"]):
        draft = get_repair_draft(db, session_id)
        if draft:
            db.delete(draft); db.commit()
        return "本次报修已取消，未创建工单。", ["cancel_repair_draft"], {"status": "cancelled"}
    ids = re.findall(r"R[A-Za-z0-9]{8}", text.upper())
    if ids:
        result = get_repair_status(db, ids[0])
        reply = (f"工单 {result['id']} 当前状态：{result['status']}，位置：{result['location']}，问题：{result['description']}。" if result.get("found") else result["message"])
        return reply, ["get_repair_status"], None

    draft = update_repair_draft(db, session_id, text)
    missing = missing_repair_fields(draft)
    if missing:
        db.commit()
        known = []
        if draft.category: known.append(f"类别：{draft.category}")
        if draft.urgency: known.append(f"紧急程度：{draft.urgency}")
        if draft.location: known.append(f"位置：{draft.location}")
        prefix = "，".join(known)
        reply = f"已记录{prefix + '。' if prefix else '报修需求。'}请继续提供：{'、'.join(missing)}。"
        return reply, ["update_repair_draft"], {"status": "collecting", "missing_fields": missing}

    order = complete_repair_draft(db, draft)
    reply = f"报修工单已创建，编号 {order['id']}。当前状态：{order['status']}；位置：{order['location']}；问题：{order['description']}。你可以在“报修工单”页面查看和修改。"
    return reply, ["create_repair_order"], {"status": "created", "order": order}

def _offline_reply(db, text: str, session_id: str):
    lower = text.lower()
    used = []
    draft = get_repair_draft(db, session_id)
    if draft or has_repair_intent(text) or re.search(r"R[A-Za-z0-9]{8}", text.upper()):
        return _repair_reply(db, session_id, text)
    if any(k in text for k in ["公告", "通知", "停水", "停电", "充电"]):
        used.append("search_notice")
        rows = search_notice(db, text if len(text) <= 8 else "")
        if not rows: return "暂时没有匹配的公告信息。", used, None
        return "相关公告：\n" + "\n".join(f"- {x['title']}：{x['content']}" for x in rows), used, None
    if any(k in text for k in ["快递", "服务中心", "健身", "在哪里", "位置", "开放"]):
        used.append("query_facility")
        name = "快递驿站" if "快递" in text else ("服务中心" if "服务中心" in text else "公共健身区")
        x = query_facility(db, name)
        return (f"{x['name']}位于{x['location']}，开放时间为{x['hours']}。主要服务：{x['description']}。" if x.get("found") else x["message"]), used, None
    if any(k in text for k in ["你好", "介绍", "能做什么"]):
        return "你好，我是社区生活服务智能管家，可以查询公告和设施位置，也可以协助创建、查询报修工单。", used, None
    return "我可以帮你查询社区公告、设施位置和报修工单。请告诉我具体要办理的事项。", used, None

def agent_chat(db, text: str, session_id: str):
    # 业务工具先确定事实，LangChain 只做可选的自然语言表达增强。
    reply, used, repair = _offline_reply(db, text, session_id)
    final_reply = reply if repair else _llm_enhance(text, reply)
    result = {"reply": final_reply, "tools_used": used, "mode": "offline" if not API_KEY else "hybrid"}
    if repair:
        result["repair"] = repair
    return result
