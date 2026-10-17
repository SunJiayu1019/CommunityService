import json
import logging
import time
import uuid
from collections import defaultdict
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session
from .agent import agent_chat
from .config import RATE_LIMIT
from .database import SessionLocal, init_db
from .models import ChatMessage, ChatSession, KnowledgeDocument, RepairOrder
from .schemas import ChatRequest, KnowledgeTextRequest, KnowledgeWebRequest, RepairRequest, RepairUpdate, SessionCreate
from .tools import create_repair_order, get_repair_status, list_repairs, repair_to_dict
from .knowledge import delete_document_vectors, extract_pdf, extract_web, index_document, new_document_id

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="社区生活服务智能管家 API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
_rate_store = defaultdict(list)

@app.on_event("startup")
def startup():
    init_db()

@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        ip = request.client.host if request.client else "unknown"
        now = time.time(); _rate_store[ip] = [x for x in _rate_store[ip] if now - x < 60]
        if len(_rate_store[ip]) >= RATE_LIMIT:
            return JSONResponse(status_code=429, content={"code": 429, "message": "请求过于频繁，请稍后再试"})
        _rate_store[ip].append(now)
    return await call_next(request)

def db_dep():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def ok(data, message="success"): return {"code": 0, "message": message, "data": data}

def require_admin(request: Request):
    if request.headers.get("x-user-role") != "admin":
        raise HTTPException(403, "仅管理员可以管理知识库")

def persist_knowledge(db: Session, title: str, source_type: str, source: str, content: str):
    document_id = new_document_id()
    row = KnowledgeDocument(id=document_id, title=title, source_type=source_type, source=source, status="indexing")
    db.add(row)
    db.commit()
    try:
        count = index_document(document_id, title, source_type, source, content)
        row.status = "ready"
        row.chunk_count = count
        row.error = None
        db.commit()
        db.refresh(row)
    except Exception as exc:
        db.rollback()
        row = KnowledgeDocument(id=document_id, title=title, source_type=source_type, source=source,
                                status="failed", error=str(exc)[:1000])
        db.add(row)
        db.commit()
        raise HTTPException(503, f"资料已记录但向量入库失败：{exc}")
    return {"id": row.id, "title": row.title, "source_type": row.source_type, "status": row.status, "chunk_count": row.chunk_count}

@app.get("/")
def health(): return ok({"service": "community-service", "status": "running"})

@app.post("/api/sessions")
def create_session(req: SessionCreate, db: Session = Depends(db_dep)):
    row = ChatSession(id=str(uuid.uuid4()), title=req.title); db.add(row); db.commit(); return ok({"id": row.id, "title": row.title})

@app.get("/api/sessions")
def sessions(db: Session = Depends(db_dep)):
    rows = db.query(ChatSession).order_by(ChatSession.updated_at.desc()).all()
    return ok([{ "id": x.id, "title": x.title, "updated_at": x.updated_at.isoformat() if x.updated_at else None } for x in rows])

@app.get("/api/sessions/{session_id}/messages")
def messages(session_id: str, db: Session = Depends(db_dep)):
    rows = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at).all()
    return ok([{ "role": x.role, "content": x.content } for x in rows])

@app.post("/api/agent/chat")
def chat(req: ChatRequest, db: Session = Depends(db_dep)):
    sid = req.session_id or str(uuid.uuid4())
    if not db.query(ChatSession).filter(ChatSession.id == sid).first(): db.add(ChatSession(id=sid, title=req.message[:20]))
    db.add(ChatMessage(session_id=sid, role="user", content=req.message))
    result = agent_chat(db, req.message, sid)
    db.add(ChatMessage(session_id=sid, role="assistant", content=result["reply"])); db.commit()
    return ok({"session_id": sid, **result})

@app.post("/api/chat/stream")
def stream(req: ChatRequest, db: Session = Depends(db_dep)):
    result = chat(req, db)["data"]; text = result["reply"]
    def events():
        for i in range(0, len(text), 8): yield f"data: {json.dumps({'delta': text[i:i+8]}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(events(), media_type="text/event-stream")

@app.post("/api/repairs")
def repair(req: RepairRequest, db: Session = Depends(db_dep)): return ok(create_repair_order(db, req.model_dump()))

