from fastapi import FastAPI, Request
import aioredis
import aiofiles
import io
from fastapi.templating import Jinja2Templates
from PIL import Image
from werkzeug.utils import secure_filename
import debugpy
from pathlib import Path
from fastapi import File, UploadFile
from fastapi.responses import RedirectResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

debugpy.listen(("0.0.0.0", 5678))

UPLOAD_FOLDER = Path("./uploads")
THUMBNAIL_FOLDER = UPLOAD_FOLDER / "thumbnails"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
MAX_CONTENT_LENGTH = 4_000_000

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="static")

redis = aioredis.Redis(host="redis", port=6379)


@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request},
    )


def allowed_file(filename: str):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_media_type(filename):
    ext = str(filename).split(".")[-1]
    if ext == "jpg":
        ext = "jpeg"
    return ext


def get_mime_type(filename):
    return f"image/{get_media_type(filename)}"


def process(img: Image) -> Image:
    basewidth = 300
    wpercent = basewidth / float(img.size[0])
    hsize = int((float(img.size[1]) * float(wpercent)))
    img_processed = img.resize((basewidth, hsize), Image.ANTIALIAS)
    return img_processed


def get_img_bytes(img: Image, media_type: str) -> bytes:
    byte_stream = io.BytesIO()
    img.save(byte_stream, media_type)
    return byte_stream.getvalue()


async def save_processed(img: Image, folder: Path, filename: str, suffix: str):
    media_type = get_media_type(filename)
    dot_pos = filename.rfind(".")
    filepath_processed = folder / f"{filename[:dot_pos]}-{suffix}{filename[dot_pos:]}"
    img_bytes = get_img_bytes(img, media_type)
    async with aiofiles.open(filepath_processed, "wb") as f:
        await f.write(img_bytes)
    return filepath_processed


async def save_paths(filename: str, filepath_processed: Path, filepath_thumbnail: Path):
    await redis.hset(
        filename,
        mapping={
            "filename": filename,
            "filepath_processed": str(filepath_processed),
            "filepath_thumbnail": str(filepath_thumbnail),
        },
    )


async def get_paths(key) -> dict:
    filename = await redis.hget(key, "filename")
    if filename:
        return {
            "filename": filename.decode("utf-8"),
            "filepath_processed": (await redis.hget(key, "filepath_processed")).decode(
                "utf-8"
            ),
            "filepath_thumbnail": (await redis.hget(key, "filepath_thumbnail")).decode(
                "utf-8"
            ),
        }
    else:
        return {}


async def get_all_paths() -> list:
    image_paths = []
    next_index = 1
    while next_index:
        next_index, keys = await redis.scan(_type="HASH")
        for key in keys:
            image_paths.append(await get_paths(key))
    return image_paths


@app.get("/upscale", response_class=HTMLResponse)
async def upscale(request: Request):
    image_paths = await get_all_paths()
    return templates.TemplateResponse(
        "upscale.html",
        {
            "request": request,
            "image_paths": image_paths,
        },
    )


@app.post("/upscale", response_class=HTMLResponse)
async def uploadfile(request: Request, file: UploadFile = File(...)):
    if file.filename == "":
        return RedirectResponse(url="/", status_code=301)
    if allowed_file(file.filename):
        contents = file.file.read(MAX_CONTENT_LENGTH)
        if file.file.read(1):
            return {"message": f"File is larger than {MAX_CONTENT_LENGTH}"}
        file.file.close()
        filename = secure_filename(file.filename)
        async with aiofiles.open(UPLOAD_FOLDER / filename, "wb") as f:
            await f.write(contents)
        img = Image.open(UPLOAD_FOLDER / filename)
        img_processed = process(img)
        filepath_processed = await save_processed(
            img_processed, UPLOAD_FOLDER, filename, "processed"
        )
        img_thumbnail = img.copy()
        img_thumbnail.thumbnail((100, 100))
        filepath_thumbnail = await save_processed(
            img_thumbnail, THUMBNAIL_FOLDER, filename, "thumbnail"
        )
        await save_paths(filename, filepath_processed, filepath_thumbnail)
        image_paths = await get_all_paths()
        return templates.TemplateResponse(
            "upscale.html",
            {
                "request": request,
                "image_paths": image_paths,
            },
        )
    return RedirectResponse("/", status_code=301)


@app.get("/download/{name}")
async def download(name: str):
    path = (await get_paths(name)).get("filepath_processed")
    if path:
        return FileResponse(path, media_type=get_mime_type(name))
    else:
        return "Not found!"
