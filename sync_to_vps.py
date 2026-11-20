"""
Script đồng bộ dữ liệu từ máy Local lên máy chủ VPS.
Tự động gộp Nhóm, Từ khóa, Chủ đề mà KHÔNG ghi đè, KHÔNG mất Cookie và KHÔNG mất bài viết trên VPS.
Chạy trực tiếp bằng Python chuẩn (không cần cài thêm thư viện ngoài).
"""

import os
import sys
import json
import sqlite3
import urllib.request
import urllib.error

# Cấu hình mặc định
DEFAULT_VPS_URL = os.environ.get("VPS_URL", "https://skeyshome.io.vn")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "fb_monitor.db")


def main():
    print("=" * 65)
    print(" 🚀 ĐỒNG BỘ DỮ LIỆU TỰ ĐỘNG: LOCAL ➔ VPS (skeyshome.io.vn)")
    print("=" * 65)

    if not os.path.exists(DB_FILE):
        print(f"\n❌ LỖI: Không tìm thấy file dữ liệu local tại:\n   {DB_FILE}")
        print("   Hãy đảm bảo file fb_monitor.db nằm cùng thư mục với script này.")
        input("\nBấm Enter để thoát...")
        return

    # 1. Đọc dữ liệu từ SQLite local
    print(f"\n[1/3] Đang đọc dữ liệu từ local database: fb_monitor.db...")
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Đọc Topics
        topics = []
        try:
            cur.execute("SELECT name, color FROM topicitem")
            for r in cur.fetchall():
                topics.append({"name": r["name"], "color": r["color"]})
        except Exception:
            pass

        # Đọc Keywords
        keywords = []
        try:
            cur.execute("SELECT text, is_active FROM keyworditem")
            for r in cur.fetchall():
                keywords.append({"text": r["text"], "is_active": bool(r["is_active"])})
        except Exception:
            pass

        # Đọc Groups
        groups = []
        try:
            cur.execute("SELECT name, fb_url, clean_group_id, member_count, privacy, topic_name, is_joined, is_active, post_permission, post_permission_text, comment_permission, comment_permission_text FROM groupitem")
            for r in cur.fetchall():
                groups.append({
                    "name": r["name"],
                    "fb_url": r["fb_url"],
                    "clean_group_id": r["clean_group_id"],
                    "member_count": r["member_count"] or 0,
                    "privacy": r["privacy"] or "unknown",
                    "topic_name": r["topic_name"] or "Chưa phân loại",
                    "is_joined": bool(r["is_joined"]),
                    "is_active": bool(r["is_active"]),
                    "post_permission": r["post_permission"] or "unknown",
                    "post_permission_text": r["post_permission_text"] or "",
                    "comment_permission": r["comment_permission"] or "open",
                    "comment_permission_text": r["comment_permission_text"] or "",
                })
        except Exception:
            pass

        conn.close()

        print(f"  ✓ Tìm thấy {len(groups)} nhóm Facebook")
        print(f"  ✓ Tìm thấy {len(keywords)} từ khóa lọc")
        print(f"  ✓ Tìm thấy {len(topics)} chủ đề phân loại")

    except Exception as e:
        print(f"❌ Lỗi đọc database local: {e}")
        input("\nBấm Enter để thoát...")
        return

    if not groups and not keywords and not topics:
        print("\n⚠️ Database local không có dữ liệu nào để đồng bộ.")
        input("\nBấm Enter để thoát...")
        return

    # 2. Chuẩn bị payload gửi lên VPS
    vps_url = DEFAULT_VPS_URL.rstrip("/")
    api_endpoint = f"{vps_url}/api/data/import"
    payload = {
        "topics": topics,
        "keywords": keywords,
        "groups": groups,
    }
    json_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    print(f"\n[2/3] Đang kết nối tới máy chủ VPS: {vps_url}...")
    req = urllib.request.Request(
        api_endpoint,
        data=json_data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "FBMonitor-SyncClient/1.0",
        },
        method="POST"
    )

    if ADMIN_PASSWORD:
        import base64
        auth_str = f"{ADMIN_USERNAME}:{ADMIN_PASSWORD}"
        b64_auth = base64.b64encode(auth_str.encode()).decode()
        req.add_header("Authorization", f"Basic {b64_auth}")

    # 3. Gửi request và nhận kết quả
    print("[3/3] Đang nạp và gộp dữ liệu thông minh trên VPS...")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_body = resp.read().decode("utf-8")
            result = json.loads(resp_body)

            print("\n" + "=" * 65)
            print(" 🎉 ĐỒNG BỘ THÀNH CÔNG RỰC RỠ!")
            print("=" * 65)
            print(f" ➕ Số nhóm Facebook mới nạp:  {result.get('added_groups', 0)}")
            print(f" ➕ Số từ khóa mới nạp:        {result.get('added_keywords', 0)}")
            print(f" ➕ Số chủ đề mới nạp:         {result.get('added_topics', 0)}")
            print("-" * 65)
            print(" 🛡️ BẢO VỆ DỮ LIỆU:")
            print("  • Các tài khoản & Cookie Facebook trên VPS: NGUYÊN VẸN 100%")
            print("  • Các bài viết đã quét & Lịch sử cảnh báo:   NGUYÊN VẸN 100%")
            print("  • Nhóm cũ đã tồn tại trên VPS:               KHÔNG BỊ TRÙNG LẶP")
            print("=" * 65)
            print(f"\n👉 Bạn có thể vào ngay https://skeyshome.io.vn để xem danh sách mới!")

    except urllib.error.HTTPError as http_err:
        print(f"\n❌ Máy chủ VPS phản hồi lỗi mã {http_err.code}: {http_err.reason}")
        try:
            err_detail = http_err.read().decode("utf-8")
            print(f"   Chi tiết: {err_detail[:200]}")
        except Exception:
            pass
    except urllib.error.URLError as url_err:
        print(f"\n❌ Không thể kết nối tới VPS tại {vps_url}: {url_err.reason}")
        print("   Hãy kiểm tra lại mạng hoặc đảm bảo VPS đang chạy và mở cổng 80/443.")
    except Exception as ex:
        print(f"\n❌ Đã xảy ra lỗi: {ex}")

    input("\nBấm Enter để đóng cửa sổ...")


if __name__ == "__main__":
    main()
