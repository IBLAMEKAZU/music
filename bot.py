"""
🎵 Telegram Music Bot
Requires: pip install python-telegram-bot yt-dlp
"""

import os
import re
import json
import random
import string
import asyncio
import sqlite3
import hashlib
from pathlib import Path

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)
import yt_dlp


# ─────────────────────────────────────────────
# CONFIG  –  fill these before running
# ─────────────────────────────────────────────
BOT_TOKEN   = "8746618909:AAFTS7g8hv8qIlFdPNCRFESMftKXIyrFHqU"          # @BotFather token
BOT_USERNAME = "@MUSIC_Flexxyrich_bot"             # without @
OWNER_CHAT_ID = 7692722647                    # your Telegram ID (int)

# Google-Drive photo folder links  (add as many as you like)
PHOTO_FOLDERS = {
    "Nature"   : "https://drive.google.com/drive/folders/YOUR_FOLDER_ID_1",
    "Events"   : "https://drive.google.com/drive/folders/YOUR_FOLDER_ID_2",
    "Memories" : "https://drive.google.com/drive/folders/YOUR_FOLDER_ID_3",
}

DB_PATH      = "musicbot.db"
MUSIC_DIR    = Path("music_storage")   # local folder for downloaded audio
MUSIC_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────
# Conversation states
# ─────────────────────────────────────────────
(
    SET_PASSWORD, CONFIRM_PASSWORD,
    ENTER_PASSWORD_VIEW,
    RESET_ASK_KEY, RESET_NEW_PASS, RESET_CONFIRM_PASS,
 

def get_user(chat_id: int):
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE chat_id=?", (chat_id,)).fetchone()


def upsert_user(chat_id: int, username: str):
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users(chat_id, username) VALUES(?,?)",
            (chat_id, username)
        )
        conn.execute(
            "UPDATE users SET username=? WHERE chat_id=?",
            (username, chat_id)
        )


def set_password_and_keys(chat_id: int, hashed_pw: str, keys: list):
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET password=?, keys=? WHERE chat_id=?",
            (hashed_pw, json.dumps(keys), chat_id)
        )


def get_folders(chat_id: int):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM folders WHERE chat_id=?", (chat_id,)
        ).fetchall()


def get_or_create_folder(chat_id: int, name: str) -> int:
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO folders(chat_id, name) VALUES(?,?)",
            (chat_id, name.lower())
        )
        row = conn.execute(
            "SELECT id FROM folders WHERE chat_id=? AND name=?",
            (chat_id, name.lower())
        ).fetchone()
        return row["id"]


def add_song(folder_id: int, title: str, file_path: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO songs(folder_id, title, file_path) VALUES(?,?,?)",
            (folder_id, title, file_path)
        )


def get_songs(folder_id: int):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM songs WHERE folder_id=?", (folder_id,)
        ).fetchall()


def find_song(folder_id: int, title: str):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM songs WHERE folder_id=? AND LOWER(title) LIKE ?",
            (folder_id, f"%{title.lower()}%")
        ).fetchone()


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👤 Account",      callback_data="account"),
            InlineKeyboardButton("🔗 Referral Link", callback_data="referral"),
        ],
        [
            InlineKeyboardButton("💾 Saved Music",  callback_data="saved"),
            InlineKeyboardButton("🔑 Password",     callback_data="password"),
        ],
        [
            InlineKeyboardButton("📸 Photo Folders", callback_data="photos"),
        ],
    ])