@app.get("/api/repairs/{order_id}")
def repair_detail(order_id: str, db: Session = Depends(db_dep)):
    value = get_repair_status(db, order_id)
    if not value.get("found", True): raise HTTPException(404, value["message"])
    return ok(value)

@app.get("/api/repairs")
def repair_list(phone: str | None = None, db: Session = Depends(db_dep)):
    rows = db.query(RepairOrder).order_by(RepairOrder.created_at.desc()).all() if not phone else db.query(RepairOrder).filter(RepairOrder.phone == phone).order_by(RepairOrder.created_at.desc()).all()
    return ok([repair_to_dict(x) for x in rows])

@app.put("/api/repairs/{order_id}")
def update_repair(order_id: str, req: RepairUpdate, request: Request, db: Session = Depends(db_dep)):
    row = db.query(RepairOrder).filter(RepairOrder.id == order_id.upper()).first()
    if not row: raise HTTPException(404, "未找到该工单")
    role = request.headers.get("x-user-role", "resident")
    phone = request.headers.get("x-user-phone")
    if role != "admin" and phone != row.phone: raise HTTPException(403, "只能修改本人提交的工单")
    for key, value in req.model_dump(exclude_none=True).items(): setattr(row, key, value)
    db.commit(); db.refresh(row)
    return ok(repair_to_dict(row))

@app.delete("/api/repairs/{order_id}")
def delete_repair(order_id: str, request: Request, db: Session = Depends(db_dep)):
    if request.headers.get("x-user-role") != "admin": raise HTTPException(403, "仅管理员可以删除工单")
    row = db.query(RepairOrder).filter(RepairOrder.id == order_id.upper()).first()
    if not row: raise HTTPException(404, "未找到该工单")
    db.delete(row); db.commit(); return ok({"id": order_id.upper()})

@app.get("/api/admin/knowledge/documents")
def knowledge_documents(request: Request, db: Session = Depends(db_dep)):
    require_admin(request)
    rows = db.query(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc()).all()
    return ok([{"id": x.id, "title": x.title, "source_type": x.source_type, "source": x.source,
                "status": x.status, "chunk_count": x.chunk_count, "error": x.error,
                "created_at": x.created_at.isoformat() if x.created_at else None} for x in rows])

@app.post("/api/admin/knowledge/text")
def add_knowledge_text(req: KnowledgeTextRequest, request: Request, db: Session = Depends(db_dep)):
    require_admin(request)
    return ok(persist_knowledge(db, req.title, "text", "手动录入", req.content), "资料已写入向量知识库")

@app.post("/api/admin/knowledge/pdf")
async def add_knowledge_pdf(request: Request, title: str = Form(...), file: UploadFile = File(...), db: Session = Depends(db_dep)):
    require_admin(request)
    if not file.filename.lower().endswith(".pdf") or file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(415, "仅支持 PDF 文件")
    content = await file.read(10_000_001)
    if len(content) > 10_000_000:
        raise HTTPException(413, "PDF 文件不能超过 10 MB")
    try:
        text = extract_pdf(content)
    except Exception as exc:
        raise HTTPException(422, f"PDF 解析失败：{exc}")
    return ok(persist_knowledge(db, title, "pdf", file.filename, text), "PDF 已写入向量知识库")

@app.post("/api/admin/knowledge/web")
def add_knowledge_web(req: KnowledgeWebRequest, request: Request, db: Session = Depends(db_dep)):
    require_admin(request)
    try:
        content = extract_web(req.url)
    except Exception as exc:
        raise HTTPException(422, f"网页抓取失败：{exc}")
    return ok(persist_knowledge(db, req.title, "web", req.url, content), "网页内容已写入向量知识库")

@app.delete("/api/admin/knowledge/documents/{document_id}")
def delete_knowledge_document(document_id: str, request: Request, db: Session = Depends(db_dep)):
    require_admin(request)
    row = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
    if not row:
        raise HTTPException(404, "未找到该知识资料")
    try:
        delete_document_vectors(document_id)
    except Exception as exc:
        raise HTTPException(503, f"向量删除失败，资料记录已保留：{exc}")
    db.delete(row)
    db.commit()
    return ok({"id": document_id}, "知识资料及向量片段已删除")
