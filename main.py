import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Import router จากไฟล์ที่เราแยกไว้
from routes.get import router as get_router
from routes.post import router as post_router

logging.basicConfig(level=logging.INFO)

app = FastAPI()

# Mount Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# รวม Router เข้ากับแอปหลัก
app.include_router(get_router)
app.include_router(post_router)