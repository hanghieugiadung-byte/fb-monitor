# HƯỚNG DẪN ĐÓNG GÓI VÀ TRIỂN KHAI LÊN WEB CHẠY 24/7 (FB MONITOR)

Tài liệu này cung cấp các giải pháp đóng gói toàn diện bằng **Docker Container** (chuẩn theo kiến trúc `viseshrp/fbn`) để đưa ứng dụng **FB Monitor** lên môi trường Web công cộng và duy trì hoạt động quét tự động liên tục 24/7/365.

---

## 📌 Tổng Quan Kiến Trúc Đóng Gói
* **Base Image:** `mcr.microsoft.com/playwright/python:v1.49.0-noble` (Đã tích hợp sẵn Python 3.12, Chromium Headless và đầy đủ thư viện font, hệ điều hành).
* **Dữ liệu bền vững (Persistent Volume):** Toàn bộ cơ sở dữ liệu (`fb_monitor.db`), tài khoản Facebook, từ khóa, kho nhóm và lịch quét được lưu tại `./data:/app/data`, đảm bảo không bao giờ bị mất khi restart hay update container.
* **Tự động phục hồi 24/7:** `restart: unless-stopped` giúp ứng dụng tự động chạy lại ngay lập tức nếu container bị tắt hoặc máy chủ khởi động lại.
* **Bảo mật truy cập Web:** Hỗ trợ cấu hình `ADMIN_PASSWORD` (xác thực HTTP Basic Auth) để ngăn chặn người lạ truy cập vào Web Dashboard và xem Cookie tài khoản của bạn.

---

## 🚀 PHƯƠNG ÁN 1: Triển Khai Trên Máy Chủ VPS Linux (Khuyên Dùng Nhất)

Đây là phương án chuẩn nhất cho sản phẩm thực tế: Chi phí thuê VPS rất rẻ (~70.000đ - 100.000đ/tháng trên Hetzner, DigitalOcean, Linode, Vultr hoặc dùng gói Miễn phí vĩnh viễn của **Oracle Cloud Free Tier**).

### Bước 1: Kết nối vào VPS qua SSH
```bash
ssh root@<IP_VPS_CUA_BAN>
```

### Bước 2: Cài đặt Docker & Docker Compose (Nếu VPS chưa có)
Chạy lệnh 1 dòng chính thức từ Docker:
```bash
curl -fsSL https://get.docker.com | sh
```

### Bước 3: Đưa mã nguồn lên VPS
Bạn có thể clone repo từ GitHub hoặc upload thư mục `fb-monitor`:
```bash
# Tạo thư mục làm việc
mkdir -p /opt/fb-monitor
cd /opt/fb-monitor

# Clone code từ repo của bạn (hoặc dùng scp để copy từ máy tính lên)
# git clone <URL_REPO_CUA_BAN> .
```

### Bước 4: Cấu hình Mật khẩu Quản trị
Tạo file `.env` trên VPS để đặt mật khẩu bảo vệ Dashboard:
```bash
nano .env
```
Nội dung file `.env`:
```env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=MatKhauBaoMatCuaBan123@#
```
*(Nhấn `Ctrl + O` rồi `Enter` để lưu, `Ctrl + X` để thoát).*

### Bước 5: Khởi chạy 24/7 bằng Docker Compose
```bash
docker compose up -d --build
```

Kiểm tra trạng thái container:
```bash
docker compose ps
docker compose logs -f fb-monitor
```

Bây giờ bạn có thể truy cập Web Dashboard tại: **`http://<IP_VPS_CUA_BAN>:8000`** và nhập tài khoản `admin` cùng mật khẩu bạn đã đặt ở Bước 4.

---

### Bước 6 (Tùy chọn): Cài đặt Tên Miền Riêng & Chứng chỉ SSL HTTPS Miễn Phí (Nginx + Let's Encrypt)
Để truy cập chuyên nghiệp bằng tên miền dạng `https://fb.tenmiencuaban.com`:

