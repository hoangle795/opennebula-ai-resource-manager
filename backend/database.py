import sqlite3
import os
import json
from contextlib import contextmanager
from datetime import datetime

# File dữ liệu sẽ được lưu cùng thư mục với file code này
DB_PATH = os.path.join(os.path.dirname(__file__), "agent_logs.db")

# ── THÊM MỚI: thư mục lưu log JSON mỗi khi demo kết thúc ────────────────────
LOGS_EXPORT_DIR = os.path.join(os.path.dirname(__file__), "demo_logs")
os.makedirs(LOGS_EXPORT_DIR, exist_ok=True)


@contextmanager
def _conn():
    """Bộ quản lý kết nối: tự động Commit khi xong, Rollback nếu lỗi và luôn đóng kết nối."""
    conn = sqlite3.connect(DB_PATH)
    # Không dùng Row_factory ở đây để dữ liệu trả về dạng mảng thuần túy, khớp với JS log[1], log[2]
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Khởi tạo bảng log nếu chưa tồn tại"""
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                level      TEXT    NOT NULL,
                message    TEXT    NOT NULL,
                timestamp  TEXT    NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_logs_id ON ai_logs (id DESC)"
        )
    print("✅ Database initialized successfully.")


def add_log(level: str, message: str):
    """Ghi một dòng log mới vào database"""
    ts = datetime.now().strftime("%H:%M:%S")
    with _conn() as conn:
        conn.execute(
            "INSERT INTO ai_logs (level, message, timestamp) VALUES (?, ?, ?)",
            (level, message, ts),
        )


def get_recent_logs(limit: int = 15) -> list:
    """
    Lấy danh sách log mới nhất. 
    Dữ liệu trả về dạng List of Lists để Frontend truy cập bằng log[1], log[2]...
    """
    with _conn() as conn:
        # Thứ tự cột RẤT QUAN TRỌNG: id(0), level(1), message(2), timestamp(3)
        cursor = conn.execute(
            "SELECT id, level, message, timestamp FROM ai_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()

    # Chuyển đổi từ dữ liệu SQLite thành List thuần túy cho JSON API
    return [list(row) for row in rows]


def purge_old_logs(keep: int = 1_000):
    """Dọn dẹp database, chỉ giữ lại số lượng log nhất định"""
    with _conn() as conn:
        conn.execute(
            """
            DELETE FROM ai_logs
            WHERE id NOT IN (
                SELECT id FROM ai_logs ORDER BY id DESC LIMIT ?
            )
            """,
            (keep,),
        )


# ══════════════════════════════════════════════════════════════════════════════
# THÊM MỚI: Export log ra file JSON (dùng cho demo/luận văn)
# ══════════════════════════════════════════════════════════════════════════════

def get_latest_log_id() -> int:
    """Lấy id log mới nhất hiện tại — dùng làm điểm mốc 'bắt đầu demo'."""
    with _conn() as conn:
        cursor = conn.execute("SELECT MAX(id) FROM ai_logs")
        row = cursor.fetchone()
    return row[0] or 0


def get_all_logs_since(since_id: int = 0) -> list:
    """Lấy toàn bộ log có id > since_id (dùng để export đúng phần log của 1 lần demo)."""
    with _conn() as conn:
        cursor = conn.execute(
            "SELECT id, level, message, timestamp FROM ai_logs WHERE id > ? ORDER BY id ASC",
            (since_id,),
        )
        rows = cursor.fetchall()
    return [
        {"id": r[0], "level": r[1], "message": r[2], "timestamp": r[3]}
        for r in rows
    ]


def export_logs_to_json(since_id: int = 0, label: str = "demo") -> str:
    """
    Xuất log (từ since_id tới hiện tại) ra file JSON trong thư mục demo_logs/.
    Tên file tự động kèm timestamp để không bị đè lên lần demo trước.
    Trả về đường dẫn file đã lưu.
    """
    logs = get_all_logs_since(since_id)
    ts_str   = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{label}_{ts_str}.json"
    filepath = os.path.join(LOGS_EXPORT_DIR, filename)

    payload = {
        "exported_at": datetime.now().isoformat(),
        "label": label,
        "log_count": len(logs),
        "logs": logs,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return filepath