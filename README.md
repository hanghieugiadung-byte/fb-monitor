# FB Monitor 🔍 (fbn Edition)

Web App chuyên nghiệp chuyên **giám sát bài viết nhóm Facebook, lọc từ khóa và bắn thông báo tới Telegram**, xây dựng theo chuẩn kiến trúc và tính năng của repo **[viseshrp/fbn](https://github.com/viseshrp/fbn)**.

---

## 🌟 Tính năng giống hệt `viseshrp/fbn` nhưng có giao diện Web trực quan

| Tính năng trong `fbn` | Cách hoạt động trên Web App này |
|---|---|
| **`fbn bootstrap`** (Nhập Cookie) | 🔑 Dán Cookie trực tiếp trên Web UI (hỗ trợ cả chuỗi Header `c_user=...; xs=...` lẫn JSON từ Cookie-Editor). Không cần gõ lệnh terminal. |
| **`fbn doctor`** (Chẩn đoán) | 🩺 Nút **"Chẩn đoán (Doctor)"** kiểm tra tự động 3 thành phần: Chromium Browser, Trạng thái Cookie Facebook (có sống không, ID tài khoản nào) và Kết nối Telegram. |
| **`fbn check`** (Quét 1 lần) | 🚀 Nút **"Quét ngay (Check)"** quét bài viết ngay lập tức và hiển thị **Live Console log thời gian thực** trên màn hình. Hỗ trợ cả chế độ **Dry Run** (quét thử không gửi tin). |
| **`fbn monitor`** (Giám sát nền) | 🔄 Công tắc **BẬT / TẮT Giám sát tự động** chạy nền với chu kỳ tùy chỉnh (5, 10, 15, 30, 60 phút/lần). |
| **Apprise / Telegram Notification** | 📲 Gửi tin nhắn Telegram HTML card đẹp mắt, kèm nút Inline Button `[🔗 Xem bài viết gốc]` trỏ trực tiếp đến bài viết và `[👤 Bài viết của tác giả]` trong nhóm. Có nút **"Gửi tin nhắn kiểm tra"** ngay trên giao diện. |
| **Target Group & Keywords** | 👥 Quản lý danh sách nhóm theo dõi (URL hoặc Group ID). Hỗ trợ lọc theo từ khóa, hoặc **để trống từ khóa để theo dõi 100% bài viết mới của nhóm** (chuẩn fbn). Hỗ trợ chọn lọc nhóm & từ khóa khi quét. |
| **Group Discovery** | 🔍 Tự động tìm kiếm nhóm theo chủ đề và quy mô, hiển thị 2 cột thao tác: **Tham gia nhóm** và **Thêm vào giám sát**. Sau khi bấm chọn, liên kết sẽ tự động ẩn đi và đánh dấu hoàn thành. |
| **Author Post Link** | 👤 Link tên tác giả trỏ trực tiếp đến danh sách tất cả các bài viết của tác giả đó trong nhóm (`/groups/{id}/user/{uid}/` hoặc tìm kiếm tác giả trong nhóm). |
| **Seen Posts Storage** | 📋 Cơ sở dữ liệu SQLite chống trùng lặp (`seen_posts`), đảm bảo mỗi bài viết chỉ gửi 1 lần duy nhất. Có nút xóa danh sách bài đã lưu để quét lại từ đầu. |

---

## 🚀 Hướng dẫn khởi chạy nhanh

### Bước 1: Chạy ứng dụng
Mở Terminal / PowerShell tại thư mục `fb-monitor` và gõ:
```bash
python main.py
```
Màn hình sẽ hiển thị:
```text
INFO: Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### Bước 2: Truy cập Web App
Mở trình duyệt Web truy cập: 👉 **`http://localhost:8000`**

---

## 📖 Hướng dẫn sử dụng chi tiết (3 bước đơn giản)

### 1️⃣ Bước 1: Cấu hình Cookie & Telegram (Tab ⚙️ Cấu hình)
1. **Lấy Cookie Facebook:**
   - Dùng trình duyệt mở Facebook (khuyên dùng tài khoản phụ).
   - Dùng extension **Cookie-Editor** (hoặc J2TEAM) → bấm **Export** → chọn **Header String** (dạng `c_user=...; xs=...;`) hoặc **JSON**.
   - Dán vào ô Cookie và bấm **Lưu Cookie**.
2. **Cấu hình Telegram:**
   - Nhập **Telegram Bot Token** (lấy từ `@BotFather`).
   - Nhập **Telegram Chat ID** (lấy từ `@userinfobot`).
   - Bấm **Gửi tin nhắn kiểm tra** để xác nhận bot hoạt động.
   - Bấm **Lưu Telegram**.

### 2️⃣ Bước 2: Thêm Nhóm & Từ khóa (Tab 👥 Nhóm & Từ khóa)
- Nhập Tên gợi nhớ và Link nhóm Facebook (VD: `https://www.facebook.com/groups/123456789`).
- Nhập từ khóa bạn muốn theo dõi (VD: `tuyển dụng, mua bán, freelancer`).
- *Lưu ý: Nếu không thêm từ khóa nào, hệ thống sẽ theo dõi tất cả bài viết mới trong nhóm.*

### 3️⃣ Bước 3: Kiểm tra & Bật Giám sát (Tab 📊 Dashboard)
- Bấm **"🩺 Chẩn đoán (Doctor)"**: Xem hệ thống báo xanh toàn bộ.
- Bấm **"🚀 Quét ngay (Check)"**: Xem tiến trình cào bài viết chạy trực tiếp trong cửa sổ Console Output màu đen.
- Bấm nút **"Bật"** tại thanh trạng thái trên cùng để kích hoạt chế độ **Giám sát tự động 24/7**!

---

## 🐳 Triển khai bằng Docker & Chạy Web 24/7

Dự án đã được đóng gói hoàn chỉnh bằng **Docker Compose** dựa trên Playwright image chính thức (`mcr.microsoft.com/playwright/python:v1.49.0-noble`), hỗ trợ bảo vệ mật khẩu đăng nhập và lưu trữ cơ sở dữ liệu bền vững:

```bash
# 1. Khởi chạy nền 24/7 tự động restart
docker compose up -d --build

# 2. Xem logs thời gian thực
docker compose logs -f fb-monitor
```

Xem hướng dẫn chi tiết từng bước (Cài đặt VPS, Tên miền riêng, SSL HTTPS miễn phí, Cloudflare Tunnel, Railway) tại file:
👉 **[DEPLOY_GUIDE.md](DEPLOY_GUIDE.md)**
