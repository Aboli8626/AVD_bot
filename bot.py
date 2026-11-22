
import os
import re
import uuid
import shutil
import logging
import asyncio
import threading

from pathlib import Path
from urllib.parse import urlparse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import yt_dlp


# ==================================================
# تنظیمات اصلی
# ==================================================

TOKEN = os.getenv("TOKEN")

MAX_UPLOAD_SIZE = 49 * 1024 * 1024

DOWNLOAD_DIR = Path("/tmp/video_downloader")

DOWNLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ==================================================
# دامنه‌های مجاز
# ==================================================

ALLOWED_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "instagram.com",
)


def is_supported_url(url):

    try:

        parsed = urlparse(url)

        host = (parsed.hostname or "").lower()

        if parsed.scheme not in ("http", "https"):
            return False

        for domain in ALLOWED_DOMAINS:

            if host == domain or host.endswith("." + domain):
                return True

        return False

    except Exception:

        return False


def extract_url(text):

    matches = re.findall(
        r"https?://[^\s<>]+",
        text,
    )

    for url in matches:

        url = url.rstrip(".,!?،؛)]}»")

        if is_supported_url(url):
            return url

    return None


# ==================================================
# دریافت اطلاعات ویدیو
# ==================================================

def get_video_info(url):

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 25,
        "retries": 2,
    }

    with yt_dlp.YoutubeDL(options) as ydl:

        info = ydl.extract_info(
            url,
            download=False,
        )

    if not info:
        raise ValueError("اطلاعات ویدیو دریافت نشد.")

    if info.get("_type") == "playlist":
        raise ValueError("لطفاً لینک مستقیم یک ویدیو را ارسال کنید.")

    formats = info.get("formats") or []

    heights = set()

    for fmt in formats:

        if fmt.get("vcodec") == "none":
            continue

        height = fmt.get("height")

        if height and int(height) >= 144:
            heights.add(int(height))

    if info.get("height"):
        heights.add(int(info["height"]))

    qualities = sorted(
        heights,
        reverse=True,
    )[:6]

    if not qualities:
        qualities = [None]

    return {
        "title": info.get("title", "ویدیوی بدون عنوان"),
        "qualities": qualities,
        "duration": info.get("duration"),
    }


# ==================================================
# ساخت دکمه‌های انتخاب کیفیت
# ==================================================

def get_quality_keyboard(token, qualities):

    keyboard = []

    row = []

    for quality in qualities:

        if quality is None:
            label = "بهترین کیفیت"
            quality_value = "best"

        else:
            label = f"{quality}p"
            quality_value = str(quality)

        button = InlineKeyboardButton(
            label,
            callback_data=f"dl:{token}:{quality_value}",
        )

        row.append(button)

        if len(row) == 2:

            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    return InlineKeyboardMarkup(keyboard)


# ==================================================
# دانلود ویدیو
# ==================================================

def download_video(url, quality, download_path):

    download_path = Path(download_path)

    if quality is None:

        format_selector = (
            "bestvideo+bestaudio/best"
        )

    else:

        format_selector = (
            f"bestvideo[height<={quality}]+bestaudio/"
            f"best[height<={quality}]/best"
        )

    options = {

        "format": format_selector,

        "outtmpl": str(
            download_path / "%(id)s.%(ext)s"
        ),

        "merge_output_format": "mp4",

        "quiet": True,

        "no_warnings": True,

        "noplaylist": True,

        "socket_timeout": 30,

        "retries": 3,

        "fragment_retries": 3,

        "restrictfilenames": True,

        "overwrites": True,

    }

    with yt_dlp.YoutubeDL(options) as ydl:

        ydl.extract_info(
            url,
            download=True,
        )

    video_extensions = {
        ".mp4",
        ".mkv",
        ".webm",
        ".mov",
        ".m4v",
    }

    files = [
        file
        for file in download_path.iterdir()
        if file.is_file()
        and file.suffix.lower() in video_extensions
        and not file.name.endswith(".part")
    ]

    if not files:
        raise FileNotFoundError(
            "فایل ویدیویی پس از دانلود پیدا نشد."
        )

    video_file = max(
        files,
        key=lambda file: file.stat().st_size,
    )

    file_size = video_file.stat().st_size

    if file_size > MAX_UPLOAD_SIZE:

        raise ValueError(
            "حجم ویدیو بیشتر از محدودیت ارسال این ربات در تلگرام است."
        )

    return video_file


# ==================================================
# پیام خوش‌آمدگویی
# ==================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    welcome_message = (
        "سلام! به ربات دانلودر خوش اومدی 👋\n\n"
        "🎬 با این ربات می‌تونی ویدیوهای عمومی "
        "یوتیوب و اینستاگرام رو دانلود کنی.\n\n"
        "📌 روش استفاده:\n"
        "1️⃣ لینک ویدیو رو ارسال کن.\n"
        "2️⃣ کیفیت موردنظرت رو انتخاب کن.\n"
        "3️⃣ ویدیو رو مستقیماً در تلگرام دریافت کن.\n\n"
        "برای راهنمایی بیشتر دستور /help رو بفرست."
    )

    await update.effective_message.reply_text(
        welcome_message
    )


# ==================================================
# راهنمای ربات
# ==================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = (
        "📖 راهنمای استفاده از ربات\n\n"
        "🎥 لینک‌های قابل پشتیبانی:\n"
        "• YouTube\n"
        "• YouTube Shorts\n"
        "• Instagram Reels\n"
        "• پست‌های ویدیویی عمومی اینستاگرام\n\n"
        "🔹 فقط لینک ویدیو رو ارسال کن.\n"
        "🔹 کیفیت دلخواهت رو انتخاب کن.\n"
        "🔹 منتظر دریافت ویدیو باش.\n\n"
        "برای لغو درخواست قبلی دستور /cancel رو بفرست."
    )

    await update.effective_message.reply_text(
        message
    )