async def download_audio(query: str, dest_folder: Path) -> tuple[str, str] | None:
    """
    Download audio from YouTube/etc via yt-dlp.
    Returns (title, file_path) or None on failure.
    """
    ydl_opts = {
        "format"         : "bestaudio/best",
        "outtmpl"        : str(dest_folder / "%(title)s.%(ext)s"),
        "postprocessors" : [{
            "key"            : "FFmpegExtractAudio",
            "preferredcodec" : "mp3",
            "preferredquality": "192",
        }],
        "quiet"          : True,
        "no_warnings"    : True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                query if query.startswith("http") else f"ytsearch1:{query}",
                download=True
            )
            if "entries" in info:
                info = info["entries"][0]
            title     = info.get("title", "Unknown")
            file_path = str(dest_folder / f"{title}.mp3")
            # yt-dlp may sanitise the filename; find actual file
            mp3s = list(dest_folder.glob("*.mp3"))
            if mp3s:
                # pick the newest
                actual = max(mp3s, key=lambda p: p.stat().st_mtime)
                return title, str(actual)
    except Exception as e:
        print(f"[yt-dlp error] {e}")
    return None


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user.id, user.username or "")

    # handle referral: /start ref_<referrer_id>
    args = ctx.args
    if args and args[0].startswith("ref_"):
        referrer_id = int(args[0][4:])
        if referrer_id != user.id:
            with get_db() as conn:
                conn.execute(
                    "UPDATE users SET referred_by=? WHERE chat_id=? AND referred_by IS NULL",
                    (referrer_id, user.id)
                )

    await update.message.reply_text(
        f"🎵 *Welcome to Music Bot*, {user.first_name}!\n\n"
        "Store & retrieve your favourite songs in custom folders.\n"
        "Use the menu below or type `/help` for commands.",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )


# ─────────────────────────────────────────────
# /help
# ─────────────────────────────────────────────
async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Commands*\n\n"
        "`/start` – Main menu\n"
        "`/menu`  – Show menu buttons\n"
        "`/foldername song name` – Save/get a song\n"
        "  _e.g._ `/bollywood Shape of You`\n\n"
        "*Button Menu:*\n"
        "👤 Account – your Telegram ID\n"
        "🔗 Referral – share link\n"
        "💾 Saved – view your folders & songs\n"
        "🔑 Password – set / change password\n"
        "📸 Photos – view photo folder links",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )


# ─────────────────────────────────────────────
# /menu
# ─────────────────────────────────────────────
async def menu_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎛 *Main Menu*", parse_mode="Markdown",
                                    reply_markup=main_keyboard())


# ─────────────────────────────────────────────
# BUTTON CALLBACKS
# ─────────────────────────────────────────────
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data    = query.data
    chat_id = query.from_user.id
    user_row = get_user(chat_id)

    # ── ACCOUNT ──────────────────────────────
    if data == "account":
        uname = f"@{query.from_user.username}" if query.from_user.username else "N/A"
        await query.edit_message_text(
            f"👤 *Your Account*\n\n"
            f"• Telegram ID : `{chat_id}`\n"
            f"• Username    : {uname}\n"
            f"• Password set: {'✅ Yes' if user_row and user_row['password'] else '❌ No'}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
            ]])
        )

    # ── REFERRAL ─────────────────────────────
    elif data == "referral":
        link = f"https://t.me/{BOT_USERNAME}?start=ref_{chat_id}"
        await query.edit_message_text(
            f"🔗 *Your Referral Link*\n\n`{link}`\n\n"
            "Share this link – when friends join via your link they'll be linked to you!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
            ]])
        )

    # ── SAVED (asks password first) ───────────
    elif data == "saved":
        if not user_row or not user_row["password"]:
            await query.edit_message_text(
                "⚠️ You haven't set a password yet.\nTap *Password* from the menu to create one first.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
                ]])
            )
            return
        ctx.user_data["pending_action"] = "view_saved"
        await query.edit_message_text(
            "🔒 Enter your password to view saved music:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="back_menu")
            ]])
        )
        return ENTER_PASSWORD_VIEW

    # ── PASSWORD MENU ─────────────────────────
    elif data == "password":
        if user_row and user_row["password"]:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Change Password",  callback_data="change_password")],
                [InlineKeyboardButton("🆘 Forgot Password",  callback_data="forgot_password")],
                [InlineKeyboardButton("🔑 Regenerate Keys",  callback_data="regen_keys")],
                [InlineKeyboardButton("⬅️ Back",            callback_data="back_menu")],
            ])
            await query.edit_message_text("🔑 *Password Options*", parse_mode="Markdown",
                                          reply_markup=keyboard)
        else:
            ctx.user_data["password_action"] = "set"
            await query.edit_message_text(
                "🔑 *Set a Password*\n\nPlease type your new password:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Cancel", callback_data="back_menu")
                ]])
            )
            return SET_PASSWORD

    # ── CHANGE PASSWORD ───────────────────────
    elif data == "change_password":
        ctx.user_data["password_action"] = "change"
        await query.edit_message_text(
            "🔑 Type your *new* password:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="back_menu")
            ]])
        )
        return SET_PASSWORD

    # ── FORGOT PASSWORD ───────────────────────
    elif data == "forgot_password":
        await query.edit_message_text(
            "🆘 *Forgot Password*\n\nPlease send one of your 3 recovery keys:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="back_menu")
            ]])
        )
        return RESET_ASK_KEY

    # ── REGEN KEYS ────────────────────────────
    elif data == "regen_keys":
        await query.edit_message_text(
            "⚠️ Regenerating keys will *invalidate* your old keys.\n"
            "Type *CONFIRM* to proceed:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="back_menu")
            ]])
        )
        return REGEN_KEYS_CONFIRM

    # ── PHOTOS ────────────────────────────────
    elif data == "photos":
        if not PHOTO_FOLDERS:
            text = "📸 No photo folders configured yet."
        else:
            lines = "\n".join(
                f"• *{name}*: [Open]({link})"
                for name, link in PHOTO_FOLDERS.items()
            )
            text = f"📸 *Photo Folders*\n\n{lines}"
        await query.edit_message_text(
            text, parse_mode="Markdown", disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
            ]])
        )

    # ── BACK ──────────────────────────────────
    elif data == "back_menu":
        await query.edit_message_text(
            "🎛 *Main Menu*", parse_mode="Markdown",
            reply_markup=main_keyboard()
        )


