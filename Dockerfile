FROM python:3.11-slim

# ตั้งค่า Environment สำหรับ Python และ Timezone ไทย
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Bangkok

WORKDIR /app

# ติดตั้ง tzdata และตั้งค่าเวลาของระบบให้เป็นประเทศไทย
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# ติดตั้ง Python Dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# คัดลอกโค้ดระบบ
COPY database.py main.py ./
COPY routes/ ./routes/
COPY template/ ./template/
COPY static/ ./static/

# เปิดพอร์ต 8000
EXPOSE 8000

# ตรวจสอบความพร้อมของ Container
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

# รัน FastAPI ผ่าน Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