1. **Trỏ bản ghi DNS:** Thêm bản ghi `A` trỏ tên miền về IP của VPS.
2. **Cài đặt Nginx & Certbot trên VPS:**
```bash
apt update && apt install -y nginx certbot python3-certbot-nginx
```

3. **Tạo cấu hình Nginx:**
```bash
nano /etc/nginx/sites-available/fb-monitor
```
Dán nội dung:
```nginx
server {
    server_name fb.tenmiencuaban.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }
}
```

4. **Kích hoạt và cấp chứng chỉ SSL HTTPS miễn phí:**
```bash
ln -s /etc/nginx/sites-available/fb-monitor /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d fb.tenmiencuaban.com
```
Certbot sẽ tự động gia hạn chứng chỉ HTTPS vĩnh viễn. Giờ bạn có thể mở `https://fb.tenmiencuaban.com` ở bất kỳ đâu trên điện thoại hay máy tính!

---

## 🌐 PHƯƠNG ÁN 2: Chạy Ngay Trên Máy Tính Cá Nhân & Đưa Ra Web Miễn Phí (Cloudflare Tunnel)

Nếu bạn không muốn thuê VPS và muốn tận dụng máy tính/laptop hoặc Mini PC ở nhà để chạy 24/7:

1. **Khởi động ứng dụng bằng Docker trên máy tính:**
```powershell
docker compose up -d --build
```

2. **Cài đặt Cloudflare Tunnel (Miễn phí 100%):**
   * Tải công cụ `cloudflared` từ [Cloudflare](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).
   * Chạy lệnh tạo đường hầm HTTPS ra ngoài Internet ngay lập tức:
   ```powershell
   cloudflared tunnel --url http://localhost:8000
   ```
   * Cloudflare sẽ cung cấp cho bạn một đường dẫn HTTPS công khai dạng:
     `https://random-name.trycloudflare.com`
   * Bạn có thể mở link này trên điện thoại hoặc chia sẻ cho người khác truy cập mà **không cần mở port modem, không cần IP tĩnh**, bảo mật tuyệt đối qua hạ tầng Cloudflare.

---

## ☁️ PHƯƠNG ÁN 3: Triển Khai Lên Nền Tảng Cloud (Railway / Render / Fly.io)

1. Push toàn bộ mã nguồn lên GitHub của bạn.
2. Đăng nhập vào [Railway.app](https://railway.app/) hoặc [Render.com](https://render.com/).
3. Chọn **New Project** -> **Deploy from GitHub repo**.
4. Nền tảng sẽ tự động nhận diện `Dockerfile` và tiến hành build.
5. **Cấu hình Volume (Quan trọng):**
   * Trong phần cài đặt Service -> **Volumes**, tạo một Volume gắn vào đường dẫn: `/app/data` (kích thước 1GB là đủ).
6. **Cấu hình Environment Variables:**
   * `ADMIN_USERNAME`: `admin`
   * `ADMIN_PASSWORD`: `<mật_khẩu_của_bạn>`
   * `TZ`: `Asia/Ho_Chi_Minh`
7. Nhấn Deploy. Railway/Render sẽ cấp cho bạn một tên miền HTTPS miễn phí để sử dụng 24/7.

---

## 📋 Quản Lý & Bảo Trì Ứng Dụng Khi Chạy 24/7

* **Xem log cào dữ liệu thời gian thực:**
  ```bash
  docker compose logs -f fb-monitor
  ```
* **Khởi động lại ứng dụng:**
  ```bash
  docker compose restart fb-monitor
  ```
* **Cập nhật mã nguồn mới:**
  ```bash
  git pull
  docker compose up -d --build
  ```
* **Sao lưu dữ liệu:**
  Chỉ cần copy thư mục `./data/fb_monitor.db` là bạn đã sao lưu toàn bộ danh sách tài khoản, cookie, nhóm và từ khóa.