# ─────────────────────────────────────────────
# CONVERSATION: Set / Change Password
# ─────────────────────────────────────────────
async def set_password_step1(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_password"] = update.message.text.strip()
    await update.message.reply_text("✅ Got it. Please *confirm* your password by typing it again:",
                                    parse_mode="Markdown")
    return CONFIRM_PASSWORD


async def set_password_step2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pw1 = ctx.user_data.get("new_password", "")
    pw2 = update.message.text.strip()
    if pw1 != pw2:
        await update.message.reply_text("❌ Passwords don't match. Try `/menu` and set again.",
                                        parse_mode="Markdown")
        return ConversationHandler.END

    keys     = generate_keys()
    hashed   = hash_password(pw1)
    chat_id  = update.effective_user.id
    set_password_and_keys(chat_id, hashed, keys)

    await update.message.reply_text(
        "✅ *Password set!*\n\n"
        "🔑 *Your 3 Recovery Keys* – save these somewhere safe!\n\n"
        f"`{keys[0]}`\n`{keys[1]}`\n`{keys[2]}`\n\n"
        "⚠️ You'll need one of these if you ever forget your password.",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
# CONVERSATION: View Saved (password gate)
# ─────────────────────────────────────────────
async def enter_password_view(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id  = update.effective_user.id
    user_row = get_user(chat_id)
    entered  = update.message.text.strip()

    if not user_row or hash_password(entered) != user_row["password"]:
        await update.message.reply_text("❌ Wrong password. Tap /menu to try again.")
        return ConversationHandler.END

    # Show saved music
    folders = get_folders(chat_id)
    if not folders:
        msg = "💾 *Your Music Library is empty.*\n\nUse `/foldername song` to save music!"
    else:
        lines = []
        for f in folders:
            songs = get_songs(f["id"])
            lines.append(f"📁 *{f['name'].capitalize()}* ({len(songs)} songs)")
            for s in songs:
                lines.append(f"   🎵 {s['title']}")
        msg = "💾 *Your Saved Music*\n\n" + "\n".join(lines)

    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())
    return ConversationHandler.END


# ─────────────────────────────────────────────
# CONVERSATION: Forgot Password
# ─────────────────────────────────────────────
async def reset_ask_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id  = update.effective_user.id
    user_row = get_user(chat_id)
    entered  = update.message.text.strip().upper()

    if not user_row or not user_row["keys"]:
        await update.message.reply_text("❌ No recovery keys found. Contact support.")
        return ConversationHandler.END

    stored_keys = json.loads(user_row["keys"])
    if entered not in stored_keys:
        await update.message.reply_text("❌ Key not recognised. Tap /menu to try again.")
        return ConversationHandler.END

    await update.message.reply_text("✅ Key accepted! Enter your *new* password:",
                                    parse_mode="Markdown")
    ctx.user_data["password_action"] = "reset"
    return RESET_NEW_PASS


async def reset_new_pass(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_password"] = update.message.text.strip()
    await update.message.reply_text("Confirm the new password:")
    return RESET_CONFIRM_PASS


async def reset_confirm_pass(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pw1 = ctx.user_data.get("new_password", "")
    pw2 = update.message.text.strip()
    if pw1 != pw2:
        await update.message.reply_text("❌ Passwords don't match. Tap /menu and try again.")
        return ConversationHandler.END

    chat_id = update.effective_user.id
    user_row = get_user(chat_id)
    keys    = json.loads(user_row["keys"])    # keep existing keys
    set_password_and_keys(chat_id, hash_password(pw1), keys)
    await update.message.reply_text("✅ Password reset successfully!", reply_markup=main_keyboard())
    return ConversationHandler.END


# ─────────────────────────────────────────────
# CONVERSATION: Regenerate Keys
# ─────────────────────────────────────────────
async def regen_keys_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text    = update.message.text.strip().upper()
    chat_id = update.effective_user.id
    if text != "CONFIRM":
        await update.message.reply_text("❌ Cancelled.", reply_markup=main_keyboard())
        return ConversationHandler.END

    user_row = get_user(chat_id)
    if not user_row or not user_row["password"]:
        await update.message.reply_text("❌ Set a password first.")
        return ConversationHandler.END

    new_keys = generate_keys()
    set_password_and_keys(chat_id, user_row["password"], new_keys)
    await update.message.reply_text(
        "🔑 *New Recovery Keys Generated!*\n\n"
        f"`{new_keys[0]}`\n`{new_keys[1]}`\n`{new_keys[2]}`\n\n"
        "⚠️ Your old keys are now invalid – save these new ones!",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
# /foldername song  COMMAND
# ─────────────────────────────────────────────
async def folder_song_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Any command like /bollywood Shape of You
    The command name IS the folder name.
    """
    chat_id     = update.effective_user.id
    folder_name = update.message.text.split()[0][1:]   # strip leading /
    song_name   = " ".join(update.message.text.split()[1:]).strip()

    if not song_name:
        await update.message.reply_text(
            f"Usage: `/{folder_name} Song Name`", parse_mode="Markdown"
        )
        return

    upsert_user(chat_id, update.effective_user.username or "")
    folder_id = get_or_create_folder(chat_id, folder_name)

    # Check if already saved
    existing = find_song(folder_id, song_name)
    if existing and os.path.exists(existing["file_path"]):
        await update.message.reply_text(f"📦 Found in *{folder_name}* – sending now…",
                                        parse_mode="Markdown")
        with open(existing["file_path"], "rb") as f:
            await update.message.reply_audio(f, title=existing["title"])
        return

    # Download fresh
    status_msg = await update.message.reply_text(
        f"🔍 Searching for *{song_name}* in *{folder_name}*…", parse_mode="Markdown"
    )
    user_folder = MUSIC_DIR / str(chat_id) / folder_name
    user_folder.mkdir(parents=True, exist_ok=True)

    result = await download_audio(song_name, user_folder)

    if result:
        title, file_path = result
        add_song(folder_id, title, file_path)
        await status_msg.edit_text(f"✅ Found *{title}* – sending audio…", parse_mode="Markdown")
        with open(file_path, "rb") as f:
            await update.message.reply_audio(f, title=title)
    else:
        # Ask for a video link
        ctx.user_data["pending_folder_id"]   = folder_id
        ctx.user_data["pending_song_name"]   = song_name
        ctx.user_data["pending_user_folder"] = str(user_folder)
        await status_msg.edit_text(
            f"❌ Couldn't find *{song_name}* automatically.\n\n"
            "Please send me a *YouTube / video link* for this song and I'll extract the audio:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="back_menu")
            ]])
        )
        return AWAIT_VIDEO_LINK


# ─────────────────────────────────────────────
# CONVERSATION: Receive video link
# ─────────────────────────────────────────────
async def await_video_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    link        = update.message.text.strip()
    folder_id   = ctx.user_data.get("pending_folder_id")
    song_name   = ctx.user_data.get("pending_song_name", "song")
    user_folder = Path(ctx.user_data.get("pending_user_folder", str(MUSIC_DIR)))

    if not link.startswith("http"):
        await update.message.reply_text("⚠️ Please send a valid URL.")
        return AWAIT_VIDEO_LINK

    status_msg = await update.message.reply_text("⏳ Extracting audio from link…")
    result     = await download_audio(link, user_folder)

    if result:
        title, file_path = result
        add_song(folder_id, title, file_path)
        await status_msg.edit_text(f"✅ Got *{title}* – sending audio…", parse_mode="Markdown")
        with open(file_path, "rb") as f:
            await update.message.reply_audio(f, title=title)
    else:
        await status_msg.edit_text(
            "❌ Failed to extract audio from that link. Please try another link."
        )

    return ConversationHandler.END


# ─────────────────────────────────────────────
# Fallback cancel
# ─────────────────────────────────────────────
async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.", reply_markup=main_keyboard())
    return ConversationHandler.END


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # ── Password set/change conversation ──────
    pw_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_handler, pattern="^(password|change_password)$"),
        ],
        states={
            SET_PASSWORD     : [MessageHandler(filters.TEXT & ~filters.COMMAND, set_password_step1)],
            CONFIRM_PASSWORD : [MessageHandler(filters.TEXT & ~filters.COMMAND, set_password_step2)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )

    # ── View saved music (password gate) ──────
    view_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_handler, pattern="^saved$"),
        ],
        states={
            ENTER_PASSWORD_VIEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_password_view)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )

    # ── Forgot password conversation ──────────
    forgot_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_handler, pattern="^forgot_password$"),
        ],
        states={
            RESET_ASK_KEY     : [MessageHandler(filters.TEXT & ~filters.COMMAND, reset_ask_key)],
            RESET_NEW_PASS    : [MessageHandler(filters.TEXT & ~filters.COMMAND, reset_new_pass)],
            RESET_CONFIRM_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, reset_confirm_pass)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )

    # ── Regen keys conversation ───────────────
    regen_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_handler, pattern="^regen_keys$"),
        ],
        states={
            REGEN_KEYS_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, regen_keys_confirm)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )

    # ── /folder song conversation ─────────────
    folder_conv = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex(r"^/[a-zA-Z_]+\s+.+") & ~filters.COMMAND,
                folder_song_command
            ),
            # Also catch actual commands that aren't built-in
        ],
        states={
            AWAIT_VIDEO_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, await_video_link)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )

    # Register all handlers
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("help",   help_cmd))
    app.add_handler(CommandHandler("menu",   menu_cmd))
    app.add_handler(CommandHandler("cancel", cancel))

    app.add_handler(pw_conv)
    app.add_handler(view_conv)
    app.add_handler(forgot_conv)
    app.add_handler(regen_conv)

    # Generic callback handler (account, referral, photos, back_menu)
    app.add_handler(CallbackQueryHandler(button_handler))

    # Folder/song command handler (any /<word> <song>)
    # We register it as a MessageHandler catching /command patterns
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r"^/\w+\s+.+"),
        folder_song_command
    ))

    print("🤖 Bot started! Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
