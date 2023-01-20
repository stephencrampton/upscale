from fastapi import FastAPI
import aioredis
import aiofiles
import io
from PIL import Image
from werkzeug.utils import secure_filename
import os
import debugpy
from pathlib import Path
from fastapi import File, UploadFile
from fastapi.responses import RedirectResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles

debugpy.listen(("0.0.0.0", 5678))

UPLOAD_FOLDER = Path("./uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
MAX_CONTENT_LENGTH = 16_000_000

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

redis = aioredis.Redis(host="redis", port=6379)


@app.get("/")
async def home():
    return FileResponse("static/index.html")


@app.get("/hits")
async def read_hits():
    await redis.incr("hits")
    return {"Number of hits": await redis.get("hits")}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_media_type(filename):
    ext = filename.split(".")[-1]
    if ext == "jpg":
        ext = "jpeg"
    return ext


def get_mime_type(filename):
    return f"image/{get_media_type(filename)}"


@app.post("/")
async def uploadfile(file: UploadFile = File(...)):
    if file.filename == "":
        return RedirectResponse(url="/", status_code=301)
    if allowed_file(file.filename):
        contents = file.file.read(MAX_CONTENT_LENGTH)
        if file.file.read(1):
            return {"message": f"File is larger than {MAX_CONTENT_LENGTH}"}
        file.file.close()
        async with aiofiles.open(UPLOAD_FOLDER / file.filename, "wb") as f:
            await f.write(contents)
        filename = secure_filename(file.filename)
        basewidth = 300
        img = Image.open(UPLOAD_FOLDER / filename)
        wpercent = basewidth / float(img.size[0])
        hsize = int((float(img.size[1]) * float(wpercent)))
        img = img.resize((basewidth, hsize), Image.ANTIALIAS)
        dot_pos = filename.rfind(".")
        filename_resized = filename[:dot_pos] + "-resized" + filename[dot_pos:]
        filepath_resized = os.path.join(UPLOAD_FOLDER, filename_resized)
        byte_stream = io.BytesIO()
        img.save(byte_stream, get_media_type(filename_resized))
        img_bytes = byte_stream.getvalue()
        async with aiofiles.open(UPLOAD_FOLDER / filename_resized, "wb") as f:
            await f.write(img_bytes)
        return Response(content=img_bytes, media_type=get_mime_type(filename_resized))
    return RedirectResponse("/", status_code=301)


@app.get("/download/{name}")
async def download(name: str):
    return FileResponse(UPLOAD_FOLDER / name, media_type=get_mime_type(name))
