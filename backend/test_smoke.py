import os
from pathlib import Path

os.environ["LLM_API_KEY"] = ""
os.environ["DB_PATH"] = "data/test_community.db"

test_db = Path(__file__).resolve().parent / "data" / "test_community.db"
if test_db.exists():
    test_db.unlink()

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, engine
from app.models import KnowledgeDocument, RepairDraft, RepairOrder
from unittest.mock import patch

with TestClient(app) as client:
    assert client.get("/").status_code == 200
    sid = client.post("/api/sessions", json={"title": "测试"}).json()["data"]["id"]
    res = client.post("/api/agent/chat", json={"session_id": sid, "message": "快递驿站在哪里？"})
    assert res.status_code == 200 and "快递驿站" in res.json()["data"]["reply"]

    # 多轮对话：首轮生成持久化草稿，补齐字段后写入 repair_orders。
    repair_sid = client.post("/api/sessions", json={"title": "多轮报修测试"}).json()["data"]["id"]
    first = client.post("/api/agent/chat", json={"session_id": repair_sid, "message": "我家厨房漏水，需要紧急报修"}).json()["data"]
    assert first["repair"]["status"] == "collecting"
    assert set(first["repair"]["missing_fields"]) == {"姓名", "联系电话", "详细位置"}
    second = client.post("/api/agent/chat", json={"session_id": repair_sid, "message": "我叫张三，电话13800000000，住在2号楼101室"}).json()["data"]
    assert second["repair"]["status"] == "created"
    order_id = second["repair"]["order"]["id"]
    assert client.get(f"/api/repairs/{order_id}").json()["data"]["status"] == "待受理"

    db = SessionLocal()
    try:
        assert db.query(RepairOrder).filter(RepairOrder.id == order_id).one().phone == "13800000000"
        assert db.query(RepairDraft).filter(RepairDraft.session_id == repair_sid).first() is None
    finally:
        db.close()

    # 工单必须跨数据库会话可读，不能只存在于当前请求的 ORM 对象中。
    db = SessionLocal()
    try:
        db.expire_all()
        assert db.query(RepairOrder).filter(RepairOrder.id == order_id).one().description
    finally:
        db.close()

    # 管理员知识资料接口必须写 SQLite 元数据并调用向量索引器；住户不得入库。
    denied = client.post("/api/admin/knowledge/text", headers={"X-User-Role": "resident"},
                         json={"title": "测试资料", "content": "社区访客服务时间为每天九点到十八点。"})
    assert denied.status_code == 403
    with patch("app.main.index_document", return_value=1) as index_mock:
        indexed = client.post("/api/admin/knowledge/text", headers={"X-User-Role": "admin"},
                              json={"title": "访客服务", "content": "社区访客服务时间为每天九点到十八点。"})
    assert indexed.status_code == 200 and indexed.json()["data"]["chunk_count"] == 1
    index_mock.assert_called_once()
    db = SessionLocal()
    try:
        saved = db.query(KnowledgeDocument).filter(KnowledgeDocument.title == "访客服务").one()
        assert saved.status == "ready" and saved.chunk_count == 1
    finally:
        db.close()
    with patch("app.agent.search_knowledge", return_value=["社区访客服务时间为每天九点到十八点。"]):
        answer = client.post("/api/agent/chat", json={"message": "访客服务时间是多少"}).json()["data"]
    assert "每天九点到十八点" in answer["reply"] and "search_knowledge" in answer["tools_used"]

    # 字段校验：手机号不合法时，独立创建接口必须拒绝。
    invalid = client.post("/api/repairs", json={"resident":"张三","phone":"123","location":"2号楼101","category":"水管","description":"厨房漏水","urgency":"紧急"})
    assert invalid.status_code == 422

    # 对话中的草稿允许显式取消，且不能生成 repair_orders。
    cancel_sid = client.post("/api/sessions", json={"title": "取消报修测试"}).json()["data"]["id"]
    client.post("/api/agent/chat", json={"session_id": cancel_sid, "message": "电梯坏了，我要报修"})
    cancelled = client.post("/api/agent/chat", json={"session_id": cancel_sid, "message": "不用报修了"}).json()["data"]
    assert cancelled["repair"]["status"] == "cancelled"
print("smoke tests passed")

engine.dispose()
db = SessionLocal()
try:
    assert db.query(RepairOrder).count() >= 1
    assert db.query(KnowledgeDocument).filter(KnowledgeDocument.title == "访客服务").one().status == "ready"
finally:
    db.close()
if test_db.exists():
    test_db.unlink()