# ==================================================
# لغو درخواست
# ==================================================

async def cancel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data.pop(
        "pending_download",
        None,
    )

    await update.effective_message.reply_text(
        "درخواست قبلی لغو شد. ✅"
    )


# ==================================================
# دریافت لینک از کاربر
# ==================================================

async def link_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.effective_message

    if not message or not message.text:
        return

    url = extract_url(message.text)

    if not url:
        return

    status = await message.reply_text(
        "🔎 در حال بررسی لینک و دریافت کیفیت‌های موجود..."
    )

    try:

        info = await asyncio.to_thread(
            get_video_info,
            url,
        )

        token = uuid.uuid4().hex[:8]

        context.user_data["pending_download"] = {
            "token": token,
            "url": url,
            "title": info["title"],
            "qualities": info["qualities"],
        }

        keyboard = get_quality_keyboard(
            token,
            info["qualities"],
        )

        title = info["title"][:300]

        response = (
            "✅ لینک با موفقیت شناسایی شد!\n\n"
            f"🎬 عنوان: {title}\n\n"
            "📥 کیفیت موردنظرت رو انتخاب کن:"
        )

        await status.edit_text(
            response,
            reply_markup=keyboard,
        )

    except Exception as error:

        logger.exception(
            "خطا در بررسی لینک: %s",
            error,
        )

        await status.edit_text(
            "❌ نتونستم این ویدیو رو بررسی کنم.\n\n"
            "ممکنه لینک نامعتبر باشه یا ویدیو "
            "برای دانلود عمومی در دسترس نباشه."
        )


# ==================================================
# انتخاب کیفیت و ارسال ویدیو
# ==================================================

async def quality_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    parts = query.data.split(":")

    if len(parts) != 3:

        await query.answer(
            "درخواست نامعتبر است.",
            show_alert=True,
        )

        return

    _, token, quality_text = parts

    pending = context.user_data.get(
        "pending_download"
    )

    if not pending or pending.get("token") != token:

        await query.answer(
            "این درخواست منقضی شده است. لطفاً لینک را دوباره ارسال کن.",
            show_alert=True,
        )

        return

    if pending.get("downloading"):

        await query.answer(
            "دانلود این ویدیو در حال انجام است.",
            show_alert=True,
        )

        return

    quality = (
        None
        if quality_text == "best"
        else int(quality_text)
    )

    pending["downloading"] = True

    await query.answer(
        "⬇️ دانلود شروع شد..."
    )

    await query.edit_message_text(
        "⏳ در حال دانلود ویدیو...\n"
        "لطفاً کمی صبر کن."
    )

    download_path = Path(
        f"/tmp/video_{uuid.uuid4().hex}"
    )

    download_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:

        video_file = await asyncio.to_thread(
            download_video,
            pending["url"],
            quality,
            download_path,
        )

        quality_label = (
            "بهترین کیفیت"
            if quality is None
            else f"{quality}p"
        )

        title = pending["title"][:850]

        caption = (
            f"🎬 {title}\n"
            f"📺 کیفیت: {quality_label}\n\n"
            "🤖 Video Downloader Bot"
        )

        await query.message.reply_text(
            "📤 دانلود تمام شد؛ در حال ارسال ویدیو..."
        )

        with open(video_file, "rb") as video:

            await context.bot.send_video(
                chat_id=query.message.chat_id,
                video=video,
                caption=caption,
                supports_streaming=True,
            )

        await query.message.reply_text(
            "✅ ویدیو با موفقیت ارسال شد!"
        )

    except Exception as error:

        logger.exception(
            "خطا در دانلود یا ارسال ویدیو: %s",
            error,
        )

        await query.message.reply_text(
            "❌ دانلود یا ارسال ویدیو ناموفق بود.\n\n"
            "ممکنه ویدیو در دسترس نباشه، "
            "حجمش بیش از حد مجاز باشه یا دانلود با خطا مواجه شده باشه.\n"
            "لطفاً دوباره لینک رو ارسال کن."
        )

    finally:

        context.user_data.pop(
            "pending_download",
            None,
        )

        shutil.rmtree(
            download_path,
            ignore_errors=True,
        )


# ==================================================
# سرور سلامت Railway
# ==================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        self.send_response(200)

        self.send_header(
            "Content-type",
            "text/plain; charset=utf-8",
        )

        self.end_headers()

        self.wfile.write(
            b"Video Downloader Bot is running!"
        )

    def log_message(self, format, *args):
        pass


def run_health_server():

    port = int(
        os.environ.get("PORT", 10000)
    )

    server = ThreadingHTTPServer(
        ("0.0.0.0", port),
        HealthHandler,
    )

    server.serve_forever()


# ==================================================
# اجرای ربات
# ==================================================

def main():

    if not TOKEN:

        raise RuntimeError(
            "متغیر محیطی TOKEN تنظیم نشده است."
        )

    threading.Thread(
        target=run_health_server,
        daemon=True,
    ).start()

    application = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel_command,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            quality_callback,
            pattern=r"^dl:",
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            link_handler,
        )
    )

    logger.info(
        "Video Downloader Bot started successfully."
    )

    application.run_polling()


if __name__ == "__main__":
    main()
