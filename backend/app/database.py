from pathlib import Path
from sqlalchemy import create_engine, update
from sqlalchemy.orm import declarative_base, sessionmaker
import logging
from .config import BASE_DIR, DB_PATH

db_file = Path(DB_PATH)
if not db_file.is_absolute():
    db_file = BASE_DIR / db_file
db_file.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(
    f"sqlite:///{db_file}",
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()

def init_db():
    from . import models
    Base.metadata.create_all(bind=engine)
    from .knowledge import ensure_vector_store
    ensure_vector_store()
    logging.getLogger(__name__).info("SQLite database: %s", db_file.resolve())
    from .models import KnowledgeDocument
    db = SessionLocal()
    try:
        db.execute(update(KnowledgeDocument).where(KnowledgeDocument.status == "indexing").values(status="failed", error="服务在资料索引完成前中断，请重新提交资料"))
        db.commit()
    finally:
        db.close()
    seed_demo_data()

def seed_demo_data():
    from .models import Notice, Facility
    db = SessionLocal()
    try:
        if db.query(Notice).count() == 0:
            db.add_all([
                Notice(title="春季集中供水检修通知", content="4月12日 09:00-12:00 进行供水泵房检修，请提前储水。", category="停水通知"),
                Notice(title="电动车充电安全提醒", content="请勿在楼道、消防通道停放或充电，违规车辆将被劝离。", category="安全提醒"),
                Notice(title="物业服务中心节假日安排", content="节假日服务时间为 09:00-17:00，紧急报修电话 400-800-1234。", category="服务安排"),
            ])
        if db.query(Facility).count() == 0:
            db.add_all([
                Facility(name="社区服务中心", location="1号门旁", hours="工作日 09:00-18:00", description="咨询、缴费、证明办理"),
                Facility(name="快递驿站", location="3号楼负一层", hours="每天 08:00-21:00", description="包裹代收与寄件"),
                Facility(name="公共健身区", location="小区东南角", hours="06:00-22:00", description="健身器材和休息座椅"),
            ])
        db.commit()
    finally:
        db.close()
