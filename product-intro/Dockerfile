# syntax=docker/dockerfile:1
FROM python:3.11-slim

# 設定工作目錄
WORKDIR /app

# 先複製 requirements 以利 Docker 層快取
COPY requirements.txt .

# 安裝依賴套件
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# 複製所有程式碼
COPY . .

# 建立本地上傳目錄（Cloud Run 啟動時使用 local 模式）
RUN mkdir -p static/uploads static/images

# 開放埠號
EXPOSE 8080

# 啟動 Gunicorn 伺服器 (Cloud Run 需要 port 8080)
CMD exec gunicorn --bind :8080 --workers 2 --threads 8 --timeout 0 app:app
