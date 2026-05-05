# 数据库配置
# app/infra/db.py


import sqlite3
import os
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_init")

# 1. 路径逻辑
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, "data", "app.db")

# 2. 数据库配置定义（全量字段对齐）
TABLE_SCHEMAS = {
    "users": {
        "primary_key": "user_id TEXT PRIMARY KEY",
        "columns": {
            "email": "TEXT",             # 👈 新增：存储邮箱，设为唯一
            "user_id": "TEXT",
            "credits": "INTEGER DEFAULT 0",
            "is_admin": "INTEGER NOT NULL DEFAULT 0",
            "superadmin": "INTEGER NOT NULL DEFAULT 0",
            "last_daily_grant": "INTEGER DEFAULT 0", # 👈 匹配 credit_repo 的时间戳逻辑
            "created_at": "REAL NOT NULL"           # 👈 修复 create_user 报错
        }
    },
    "jobs": {
        "primary_key": "job_id TEXT PRIMARY KEY",
        "columns": {
            "user_id": "TEXT NOT NULL",
            "type": "TEXT NOT NULL",
            "status": "TEXT NOT NULL",
            "price": "REAL DEFAULT 0",
            "context": "TEXT",       # 存储 JSON 字符串
            "events": "TEXT",        # 存储 JSON 字符串
            "error": "TEXT",
            "progress": "INTEGER DEFAULT 0",
            "last_msg": "TEXT",
            "result": "TEXT",        # 👈 任务结果字段
            "created_at": "REAL NOT NULL",
            "updated_at": "REAL"
        }
    },
    "credit_logs": {
        "primary_key": "id INTEGER PRIMARY KEY AUTOINCREMENT",
        "columns": {
            "user_id": "TEXT NOT NULL",
            "delta": "INTEGER NOT NULL",
            "reason": "TEXT NOT NULL",
            "created_at": "REAL NOT NULL"
        }
    },
    "job_events": {
        "primary_key": "id INTEGER PRIMARY KEY AUTOINCREMENT",
        "columns": {
            "job_id": "TEXT NOT NULL",
            "type": "TEXT",
            "msg": "TEXT",
            "progress": "INTEGER",
            "created_at": "REAL NOT NULL"
        }
    }
}

# 索引定义（针对 3M 带宽和高频查询优化）
INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_credit_logs_user_id ON credit_logs(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id)", # 方便查询用户的任务列表
    "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)"    # 方便 Worker 扫描 queued 任务
]


def get_conn() -> sqlite3.Connection:
    """获取数据库连接，包含高性能配置"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=20)
    # 性能优化：开启 WAL 模式 (支持并发读写)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """系统化初始化与自动迁移"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    cur = conn.cursor()

    try:
        for table_name, schema in TABLE_SCHEMAS.items():
            # 1. 创建表（如果不存在）
            pk = schema["primary_key"]
            cur.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({pk})")

            # 2. 检查并补齐字段
            cur.execute(f"PRAGMA table_info({table_name})")
            existing_cols = [info[1] for info in cur.fetchall()]

            for col_name, col_def in schema["columns"].items():
                if col_name not in existing_cols:
                    try:
                        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}")
                        logger.info(f"✅ 已补齐表 {table_name} 的字段: {col_name}")
                    except sqlite3.OperationalError as e:
                        # 忽略重复添加列的错误
                        if "duplicate column name" not in str(e).lower():
                            logger.error(f"❌ 补齐字段 {col_name} 失败: {e}")

        # 3. 初始化索引
        for idx_sql in INDEXES:
            cur.execute(idx_sql)

        conn.commit()
        logger.info("🚀 数据库系统化重构/初始化完成 (Users, Jobs, Credits 字段已全部同步)")
    except Exception as e:
        conn.rollback()
        logger.error(f"🚨 数据库初始化崩溃: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()