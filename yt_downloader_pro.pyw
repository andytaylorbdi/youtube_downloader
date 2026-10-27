import os
import sys
import re
import json
import threading
import time
from pathlib import Path
from datetime import datetime
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import subprocess
from queue import Queue, Empty
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from enum import Enum
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tkinter.font as tkfont

# Try importing yt-dlp gracefully
yt_dlp = None
try:
    import yt_dlp
except ImportError:
    pass

# ============================================================================
# CONSTANTS & COLORS
# ============================================================================
COLORS = {
    'bg_darkest':   '#0a0a0a',
    'bg_dark':      '#0d0d0d',
    'bg_medium':    '#141414',
    'bg_light':     '#1a1a1a',
    'bg_lighter':   '#252525',
    'bg_hover':     '#2a2a2a',
    'bg_active':    '#333333',
    'accent':       '#e63946',
    'accent_hover': '#ff4757',
    'accent_dark':  '#c1121f',
    'success':      '#00cc66',
    'warning':      '#ffaa00',
    'error':        '#ff3333',
    'text_primary': '#ffffff',
    'text_secondary':'#b3b3b3',
    'text_dim':     '#666666',
    'text_muted':   '#444444',
    'border':       '#2a2a2a',
    'video_color':  '#e63946',
    'audio_color':  '#4a90d9',
}

VIDEO_QUALITIES = ['2160p (4K)', '1440p (2K)', '1080p (Full HD)', '720p (HD)', '480p', '360p', '240p', '144p']
AUDIO_QUALITIES = ['320 kbps', '256 kbps', '192 kbps', '128 kbps', '96 kbps', '64 kbps']
VIDEO_FORMATS   = ['MP4', 'MKV', 'WEBM', 'AVI', 'MOV']
AUDIO_FORMATS   = ['MP3', 'M4A', 'FLAC', 'WAV', 'AAC', 'OPUS']



# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================
def get_download_directory():
    if sys.platform == "win32":
        desktop = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop"
    else:
        desktop = Path.home() / "Desktop"
    if not desktop.exists():
        desktop = Path.home()
    download_dir = desktop / "YouTube Downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    return str(download_dir)

def extract_video_id(url):
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    patterns = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:www\.)?youtube\.com/live/([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:m\.)?youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?youtu\.be/([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:www\.)?youtube-nocookie\.com/embed/([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            return match.group(1)
    return None

def validate_url(url):
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    domain_check = any(d in url.lower() for d in ['youtube.com', 'youtu.be', 'youtube-nocookie.com'])
    return domain_check and extract_video_id(url) is not None

def is_ffmpeg_available():
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    
    try:
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo, check=True)
        return True
    except:
        pass

    try:
        script_dir = Path(__file__).parent.absolute()
        if (script_dir / 'ffmpeg.exe').exists():
            return True
    except:
        pass

    try:
        dpath = settings.get('download_path')
        if dpath and (Path(dpath) / 'ffmpeg.exe').exists():
            return True
    except:
        pass

    return False

def bind_mousewheel_scroll(canvas):
    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
    canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
    canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

def clean_filename(filename):
    if not filename:
        return "video"
    invalid = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    for char in invalid:
        filename = filename.replace(char, '')
    return re.sub(r'\s+', ' ', filename).strip('. ')[:180] or "video"

def format_bytes(b):
    if not b:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"

def format_duration(secs):
    if not secs:
        return "0:00"
    h, r = divmod(int(secs), 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def format_views(v):
    if not v:
        return "0"
    if v >= 1_000_000_000: return f"{v/1_000_000_000:.1f}B"
    if v >= 1_000_000:     return f"{v/1_000_000:.1f}M"
    if v >= 1_000:         return f"{v/1_000:.1f}K"
    return str(v)

# ============================================================================
# SETTINGS MANAGER
# ============================================================================
class Settings:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self.filepath = Path("yt_downloader_settings.json")
        self.defaults = {
            'download_path':  get_download_directory(),
            'video_quality':  '1080p (Full HD)',
            'video_format':   'MP4',
            'audio_quality':  '320 kbps',
            'audio_format':   'MP3',
            'max_concurrent': 3,
            'sponsorblock':   True,
            'auto_paste':     True,
        }
        self.data = self._load()

    def _load(self):
        if self.filepath.exists():
            try:
                with open(self.filepath, 'r') as f:
                    return {**self.defaults, **json.load(f)}
            except:
                pass
        return self.defaults.copy()

    def save(self):
        try:
            with open(self.filepath, 'w') as f:
                json.dump(self.data, f, indent=2)
        except:
            pass

    def get(self, key):
        return self.data.get(key, self.defaults.get(key))

    def set(self, key, value):
        self.data[key] = value
        self.save()

settings = Settings()

# ============================================================================
# DOWNLOAD HISTORY
# ============================================================================
class History:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self.filepath = Path("download_history.json")
        self.lock = threading.Lock()
        self.data = self._load()

    def _load(self):
        if self.filepath.exists():
            try:
                with open(self.filepath, 'r') as f:
                    return json.load(f)
            except:
                pass
        return []

    def save(self):
        try:
            with self.lock:
                with open(self.filepath, 'w') as f:
                    json.dump(self.data[-500:], f, indent=2)
        except:
            pass

    def add(self, entry):
        with self.lock:
            entry['timestamp'] = datetime.now().isoformat()
            self.data.append(entry)
        self.save()

    def get_all(self):
        with self.lock:
            return list(reversed(self.data))

    def clear(self):
        with self.lock:
            self.data = []
        self.save()

history = History()

# ============================================================================
# LINK QUEUE SYSTEM
# ============================================================================
class LinkStatus(Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    AVAILABLE  = "available"
    FAILED     = "failed"

@dataclass
class LinkItem:
    url:        str
    video_id:   str
    status:     LinkStatus = LinkStatus.PENDING
    title:      str  = ""
    duration:   int  = 0
    views:      int  = 0
    channel:    str  = ""
    thumbnail:  str  = ""
    video_info: dict = field(default_factory=dict)
    error:      str  = ""
    added_at:   datetime = field(default_factory=datetime.now)

    def __hash__(self):
        return hash(self.video_id)

class LinkQueueManager:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.links: Dict[str, LinkItem] = {}
        self.lock = threading.Lock()
        self.process_queue = Queue()
        self.max_concurrent_fetches = 3
        self.callbacks = []
        for _ in range(self.max_concurrent_fetches):
            threading.Thread(target=self._worker_loop, daemon=True).start()

    def add_callback(self, callback):
        if hasattr(callback, '__self__'):
            obj = callback.__self__
            root = None
            if hasattr(obj, 'after'):
                root = obj
            elif hasattr(obj, 'root') and hasattr(obj.root, 'after'):
                root = obj.root
            
            if root is not None:
                def safe_cb(*args, **kwargs):
                    try:
                        root.after(0, lambda: callback(*args, **kwargs))
                    except:
                        pass
                self.callbacks.append(safe_cb)
                return
        self.callbacks.append(callback)

    def _notify(self):
        for cb in self.callbacks:
            try:
                cb()
            except:
                pass

    def _worker_loop(self):
        while True:
            try:
                video_id = self.process_queue.get(timeout=1)
                if video_id is None:
                    continue
                with self.lock:
                    if video_id not in self.links:
                        continue
                    link_item = self.links[video_id]
                    if link_item.status != LinkStatus.PENDING:
                        continue
                    link_item.status = LinkStatus.PROCESSING
                self._notify()
                success, info, error = self._fetch_video_info(link_item.url)
                with self.lock:
                    if video_id not in self.links:
                        continue
                    link_item = self.links[video_id]
                    if success and info:
                        link_item.status  = LinkStatus.AVAILABLE
                        link_item.title   = info.get('title', 'Unknown')
                        link_item.duration= info.get('duration', 0)
                        link_item.views   = info.get('view_count', 0)
                        link_item.channel = info.get('uploader', 'Unknown')
                        link_item.video_info = info
                        link_item.error   = ""
                    else:
                        link_item.status = LinkStatus.FAILED
                        link_item.error  = error or "Unknown error"
                self._notify()
            except Empty:
                continue
            except Exception as e:
                print(f"Worker error: {e}")

    def _fetch_video_info(self, url):
        try:
            opts = {
                'quiet':            True,
                'no_warnings':      True,
                'socket_timeout':   10,
                # Skip downloading the full format list — massively speeds up info fetch
                'extract_flat':     False,
                # Skip all the heavy extras we don't need
                'skip_download':    True,
                'noplaylist':       True,
                'ignoreerrors':     False,
                # Don't fetch subtitles, thumbnails, or comments
                'writesubtitles':   False,
                'writethumbnail':   False,
                'getcomments':      False,
                # Bypass heatmap/chapters processing
                'no_mark_watched':  True,
                # Only request the fields we actually display
                'force_generic_extractor': False,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                # Keep only the fields the UI uses — discard the heavy format list
                if info:
                    lightweight = {
                        'title':      info.get('title', 'Unknown'),
                        'duration':   info.get('duration', 0),
                        'view_count': info.get('view_count', 0),
                        'uploader':   info.get('uploader') or info.get('channel', 'Unknown'),
                        'webpage_url': info.get('webpage_url', url),
                        'id':         info.get('id', ''),
                        # Keep formats so the download step can use them
                        'formats':    info.get('formats', []),
                    }
                    return True, lightweight, None
                return False, None, "No info returned"
        except Exception as e:
            return False, None, str(e)[:200]

    def add_link(self, url: str) -> Optional[str]:
        if not validate_url(url):
            return None
        video_id = extract_video_id(url)
        if not video_id:
            return None
        with self.lock:
            if video_id in self.links:
                existing = self.links[video_id]
                if existing.status == LinkStatus.FAILED:
                    existing.status = LinkStatus.PENDING
                    existing.error  = ""
                    self.process_queue.put(video_id)
                    self._notify()
                    return video_id
                return None
            link_item = LinkItem(url=url, video_id=video_id)
            self.links[video_id] = link_item
        self.process_queue.put(video_id)
        self._notify()
        return video_id

    def retry_link(self, video_id: str):
        with self.lock:
            if video_id in self.links:
                link_item = self.links[video_id]
                if link_item.status == LinkStatus.FAILED:
                    link_item.status = LinkStatus.PENDING
                    link_item.error  = ""
                    self.process_queue.put(video_id)
        self._notify()

    def retry_all_failed(self):
        with self.lock:
            for video_id, link_item in self.links.items():
                if link_item.status == LinkStatus.FAILED:
                    link_item.status = LinkStatus.PENDING
                    link_item.error  = ""
                    self.process_queue.put(video_id)
        self._notify()

    def remove_link(self, video_id: str):
        with self.lock:
            if video_id in self.links:
                del self.links[video_id]
        self._notify()

    def clear_available(self):
        with self.lock:
            to_remove = [vid for vid, item in self.links.items()
                         if item.status == LinkStatus.AVAILABLE]
            for vid in to_remove:
                del self.links[vid]
        self._notify()

    def clear_failed(self):
        with self.lock:
            to_remove = [vid for vid, item in self.links.items()
                         if item.status == LinkStatus.FAILED]
            for vid in to_remove:
                del self.links[vid]
        self._notify()

    def get_link(self, video_id: str) -> Optional[LinkItem]:
        with self.lock:
            return self.links.get(video_id)

    def get_pending_links(self) -> List[LinkItem]:
        with self.lock:
            return [item for item in self.links.values()
                    if item.status in (LinkStatus.PENDING, LinkStatus.PROCESSING)]

    def get_available_links(self) -> List[LinkItem]:
        with self.lock:
            return [item for item in self.links.values()
                    if item.status == LinkStatus.AVAILABLE]

    def get_failed_links(self) -> List[LinkItem]:
        with self.lock:
            return [item for item in self.links.values()
                    if item.status == LinkStatus.FAILED]

    def get_counts(self) -> Dict[str, int]:
        with self.lock:
            pending   = sum(1 for item in self.links.values()
                            if item.status in (LinkStatus.PENDING, LinkStatus.PROCESSING))
            available = sum(1 for item in self.links.values()
                            if item.status == LinkStatus.AVAILABLE)
            failed    = sum(1 for item in self.links.values()
                            if item.status == LinkStatus.FAILED)
            return {'pending': pending, 'available': available, 'failed': failed}

link_queue = LinkQueueManager()

# ============================================================================
# DOWNLOAD MANAGER
# ============================================================================
@dataclass
class DownloadItem:
    id:        str
    url:       str
    title:     str
    config:    dict
    save_path: str
    status:    str   = "pending"
    progress:  float = 0
    speed:     str   = ""
    eta:       str   = ""
    error:     str   = ""

class DownloadManager:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.pending   = deque()
        self.active    = {}
        self.completed = []
        self.failed    = []
        self.lock      = threading.Lock()
        self.max_workers = settings.get('max_concurrent')
        self.running   = False
        self.callbacks = []

    def add_callback(self, callback):
        if hasattr(callback, '__self__'):
            obj = callback.__self__
            root = None
            if hasattr(obj, 'after'):
                root = obj
            elif hasattr(obj, 'root') and hasattr(obj.root, 'after'):
                root = obj.root
            
            if root is not None:
                def safe_cb(*args, **kwargs):
                    try:
                        root.after(0, lambda: callback(*args, **kwargs))
                    except:
                        pass
                self.callbacks.append(safe_cb)
                return
        self.callbacks.append(callback)

    def _notify(self):
        for cb in self.callbacks:
            try:
                cb()
            except:
                pass

    def add(self, item: DownloadItem):
        with self.lock:
            self.pending.append(item)
        self._ensure_running()
        self._notify()

    def _ensure_running(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self._process_queue, daemon=True).start()

    def _process_queue(self):
        executor = ThreadPoolExecutor(max_workers=self.max_workers)
        while True:
            with self.lock:
                if not self.pending and not self.active:
                    self.running = False
                    break
                while len(self.active) < self.max_workers and self.pending:
                    item = self.pending.popleft()
                    item.status = "downloading"
                    self.active[item.id] = item
                    executor.submit(self._download, item)
            self._notify()
            time.sleep(0.5)
        executor.shutdown(wait=False)

    def _download(self, item: DownloadItem):
        def hook(d):
            try:
                if d['status'] == 'downloading':
                    downloaded = d.get('downloaded_bytes', 0)
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    with self.lock:
                        item.progress = (downloaded / total * 100) if total else 0
                        item.speed = format_bytes(d.get('speed', 0)) + "/s" if d.get('speed') else ""
                        eta_secs = d.get('eta', 0)
                        item.eta = f"{eta_secs//60}:{eta_secs%60:02d}" if eta_secs else ""
                    self._notify()
                elif d['status'] == 'finished':
                    with self.lock:
                        item.status = "processing"
                    self._notify()
            except:
                pass

        config        = item.config
        download_type = config.get('type', 'video')
        quality       = config.get('quality', '1080p')
        fmt           = config.get('format', 'mp4').lower()
        clean_title   = clean_filename(item.title)

        opts = {
            'outtmpl':          str(Path(item.save_path) / f'{clean_title}.%(ext)s'),
            'progress_hooks':   [hook],
            'quiet':            True,
            'no_warnings':      True,
            'noplaylist':       True,
            'retries':          10,
            'fragment_retries': 10,
            'merge_output_format': fmt,
        }

        if settings.get('sponsorblock'):
            opts['sponsorblock_remove'] = ['sponsor', 'selfpromo', 'interaction']

        if download_type == 'audio':
            # Extract numeric kbps value: "320 kbps" -> "320"
            quality_val = re.search(r'(\d+)', quality)
            quality_num = quality_val.group(1) if quality_val else '320'

            opts['format'] = 'bestaudio/best'
            opts['postprocessors'] = [{
                'key':              'FFmpegExtractAudio',
                'preferredcodec':   fmt,
                'preferredquality': quality_num,
            }]
        else:
            # Extract numeric height: "1080p (Full HD)" -> 1080
            height_match = re.search(r'(\d+)', quality) if quality else None
            height = height_match.group(1) if height_match else '1080'

            # FIX: force the selected quality — no open-ended /best fallback
            # This ensures the user's chosen resolution is respected
            opts['format'] = (
                f'bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/'
                f'bestvideo[height<={height}][ext=webm]+bestaudio[ext=webm]/'
                f'bestvideo[height<={height}]+bestaudio/'
                f'best[height<={height}]'
            )
            opts['merge_output_format'] = fmt

            # For non-mp4 targets, allow merging to the requested container
            if fmt != 'mp4':
                opts['merge_output_format'] = fmt

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([item.url])

            with self.lock:
                if item.id in self.active:
                    del self.active[item.id]
                item.status = "completed"
                self.completed.append(item)

            history.add({
                'title':   item.title,
                'url':     item.url,
                'type':    download_type,
                'quality': quality,
                'format':  fmt,
                'status':  'completed',
            })

        except Exception as e:
            with self.lock:
                if item.id in self.active:
                    del self.active[item.id]
                item.status = "failed"
                item.error  = str(e)[:200]
                self.failed.append(item)

        self._notify()

    def get_status(self):
        with self.lock:
            return {
                'pending':   len(self.pending),
                'active':    len(self.active),
                'completed': len(self.completed),
                'failed':    len(self.failed),
            }

    def get_all_items(self):
        with self.lock:
            items = []
            items.extend(list(self.active.values()))
            items.extend(list(self.pending))
            items.extend(self.completed[-10:])
            items.extend(self.failed[-5:])
            return items

    def clear_completed(self):
        with self.lock:
            self.completed.clear()
        self._notify()

    def retry_failed(self):
        with self.lock:
            for item in self.failed:
                item.status   = "pending"
                item.progress = 0
                item.error    = ""
                self.pending.append(item)
            self.failed.clear()
        self._ensure_running()
        self._notify()

download_manager = DownloadManager()

# ============================================================================
# CUSTOM WIDGETS
# ============================================================================
class CircularProgress(tk.Canvas):
    def __init__(self, parent, size=50, thickness=4, bg_color=None, progress_color=None, **kwargs):
        super().__init__(parent, width=size, height=size,
                         highlightthickness=0, bg=COLORS['bg_medium'], **kwargs)
        self.size           = size
        self.thickness      = thickness
        self.bg_color       = bg_color or COLORS['bg_lighter']
        self.progress_color = progress_color or COLORS['accent']
        self.progress       = 0
        self._draw()

    def _draw(self):
        self.delete("all")
        padding = self.thickness + 2
        self.create_oval(padding, padding, self.size - padding, self.size - padding,
                         outline=self.bg_color, width=self.thickness)
        if self.progress > 0:
            extent = -self.progress * 3.6
            self.create_arc(padding, padding, self.size - padding, self.size - padding,
                            start=90, extent=extent, outline=self.progress_color,
                            width=self.thickness, style='arc')
        self.create_text(self.size // 2, self.size // 2,
                         text=f"{int(self.progress)}%",
                         fill=COLORS['text_primary'],
                         font=('Segoe UI', self.size // 6, 'bold'))

    def set_progress(self, value):
        self.progress = max(0, min(100, value))
        self._draw()

    def set_color(self, color):
        self.progress_color = color
        self._draw()


class ModernButton(tk.Canvas):
    def __init__(self, parent, text, command=None, width=120, height=40,
                 bg=None, fg=None, hover_bg=None, font_size=11, **kwargs):
        # Determine parent background safely
        try:
            parent_bg = parent.cget('bg')
        except:
            parent_bg = COLORS['bg_dark']

        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bg=parent_bg, **kwargs)
        self.text     = text
        self.command  = command
        self.width    = width
        self.height   = height
        self.bg       = bg or COLORS['accent']
        self.fg       = fg or COLORS['text_primary']
        self.hover_bg = hover_bg or COLORS['accent_hover']
        self.current_bg = self.bg
        self.font_size  = font_size
        self.enabled    = True

        self.bind('<Enter>',    self._on_enter)
        self.bind('<Leave>',    self._on_leave)
        self.bind('<Button-1>', self._on_click)
        self._draw()

    def _draw(self):
        self.delete('all')
        r = 10
        c = self.current_bg
        self.create_arc(0, 0, r*2, r*2, start=90, extent=90, fill=c, outline='')
        self.create_arc(self.width-r*2, 0, self.width, r*2, start=0, extent=90, fill=c, outline='')
        self.create_arc(0, self.height-r*2, r*2, self.height, start=180, extent=90, fill=c, outline='')
        self.create_arc(self.width-r*2, self.height-r*2, self.width, self.height, start=270, extent=90, fill=c, outline='')
        self.create_rectangle(r, 0, self.width-r, self.height, fill=c, outline='')
        self.create_rectangle(0, r, self.width, self.height-r, fill=c, outline='')
        self.create_text(self.width//2, self.height//2, text=self.text,
                         fill=self.fg if self.enabled else COLORS['text_dim'],
                         font=('Segoe UI', self.font_size, 'bold'))

    def _on_enter(self, e):
        if self.enabled:
            self.current_bg = self.hover_bg
            self._draw()
            self.configure(cursor='hand2')

    def _on_leave(self, e):
        self.current_bg = self.bg
        self._draw()
        self.configure(cursor='')

    def _on_click(self, e):
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self._draw()


class ModernEntry(tk.Frame):
    def __init__(self, parent, placeholder="", width=300, **kwargs):
        super().__init__(parent, bg=COLORS['bg_light'], highlightthickness=2,
                         highlightbackground=COLORS['border'],
                         highlightcolor=COLORS['accent'])
        self.placeholder        = placeholder
        self.placeholder_active = True
        self.entry = tk.Entry(self, bg=COLORS['bg_light'], fg=COLORS['text_dim'],
                              insertbackground=COLORS['text_primary'],
                              font=('Segoe UI', 12), relief='flat',
                              width=width // 10)
        self.entry.pack(padx=12, pady=10, fill='x')
        self.entry.insert(0, placeholder)
        self.entry.bind('<FocusIn>',  self._on_focus_in)
        self.entry.bind('<FocusOut>', self._on_focus_out)

    def _on_focus_in(self, e):
        if self.placeholder_active:
            self.entry.delete(0, 'end')
            self.entry.config(fg=COLORS['text_primary'])
            self.placeholder_active = False

    def _on_focus_out(self, e):
        if not self.entry.get():
            self.entry.insert(0, self.placeholder)
            self.entry.config(fg=COLORS['text_dim'])
            self.placeholder_active = True

    def get(self):
        if self.placeholder_active:
            return ""
        return self.entry.get()

    def set(self, text):
        self.entry.delete(0, 'end')
        self.entry.insert(0, text)
        self.entry.config(fg=COLORS['text_primary'])
        self.placeholder_active = False

    def clear(self):
        self.entry.delete(0, 'end')
        self.entry.insert(0, self.placeholder)
        self.entry.config(fg=COLORS['text_dim'])
        self.placeholder_active = True

    def bind_enter(self, callback):
        self.entry.bind('<Return>', callback)


class ModernCard(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=COLORS['bg_medium'], **kwargs)
        self.configure(highlightthickness=1, highlightbackground=COLORS['border'])


# ============================================================================
# QUICK DOWNLOAD WINDOW  (fully redesigned)
# ============================================================================
class QuickDownloadWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_app = parent

        self.title("Quick Download")
        self.configure(bg=COLORS['bg_dark'])
        self.overrideredirect(True)
        self.attributes('-topmost', True)

        self.last_clipboard = ""
        self._drag_x = 0
        self._drag_y = 0
        self.current_view   = 'main'   # 'main' | 'available' | 'pending' | 'failed' | 'options' | 'batch'
        self.selected_link  = None
        self._pending_download = None  # (link_item, type, quality, fmt)

        self.geometry("420x110")
        self._center_window()
        self._build_main()

        self._monitor_clipboard()
        link_queue.add_callback(self._on_queue_update)

    # ── Positioning ──────────────────────────────────────────────────────────

    def _center_window(self):
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        x  = (sw - 420) // 2
        self.geometry(f"+{x}+60")

    # ── Main (mini) view ─────────────────────────────────────────────────────

    def _build_main(self):
        self._clear()
        self.current_view  = 'main'
        self.selected_link = None
        self.geometry("420x110")

        outer = self._outer_frame()

        # ── Header ──
        hdr = tk.Frame(outer, bg=COLORS['bg_dark'])
        hdr.pack(fill='x', padx=14, pady=(11, 6))

        tk.Label(hdr, text="YT DOWNLOADER", font=('Segoe UI', 10, 'bold'),
                 bg=COLORS['bg_dark'], fg=COLORS['text_primary']).pack(side='left')

        self._hdr_close(hdr, lambda: self.withdraw())
        self._hdr_link(hdr, "MAIN", self._show_main_app)

        self._drag_bind(hdr)

        # ── Status buttons ──
        self._build_status_buttons(outer)

    def _build_status_buttons(self, parent):
        counts = link_queue.get_counts()

        row = tk.Frame(parent, bg=COLORS['bg_dark'])
        row.pack(fill='x', padx=14, pady=(0, 10))
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, weight=1)
        row.columnconfigure(2, weight=1)

        specs = [
            ("Available", counts['available'], COLORS['success'],   'available'),
            ("Pending",   counts['pending'],   COLORS['warning'],   'pending'),
            ("Failed",    counts['failed'],    COLORS['error'],     'failed'),
        ]

        paddings = [(0, 3), (3, 3), (3, 0)]
        for col, (label, count, active_bg, view) in enumerate(specs):
            active = count > 0
            bg  = active_bg if active else COLORS['bg_lighter']
            fg  = 'white'   if active else COLORS['text_dim']
            btn = tk.Label(row,
                           text=f"{label}  {count}",
                           font=('Segoe UI', 10, 'bold'),
                           bg=bg, fg=fg,
                           padx=6, pady=9,
                           cursor='hand2' if active else '',
                           anchor='center')
            btn.grid(row=0, column=col, sticky='ew',
                     padx=paddings[col])
            if active:
                btn.bind('<Button-1>', lambda e, v=view: self._show_category(v))
                # Hover effect
                orig_bg = bg
                btn.bind('<Enter>', lambda e, b=btn, ob=orig_bg: b.config(
                    bg=self._lighten(ob)))
                btn.bind('<Leave>', lambda e, b=btn, ob=orig_bg: b.config(bg=ob))

    @staticmethod
    def _lighten(hex_color):
        """Slightly lighten a hex color for hover."""
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            r = min(255, r + 20)
            g = min(255, g + 20)
            b = min(255, b + 20)
            return f'#{r:02x}{g:02x}{b:02x}'
        except:
            return hex_color

    # ── Category list view ───────────────────────────────────────────────────

    def _show_category(self, category):
        self.current_view = category
        if category == 'available':
            items = link_queue.get_available_links()
        elif category == 'pending':
            items = link_queue.get_pending_links()
        else:
            items = link_queue.get_failed_links()
        self._build_category(category, items)

    def _build_category(self, category, items):
        self._clear()

        # Dynamic height — clamp between 160 and 500
        item_h  = 60
        hdr_h   = 55
        total_h = max(160, min(hdr_h + len(items) * item_h + 20, 500))
        self.geometry(f"420x{total_h}")

        outer = self._outer_frame()

        # Header
        hdr = tk.Frame(outer, bg=COLORS['bg_dark'])
        hdr.pack(fill='x', padx=14, pady=(11, 6))

        cat_colors = {'available': COLORS['success'], 'pending': COLORS['warning'], 'failed': COLORS['error']}
        tk.Label(hdr, text=category.upper(), font=('Segoe UI', 10, 'bold'),
                 bg=COLORS['bg_dark'], fg=cat_colors.get(category, COLORS['text_dim'])).pack(side='left')

        self._hdr_close(hdr, lambda: self.withdraw())
        self._hdr_link(hdr, "← Back", self._build_main)
        self._drag_bind(hdr)

        tk.Frame(outer, bg=COLORS['border'], height=1).pack(fill='x', padx=8)

        # Scrollable list
        wrap = tk.Frame(outer, bg=COLORS['bg_dark'])
        wrap.pack(fill='both', expand=True, padx=4, pady=4)

        canvas = tk.Canvas(wrap, bg=COLORS['bg_dark'], highlightthickness=0)
        sb     = ttk.Scrollbar(wrap, orient='vertical', command=canvas.yview)
        lframe = tk.Frame(canvas, bg=COLORS['bg_dark'])

        lframe.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=lframe, anchor='nw')
        canvas.configure(yscrollcommand=sb.set)

        canvas.pack(side='left', fill='both', expand=True)
        if len(items) > 5:
            sb.pack(side='right', fill='y')
        bind_mousewheel_scroll(canvas)

        if not items:
            msgs = {
                'available': 'No available videos — copy a YouTube URL to add one',
                'pending':   'No links being processed',
                'failed':    'No failed links',
            }
            tk.Label(lframe, text=msgs.get(category, 'Empty'),
                     font=('Segoe UI', 10), bg=COLORS['bg_dark'],
                     fg=COLORS['text_dim'], wraplength=370,
                     justify='center').pack(pady=30, padx=15)
        else:
            for link_item in items:
                self._build_list_item(lframe, link_item, category)

    def _build_list_item(self, parent, link_item, category):
        card = tk.Frame(parent, bg=COLORS['bg_medium'],
                        highlightthickness=1, highlightbackground=COLORS['border'])
        card.pack(fill='x', padx=4, pady=2)

        # Status stripe
        stripe_colors = {
            'available': COLORS['success'],
            'pending':   COLORS['warning'],
            'failed':    COLORS['error'],
        }
        tk.Frame(card, bg=stripe_colors.get(category, COLORS['text_dim']), width=4
                 ).pack(side='left', fill='y')

        # Text info
        info = tk.Frame(card, bg=COLORS['bg_medium'])
        info.pack(side='left', fill='both', expand=True, padx=10, pady=8)

        raw_title = link_item.title or f"Loading... ({link_item.video_id[:8]})"
        title     = (raw_title[:36] + "...") if len(raw_title) > 36 else raw_title

        tk.Label(info, text=title, font=('Segoe UI', 10, 'bold'),
                 bg=COLORS['bg_medium'], fg=COLORS['text_primary'],
                 anchor='w').pack(fill='x')

        if category == 'available':
            meta = f"{format_duration(link_item.duration)} | {format_views(link_item.views)} views"
            tk.Label(info, text=meta, font=('Segoe UI', 8),
                     bg=COLORS['bg_medium'], fg=COLORS['text_dim'], anchor='w').pack(fill='x')
        elif category == 'pending':
            status_str = "Checking..." if link_item.status == LinkStatus.PROCESSING else "Waiting in queue..."
            tk.Label(info, text=status_str, font=('Segoe UI', 8),
                     bg=COLORS['bg_medium'], fg=COLORS['warning'], anchor='w').pack(fill='x')
        elif category == 'failed':
            err = link_item.error[:45] + ("..." if len(link_item.error) > 45 else "")
            tk.Label(info, text=f"Error: {err}", font=('Segoe UI', 8),
                     bg=COLORS['bg_medium'], fg=COLORS['error'], anchor='w').pack(fill='x')

        # Action buttons on right
        acts = tk.Frame(card, bg=COLORS['bg_medium'])
        acts.pack(side='right', padx=6, pady=6)

        if category == 'available':
            sel = tk.Label(acts, text="SELECT", font=('Segoe UI', 8, 'bold'),
                           bg=COLORS['accent'], fg='white',
                           padx=8, pady=4, cursor='hand2')
            sel.pack(side='left', padx=(0, 4))
            sel.bind('<Button-1>', lambda e: self._select_for_download(link_item))
            sel.bind('<Enter>', lambda e: sel.config(bg=COLORS['accent_hover']))
            sel.bind('<Leave>', lambda e: sel.config(bg=COLORS['accent']))

        if category == 'failed':
            retry = tk.Label(acts, text="RETRY", font=('Segoe UI', 8, 'bold'),
                             bg=COLORS['bg_lighter'], fg=COLORS['text_secondary'],
                             padx=8, pady=4, cursor='hand2')
            retry.pack(side='left', padx=(0, 4))
            retry.bind('<Button-1>',
                       lambda e: (link_queue.retry_link(link_item.video_id),
                                  self.after(100, lambda: self._show_category('failed'))))

        rm = tk.Label(acts, text="✕", font=('Segoe UI', 10, 'bold'),
                      bg=COLORS['bg_medium'], fg=COLORS['text_dim'], cursor='hand2')
        rm.pack(side='left')
        rm.bind('<Button-1>',
                lambda e: (link_queue.remove_link(link_item.video_id),
                           self.after(100, lambda: self._show_category(category))))
        rm.bind('<Enter>', lambda e: rm.config(fg=COLORS['error']))
        rm.bind('<Leave>', lambda e: rm.config(fg=COLORS['text_dim']))

    # ── Download options view ─────────────────────────────────────────────────

    def _select_for_download(self, link_item):
        self.selected_link = link_item
        self._build_options(link_item)

    def _build_options(self, link_item):
        self._clear()
        self.current_view = 'options'
        self.geometry("450x570")

        outer = self._outer_frame()

        # Header
        hdr = tk.Frame(outer, bg=COLORS['bg_dark'])
        hdr.pack(fill='x', padx=14, pady=(11, 6))

        tk.Label(hdr, text="DOWNLOAD OPTIONS", font=('Segoe UI', 10, 'bold'),
                 bg=COLORS['bg_dark'], fg=COLORS['text_primary']).pack(side='left')

        self._hdr_close(hdr, lambda: self.withdraw())
        self._hdr_link(hdr, "← Back", lambda: self._show_category('available'))
        self._drag_bind(hdr)

        # Video info card
        info_card = tk.Frame(outer, bg=COLORS['bg_medium'],
                             highlightthickness=1, highlightbackground=COLORS['border'])
        info_card.pack(fill='x', padx=14, pady=(2, 10))

        raw = link_item.title
        title_disp = (raw[:50] + "...") if len(raw) > 50 else raw
        tk.Label(info_card, text=title_disp, font=('Segoe UI', 12, 'bold'),
                 bg=COLORS['bg_medium'], fg=COLORS['text_primary'],
                 wraplength=390, justify='left').pack(anchor='w', padx=12, pady=(10, 3))

        meta = (f"{format_duration(link_item.duration)}  |  "
                f"{format_views(link_item.views)} views  |  "
                f"{link_item.channel[:25]}")
        tk.Label(info_card, text=meta, font=('Segoe UI', 9),
                 bg=COLORS['bg_medium'], fg=COLORS['text_dim']).pack(anchor='w', padx=12, pady=(0, 10))

        # Quick download
        tk.Label(outer, text="QUICK DOWNLOAD", font=('Segoe UI', 8, 'bold'),
                 bg=COLORS['bg_dark'], fg=COLORS['text_dim']).pack(anchor='w', padx=14, pady=(0, 5))

        qrow = tk.Frame(outer, bg=COLORS['bg_dark'])
        qrow.pack(fill='x', padx=14, pady=(0, 8))

        ModernButton(qrow, "VIDEO",
                     command=lambda: self._init_download_flow('video',
                         settings.get('video_quality'), settings.get('video_format')),
                     width=175, height=42, bg=COLORS['video_color']).pack(side='left', padx=(0, 6))

        ModernButton(qrow, "AUDIO",
                     command=lambda: self._init_download_flow('audio',
                         settings.get('audio_quality'), settings.get('audio_format')),
                     width=175, height=42, bg=COLORS['audio_color'],
                     hover_bg='#5a9fe9').pack(side='left')

        tk.Frame(outer, bg=COLORS['border'], height=1).pack(fill='x', padx=14, pady=6)

        # Custom video options
        tk.Label(outer, text="Video Quality", font=('Segoe UI', 9, 'bold'),
                 bg=COLORS['bg_dark'], fg=COLORS['video_color']).pack(anchor='w', padx=14)

        vq_row = tk.Frame(outer, bg=COLORS['bg_dark'])
        vq_row.pack(fill='x', padx=14, pady=(4, 6))

        self.vq_var = tk.StringVar(value='1080p')
        for q in ['2160p', '1440p', '1080p', '720p', '480p', '360p']:
            tk.Radiobutton(vq_row, text=q, variable=self.vq_var, value=q,
                           bg=COLORS['bg_dark'], fg=COLORS['text_secondary'],
                           selectcolor=COLORS['bg_active'],
                           activebackground=COLORS['bg_dark'],
                           font=('Segoe UI', 9), indicatoron=0,
                           padx=7, pady=4, relief='flat').pack(side='left', padx=1)

        vf_row = tk.Frame(outer, bg=COLORS['bg_dark'])
        vf_row.pack(fill='x', padx=14, pady=(0, 8))

        tk.Label(vf_row, text="Format:", font=('Segoe UI', 9),
                 bg=COLORS['bg_dark'], fg=COLORS['text_dim']).pack(side='left')
        self.vf_var = tk.StringVar(value=settings.get('video_format'))
        ttk.Combobox(vf_row, textvariable=self.vf_var,
                     values=VIDEO_FORMATS, width=8, state='readonly').pack(side='left', padx=7)

        ModernButton(vf_row, "Download Video",
                     command=lambda: self._init_download_flow(
                         'video', self.vq_var.get(), self.vf_var.get()),
                     width=132, height=34, font_size=9).pack(side='right')

        tk.Frame(outer, bg=COLORS['border'], height=1).pack(fill='x', padx=14, pady=6)

        # Custom audio options
        tk.Label(outer, text="Audio Quality", font=('Segoe UI', 9, 'bold'),
                 bg=COLORS['bg_dark'], fg=COLORS['audio_color']).pack(anchor='w', padx=14)

        aq_row = tk.Frame(outer, bg=COLORS['bg_dark'])
        aq_row.pack(fill='x', padx=14, pady=(4, 6))

        self.aq_var = tk.StringVar(value='320')
        for q in ['320', '256', '192', '128', '96']:
            tk.Radiobutton(aq_row, text=q, variable=self.aq_var, value=q,
                           bg=COLORS['bg_dark'], fg=COLORS['text_secondary'],
                           selectcolor=COLORS['bg_active'],
                           activebackground=COLORS['bg_dark'],
                           font=('Segoe UI', 9), indicatoron=0,
                           padx=7, pady=4, relief='flat').pack(side='left', padx=1)

        af_row = tk.Frame(outer, bg=COLORS['bg_dark'])
        af_row.pack(fill='x', padx=14, pady=(0, 8))

        tk.Label(af_row, text="Format:", font=('Segoe UI', 9),
                 bg=COLORS['bg_dark'], fg=COLORS['text_dim']).pack(side='left')
        self.af_var = tk.StringVar(value=settings.get('audio_format'))
        ttk.Combobox(af_row, textvariable=self.af_var,
                     values=AUDIO_FORMATS, width=8, state='readonly').pack(side='left', padx=7)

        ModernButton(af_row, "Download Audio",
                     command=lambda: self._init_download_flow(
                         'audio', self.aq_var.get() + ' kbps', self.af_var.get()),
                     width=132, height=34,
                     bg=COLORS['audio_color'], hover_bg='#5a9fe9',
                     font_size=9).pack(side='right')

    # ── Download flow ─────────────────────────────────────────────────────────

    def _init_download_flow(self, dl_type, quality, fmt):
        if not self.selected_link:
            return
        link  = self.selected_link
        others = [l for l in link_queue.get_available_links()
                  if l.video_id != link.video_id]
        if others:
            self._build_batch_ui(link, dl_type, quality, fmt, others)
        else:
            self._execute_download(link, dl_type, quality, fmt)
            self._build_main()

    def _build_batch_ui(self, primary, dl_type, quality, fmt, others):
        self._clear()
        self.current_view = 'batch'

        height = max(260, min(220 + len(others) * 46 + 70, 520))
        self.geometry(f"430x{height}")

        outer = self._outer_frame()

        # Header
        hdr = tk.Frame(outer, bg=COLORS['bg_dark'])
        hdr.pack(fill='x', padx=14, pady=(11, 6))

        tk.Label(hdr, text="APPLY TO MORE VIDEOS?", font=('Segoe UI', 10, 'bold'),
                 bg=COLORS['bg_dark'], fg=COLORS['text_primary']).pack(side='left')

        self._hdr_close(hdr, lambda: self.withdraw())
        self._drag_bind(hdr)

        # Settings summary
        type_color = COLORS['video_color'] if dl_type == 'video' else COLORS['audio_color']
        sum_frame = tk.Frame(outer, bg=COLORS['bg_medium'],
                             highlightthickness=1, highlightbackground=COLORS['border'])
        sum_frame.pack(fill='x', padx=14, pady=(2, 8))

        prim_title = (primary.title[:42] + "...") if len(primary.title) > 42 else primary.title
        tk.Label(sum_frame, text=f"Downloading: {prim_title}",
                 font=('Segoe UI', 9, 'bold'),
                 bg=COLORS['bg_medium'], fg=COLORS['text_primary']).pack(anchor='w', padx=12, pady=(8, 2))

        tk.Label(sum_frame, text=f"{dl_type.upper()}  ·  {quality}  ·  {fmt.upper()}",
                 font=('Segoe UI', 9), bg=COLORS['bg_medium'],
                 fg=type_color).pack(anchor='w', padx=12, pady=(0, 8))

        tk.Label(outer, text="Select other available videos to download with these same settings:",
                 font=('Segoe UI', 9), bg=COLORS['bg_dark'],
                 fg=COLORS['text_dim'], wraplength=400).pack(anchor='w', padx=14, pady=(0, 6))

        # Scrollable checkbox list
        check_wrap = tk.Frame(outer, bg=COLORS['bg_dark'])
        check_wrap.pack(fill='x', padx=14, pady=(0, 8))

        check_vars: Dict[str, tk.BooleanVar] = {}

        sa_var = tk.BooleanVar(value=False)
        def toggle_all():
            v = sa_var.get()
            for cv in check_vars.values():
                cv.set(v)

        sa_cb = tk.Checkbutton(check_wrap, text="Select all", variable=sa_var,
                               command=toggle_all,
                               bg=COLORS['bg_dark'], fg=COLORS['text_secondary'],
                               selectcolor=COLORS['bg_lighter'],
                               activebackground=COLORS['bg_dark'],
                               font=('Segoe UI', 9, 'bold'))
        sa_cb.pack(anchor='w', pady=(0, 4))

        for lo in others:
            cv = tk.BooleanVar(value=False)
            check_vars[lo.video_id] = cv
            lbl = (lo.title[:42] + "...") if len(lo.title) > 42 else lo.title
            tk.Checkbutton(check_wrap, text=lbl, variable=cv,
                           bg=COLORS['bg_dark'], fg=COLORS['text_primary'],
                           selectcolor=COLORS['bg_lighter'],
                           activebackground=COLORS['bg_dark'],
                           font=('Segoe UI', 9)).pack(anchor='w', padx=12, pady=1)

        # Action buttons
        btn_row = tk.Frame(outer, bg=COLORS['bg_dark'])
        btn_row.pack(fill='x', padx=14, pady=10)

        def do_apply():
            self._execute_download(primary, dl_type, quality, fmt)
            for lo in others:
                if check_vars.get(lo.video_id, tk.BooleanVar(value=False)).get():
                    self._execute_download(lo, dl_type, quality, fmt)
            self._build_main()

        def do_only_this():
            self._execute_download(primary, dl_type, quality, fmt)
            remaining = link_queue.get_available_links()
            if remaining:
                self._show_category('available')
            else:
                self._build_main()

        ModernButton(btn_row, "Apply & Download",
                     command=do_apply,
                     width=158, height=40).pack(side='left', padx=(0, 8))

        ModernButton(btn_row, "Only This One",
                     command=do_only_this,
                     width=130, height=40,
                     bg=COLORS['bg_light'], hover_bg=COLORS['bg_hover']).pack(side='left')

    # ── Execute ───────────────────────────────────────────────────────────────

    def _execute_download(self, link_item, dl_type, quality, fmt):
        config = {'type': dl_type, 'quality': quality, 'format': fmt.lower()}
        di = DownloadItem(
            id=f"{id(link_item)}{time.time()}",
            url=link_item.url,
            title=link_item.title,
            config=config,
            save_path=settings.get('download_path'),
        )
        download_manager.add(di)
        link_queue.remove_link(link_item.video_id)
        self._toast(f"↓  {link_item.title[:32]}...")

    # ── Clipboard monitor ─────────────────────────────────────────────────────

    def _monitor_clipboard(self):
        if settings.get('auto_paste'):
            try:
                text = self.clipboard_get()
                if text and isinstance(text, str) and text != self.last_clipboard:
                    self.last_clipboard = text
                    stripped = text.strip()
                    if validate_url(stripped):
                        link_queue.add_link(stripped)
            except:
                pass
        self.after(800, self._monitor_clipboard)

    # ── Queue update callback ─────────────────────────────────────────────────

    def _on_queue_update(self):
        try:
            current = self.current_view
            if current == 'main':
                self.after(0, self._build_main)
            elif current in ('available', 'pending', 'failed'):
                self.after(0, lambda c=current: self._show_category(c))
        except:
            pass

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _clear(self):
        for w in self.winfo_children():
            w.destroy()

    def _outer_frame(self):
        f = tk.Frame(self, bg=COLORS['bg_dark'],
                     highlightthickness=1, highlightbackground=COLORS['border'])
        f.pack(fill='both', expand=True, padx=2, pady=2)
        return f

    def _hdr_close(self, parent, cmd):
        btn = tk.Label(parent, text="✕", font=('Segoe UI', 12, 'bold'),
                       bg=COLORS['bg_dark'], fg=COLORS['text_dim'], cursor='hand2')
        btn.pack(side='right', padx=(3, 0))
        btn.bind('<Button-1>', lambda e: cmd())
        btn.bind('<Enter>', lambda e: btn.config(fg=COLORS['error']))
        btn.bind('<Leave>', lambda e: btn.config(fg=COLORS['text_dim']))

    def _hdr_link(self, parent, text, cmd):
        btn = tk.Label(parent, text=text, font=('Segoe UI', 9),
                       bg=COLORS['bg_dark'], fg=COLORS['text_dim'], cursor='hand2')
        btn.pack(side='right', padx=(0, 8))
        btn.bind('<Button-1>', lambda e: cmd())
        btn.bind('<Enter>', lambda e: btn.config(fg=COLORS['accent']))
        btn.bind('<Leave>', lambda e: btn.config(fg=COLORS['text_dim']))

    def _drag_bind(self, widget):
        widget.bind('<Button-1>',  self._start_drag)
        widget.bind('<B1-Motion>', self._on_drag)
        for child in widget.winfo_children():
            # Skip interactive buttons — they have their own <Button-1> handlers
            try:
                if child.cget('cursor') == 'hand2':
                    continue
            except:
                pass
            child.bind('<Button-1>',  self._start_drag)
            child.bind('<B1-Motion>', self._on_drag)

    def _start_drag(self, e):
        self._drag_start_x = e.x_root
        self._drag_start_y = e.y_root
        self._win_start_x = self.winfo_x()
        self._win_start_y = self.winfo_y()

    def _on_drag(self, e):
        dx = e.x_root - self._drag_start_x
        dy = e.y_root - self._drag_start_y
        self.geometry(f"+{self._win_start_x + dx}+{self._win_start_y + dy}")

    def _toast(self, text):
        try:
            t = tk.Toplevel(self)
            t.overrideredirect(True)
            t.attributes('-topmost', True)
            t.configure(bg=COLORS['success'])
            x = self.winfo_x() + (self.winfo_width() - 240) // 2
            y = self.winfo_y() + self.winfo_height() + 6
            t.geometry(f"240x34+{x}+{y}")
            tk.Label(t, text=text, font=('Segoe UI', 9, 'bold'),
                     bg=COLORS['success'], fg='white').pack(expand=True)
            t.after(1800, t.destroy)
        except:
            pass

    def _show_main_app(self):
        if self.parent_app:
            self.parent_app.deiconify() # Un-minimize if it was minimized
            self.parent_app.lift()      # Bring it up in the stacking order
            self.parent_app.focus_force() # Force the OS to give it keyboard/mouse focus
            
            # The Topmost Trick: Force it strictly to the front, then let it go back to normal
            self.parent_app.attributes('-topmost', True)
            self.parent_app.attributes('-topmost', False)


# ============================================================================
# MAIN APPLICATION
# ============================================================================
class MainApplication:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("YouTube Downloader Pro")
        self.root.geometry("800x600")
        self.root.configure(bg=COLORS['bg_darkest'])
        self.root.minsize(700, 500)

        self._configure_styles()

        self.quick_window  = None
        self.current_page  = "start"
        self.pending_refresh_scheduled = False
        self.queue_refresh_scheduled = False

        self._create_ui()

        link_queue.add_callback(self._update_status)
        download_manager.add_callback(self._update_status)

        self._update_status()

    def _configure_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TCombobox',
                        fieldbackground=COLORS['bg_light'],
                        background=COLORS['bg_light'],
                        foreground=COLORS['text_primary'])
        style.map('TCombobox',
                  fieldbackground=[('readonly', COLORS['bg_light'])],
                  selectbackground=[('readonly', COLORS['accent'])])

    def _create_ui(self):
        main_container = tk.Frame(self.root, bg=COLORS['bg_darkest'])
        main_container.pack(fill='both', expand=True)

        # Sidebar
        self.sidebar = tk.Frame(main_container, bg=COLORS['bg_dark'], width=220)
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)

        # Logo
        logo_frame = tk.Frame(self.sidebar, bg=COLORS['bg_dark'])
        logo_frame.pack(fill='x', padx=20, pady=(25, 5))
        tk.Label(logo_frame, text="YOUTUBE", font=('Segoe UI', 16, 'bold'),
                 bg=COLORS['bg_dark'], fg=COLORS['text_primary']).pack(anchor='w')
        tk.Label(logo_frame, text="DOWNLOADER", font=('Segoe UI', 16, 'bold'),
                 bg=COLORS['bg_dark'], fg=COLORS['text_primary']).pack(anchor='w')
        tk.Label(logo_frame, text="PRO", font=('Segoe UI', 10, 'bold'),
                 bg=COLORS['bg_dark'], fg=COLORS['accent']).pack(anchor='w', pady=(2, 0))

        # Navigation
        nav_frame = tk.Frame(self.sidebar, bg=COLORS['bg_dark'])
        nav_frame.pack(fill='x', padx=15, pady=(30, 0))

        self.nav_buttons = {}
        nav_items = [
            ("start",    "Start Download"),
            ("pending",  "Pending Links"),
            ("queue",    "Download Queue"),
            ("history",  "History"),
            ("settings", "Settings"),
        ]
        for page_id, text in nav_items:
            btn = tk.Label(nav_frame, text=text, font=('Segoe UI', 11),
                           bg=COLORS['bg_dark'], fg=COLORS['text_dim'],
                           cursor='hand2', padx=15, pady=10, anchor='w')
            btn.pack(fill='x', pady=2)
            btn.bind('<Button-1>', lambda e, p=page_id: self._navigate(p))
            btn.bind('<Enter>', lambda e, b=btn: self._nav_hover(b, True))
            btn.bind('<Leave>', lambda e, b=btn: self._nav_hover(b, False))
            self.nav_buttons[page_id] = btn

        self._update_nav_styles()

        # Status
        status_frame = tk.Frame(self.sidebar, bg=COLORS['bg_dark'])
        status_frame.pack(side='bottom', fill='x', padx=20, pady=(0, 20))

        self.link_status_label = tk.Label(status_frame, text="Links: None",
                                          font=('Segoe UI', 9),
                                          bg=COLORS['bg_dark'], fg=COLORS['text_muted'])
        self.link_status_label.pack(anchor='w')

        self.download_status_label = tk.Label(status_frame, text="Downloads: Ready",
                                              font=('Segoe UI', 9),
                                              bg=COLORS['bg_dark'], fg=COLORS['text_muted'])
        self.download_status_label.pack(anchor='w', pady=(2, 0))

        exit_btn = tk.Label(status_frame, text="Exit", font=('Segoe UI', 10),
                            bg=COLORS['bg_dark'], fg=COLORS['text_dim'], cursor='hand2')
        exit_btn.pack(anchor='w', pady=(15, 0))
        exit_btn.bind('<Button-1>', lambda e: self._exit())
        exit_btn.bind('<Enter>', lambda e: exit_btn.config(fg=COLORS['error']))
        exit_btn.bind('<Leave>', lambda e: exit_btn.config(fg=COLORS['text_dim']))

        # Content area
        self.content_frame = tk.Frame(main_container, bg=COLORS['bg_darkest'])
        self.content_frame.pack(side='left', fill='both', expand=True)

        self.pages = {}
        self._create_start_page()
        self._create_pending_page()
        self._create_queue_page()
        self._create_history_page()
        self._create_settings_page()

        self._show_page("start")

    def _nav_hover(self, btn, entering):
        if btn != self.nav_buttons.get(self.current_page):
            btn.config(bg=COLORS['bg_light'] if entering else COLORS['bg_dark'],
                       fg=COLORS['text_primary'] if entering else COLORS['text_dim'])

    def _update_nav_styles(self):
        for page_id, btn in self.nav_buttons.items():
            if page_id == self.current_page:
                btn.config(bg=COLORS['bg_light'], fg=COLORS['text_primary'])
            else:
                btn.config(bg=COLORS['bg_dark'], fg=COLORS['text_dim'])

    def _navigate(self, page_id):
        self.current_page = page_id
        self._update_nav_styles()
        self._show_page(page_id)
        if page_id == "start":
            self._open_quick_window()

    def _show_page(self, page_id):
        for pid, page in self.pages.items():
            page.pack_forget()
        if page_id in self.pages:
            self.pages[page_id].pack(fill='both', expand=True)
            if page_id == "pending":
                self._refresh_pending_page()
            elif page_id == "queue":
                self._refresh_queue_page()
            elif page_id == "history":
                self._refresh_history_page()

    # ── Start page ────────────────────────────────────────────────────────────

    def _create_start_page(self):
        page = tk.Frame(self.content_frame, bg=COLORS['bg_darkest'])
        self.pages["start"] = page

        # FIX: use a taller card so the button isn't clipped
        card = ModernCard(page)
        card.place(relx=0.5, rely=0.5, anchor='center', width=420, height=320)

        tk.Label(card, text="Quick Download", font=('Segoe UI', 20, 'bold'),
                 bg=COLORS['bg_medium'], fg=COLORS['text_primary']).pack(pady=(35, 10))

        tk.Label(card,
                 text="Open the floating download window\nto quickly paste and download videos\n\nURLs copied to clipboard are detected automatically!",
                 font=('Segoe UI', 11), bg=COLORS['bg_medium'],
                 fg=COLORS['text_dim'], justify='center').pack(pady=10)

        # Ensure button is packed with correct parent background
        btn_frame = tk.Frame(card, bg=COLORS['bg_medium'])
        btn_frame.pack(pady=20)

        btn = ModernButton(btn_frame, "Open Download Window",
                           command=self._open_quick_window,
                           width=210, height=50)
        btn.pack()

    # ── Pending page ──────────────────────────────────────────────────────────

    def _create_pending_page(self):
        page = tk.Frame(self.content_frame, bg=COLORS['bg_darkest'])
        self.pages["pending"] = page

        header = tk.Frame(page, bg=COLORS['bg_darkest'])
        header.pack(fill='x', padx=30, pady=(25, 15))
        tk.Label(header, text="Pending Links", font=('Segoe UI', 20, 'bold'),
                 bg=COLORS['bg_darkest'], fg=COLORS['text_primary']).pack(side='left')

        self.pending_status_label = tk.Label(header, text="",
                                             font=('Segoe UI', 10),
                                             bg=COLORS['bg_darkest'], fg=COLORS['text_dim'])
        self.pending_status_label.pack(side='right')

        tabs_frame = tk.Frame(page, bg=COLORS['bg_darkest'])
        tabs_frame.pack(fill='x', padx=30, pady=(0, 15))

        self.pending_tab = tk.StringVar(value="available")
        self.tab_buttons = {}
        for tab_id, text in [("available", "Available"), ("processing", "Processing"), ("failed", "Failed")]:
            btn = tk.Label(tabs_frame, text=text, font=('Segoe UI', 10, 'bold'),
                           bg=COLORS['bg_light'], fg=COLORS['text_dim'],
                           padx=20, pady=8, cursor='hand2')
            btn.pack(side='left', padx=(0, 5))
            btn.bind('<Button-1>', lambda e, t=tab_id: self._switch_pending_tab(t))
            self.tab_buttons[tab_id] = btn

        actions_frame = tk.Frame(page, bg=COLORS['bg_darkest'])
        actions_frame.pack(fill='x', padx=30, pady=(0, 15))

        self.download_all_btn = ModernButton(actions_frame, "Download All",
                                             command=self._download_all_available,
                                             width=130, height=38)
        self.download_all_btn.pack(side='left', padx=(0, 10))

        self.clear_pending_btn = ModernButton(actions_frame, "Clear",
                                              command=self._clear_current_pending_tab,
                                              width=80, height=38,
                                              bg=COLORS['bg_light'], hover_bg=COLORS['bg_hover'])
        self.clear_pending_btn.pack(side='left', padx=(0, 10))

        self.retry_all_btn = ModernButton(actions_frame, "Retry All",
                                          command=link_queue.retry_all_failed,
                                          width=100, height=38,
                                          bg=COLORS['bg_light'], hover_bg=COLORS['bg_hover'])
        self.retry_all_btn.pack(side='left')

        ModernButton(actions_frame, "Refresh",
                     command=self._refresh_pending_page,
                     width=90, height=38,
                     bg=COLORS['bg_light'], hover_bg=COLORS['bg_hover']).pack(side='right')

        scroll_container = tk.Frame(page, bg=COLORS['bg_darkest'])
        scroll_container.pack(fill='both', expand=True, padx=30, pady=(0, 20))

        canvas = tk.Canvas(scroll_container, bg=COLORS['bg_darkest'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_container, orient='vertical', command=canvas.yview)

        self.pending_list_frame = tk.Frame(canvas, bg=COLORS['bg_darkest'])
        self.pending_list_frame.bind('<Configure>',
                                     lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=self.pending_list_frame, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        bind_mousewheel_scroll(canvas)

        self._update_pending_tab_styles()

    def _switch_pending_tab(self, tab_id):
        self.pending_tab.set(tab_id)
        self._update_pending_tab_styles()
        self._refresh_pending_page()

    def _update_pending_tab_styles(self):
        current = self.pending_tab.get()
        for tab_id, btn in self.tab_buttons.items():
            if tab_id == current:
                btn.config(bg=COLORS['accent'], fg=COLORS['text_primary'])
            else:
                btn.config(bg=COLORS['bg_light'], fg=COLORS['text_dim'])
        if current != "available":
            self.download_all_btn.pack_forget()
        else:
            self.download_all_btn.pack(side='left', padx=(0, 10))
        if current != "failed":
            self.retry_all_btn.pack_forget()
        else:
            self.retry_all_btn.pack(side='left')

    def _refresh_pending_page(self):
        for w in self.pending_list_frame.winfo_children():
            w.destroy()

        counts = link_queue.get_counts()
        self.pending_status_label.config(
            text=f"Available: {counts['available']} | Processing: {counts['pending']} | Failed: {counts['failed']}")

        self.tab_buttons['available'].config(text=f"Available ({counts['available']})")
        self.tab_buttons['processing'].config(text=f"Processing ({counts['pending']})")
        self.tab_buttons['failed'].config(text=f"Failed ({counts['failed']})")

        current_tab = self.pending_tab.get()
        if current_tab == "available":
            items = link_queue.get_available_links()
        elif current_tab == "processing":
            items = link_queue.get_pending_links()
        else:
            items = link_queue.get_failed_links()

        if not items:
            msgs = {
                "available":  "No videos available for download",
                "processing": "No links being processed",
                "failed":     "No failed links",
            }
            tk.Label(self.pending_list_frame, text=msgs[current_tab],
                     font=('Segoe UI', 12), bg=COLORS['bg_darkest'],
                     fg=COLORS['text_dim']).pack(pady=50)
            return

        for link_item in items:
            self._create_link_item_widget(link_item)

    def _create_link_item_widget(self, link_item: LinkItem):
        card = ModernCard(self.pending_list_frame)
        card.pack(fill='x', pady=4)

        status_colors = {
            LinkStatus.PENDING:    COLORS['text_dim'],
            LinkStatus.PROCESSING: COLORS['warning'],
            LinkStatus.AVAILABLE:  COLORS['success'],
            LinkStatus.FAILED:     COLORS['error'],
        }
        tk.Frame(card, bg=status_colors.get(link_item.status, COLORS['text_dim']), width=4
                 ).pack(side='left', fill='y')

        info_frame = tk.Frame(card, bg=COLORS['bg_medium'])
        info_frame.pack(side='left', fill='both', expand=True, padx=12, pady=10)

        title = link_item.title or f"Loading... ({link_item.video_id})"
        title = (title[:47] + "...") if len(title) > 50 else title

        tk.Label(info_frame, text=title, font=('Segoe UI', 11, 'bold'),
                 bg=COLORS['bg_medium'], fg=COLORS['text_primary'], anchor='w').pack(fill='x')

        if link_item.status == LinkStatus.AVAILABLE:
            meta = f"{format_duration(link_item.duration)} | {format_views(link_item.views)} views"
            tk.Label(info_frame, text=meta, font=('Segoe UI', 9),
                     bg=COLORS['bg_medium'], fg=COLORS['text_dim'], anchor='w').pack(fill='x')
        elif link_item.status == LinkStatus.FAILED:
            tk.Label(info_frame, text=f"Error: {link_item.error[:50]}",
                     font=('Segoe UI', 9), bg=COLORS['bg_medium'],
                     fg=COLORS['error'], anchor='w').pack(fill='x')
        elif link_item.status == LinkStatus.PROCESSING:
            tk.Label(info_frame, text="Fetching video information...",
                     font=('Segoe UI', 9), bg=COLORS['bg_medium'],
                     fg=COLORS['warning'], anchor='w').pack(fill='x')
        else:
            tk.Label(info_frame, text="Waiting in queue...",
                     font=('Segoe UI', 9), bg=COLORS['bg_medium'],
                     fg=COLORS['text_dim'], anchor='w').pack(fill='x')

        actions = tk.Frame(card, bg=COLORS['bg_medium'])
        actions.pack(side='right', padx=10, pady=10)

        if link_item.status == LinkStatus.AVAILABLE:
            ModernButton(actions, "Download",
                         command=lambda: self._download_link(link_item),
                         width=90, height=32, font_size=9).pack(side='left', padx=(0, 5))

        if link_item.status == LinkStatus.FAILED:
            ModernButton(actions, "Retry",
                         command=lambda: link_queue.retry_link(link_item.video_id),
                         width=70, height=32, font_size=9,
                         bg=COLORS['bg_light'], hover_bg=COLORS['bg_hover']).pack(side='left', padx=(0, 5))

        rm = tk.Label(actions, text="✕", font=('Segoe UI', 10, 'bold'),
                      bg=COLORS['bg_medium'], fg=COLORS['text_dim'], cursor='hand2')
        rm.pack(side='left')
        rm.bind('<Button-1>', lambda e: link_queue.remove_link(link_item.video_id))
        rm.bind('<Enter>', lambda e: rm.config(fg=COLORS['error']))
        rm.bind('<Leave>', lambda e: rm.config(fg=COLORS['text_dim']))

    def _download_link(self, link_item: LinkItem):
        config = {
            'type':    'video',
            'quality': settings.get('video_quality'),
            'format':  settings.get('video_format').lower(),
        }
        di = DownloadItem(
            id=str(id(link_item)),
            url=link_item.url,
            title=link_item.title,
            config=config,
            save_path=settings.get('download_path'),
        )
        download_manager.add(di)
        link_queue.remove_link(link_item.video_id)

    def _download_all_available(self):
        for link_item in link_queue.get_available_links():
            self._download_link(link_item)

    def _clear_current_pending_tab(self):
        current = self.pending_tab.get()
        if current == "available":
            link_queue.clear_available()
        elif current == "failed":
            link_queue.clear_failed()

    # ── Queue page ────────────────────────────────────────────────────────────

    def _create_queue_page(self):
        page = tk.Frame(self.content_frame, bg=COLORS['bg_darkest'])
        self.pages["queue"] = page

        header = tk.Frame(page, bg=COLORS['bg_darkest'])
        header.pack(fill='x', padx=30, pady=(25, 15))
        tk.Label(header, text="Download Queue", font=('Segoe UI', 20, 'bold'),
                 bg=COLORS['bg_darkest'], fg=COLORS['text_primary']).pack(side='left')
        self.queue_status_label = tk.Label(header, text="",
                                           font=('Segoe UI', 10),
                                           bg=COLORS['bg_darkest'], fg=COLORS['text_dim'])
        self.queue_status_label.pack(side='right')

        actions = tk.Frame(page, bg=COLORS['bg_darkest'])
        actions.pack(fill='x', padx=30, pady=(0, 15))

        ModernButton(actions, "Clear Completed",
                     command=download_manager.clear_completed,
                     width=140, height=38,
                     bg=COLORS['bg_light'], hover_bg=COLORS['bg_hover']).pack(side='left', padx=(0, 10))
        ModernButton(actions, "Retry Failed",
                     command=download_manager.retry_failed,
                     width=110, height=38,
                     bg=COLORS['bg_light'], hover_bg=COLORS['bg_hover']).pack(side='left')
        ModernButton(actions, "Refresh",
                     command=self._refresh_queue_page,
                     width=90, height=38,
                     bg=COLORS['bg_light'], hover_bg=COLORS['bg_hover']).pack(side='right')

        scroll_container = tk.Frame(page, bg=COLORS['bg_darkest'])
        scroll_container.pack(fill='both', expand=True, padx=30, pady=(0, 20))

        canvas = tk.Canvas(scroll_container, bg=COLORS['bg_darkest'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_container, orient='vertical', command=canvas.yview)

        self.queue_list_frame = tk.Frame(canvas, bg=COLORS['bg_darkest'])
        self.queue_list_frame.bind('<Configure>',
                                   lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=self.queue_list_frame, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        bind_mousewheel_scroll(canvas)

    def _refresh_queue_page(self):
        for w in self.queue_list_frame.winfo_children():
            w.destroy()

        status = download_manager.get_status()
        self.queue_status_label.config(
            text=f"Active: {status['active']} | Pending: {status['pending']} | "
                 f"Completed: {status['completed']} | Failed: {status['failed']}")

        items = download_manager.get_all_items()
        if not items:
            tk.Label(self.queue_list_frame, text="Queue is empty",
                     font=('Segoe UI', 12), bg=COLORS['bg_darkest'],
                     fg=COLORS['text_dim']).pack(pady=50)
            return

        for item in items:
            self._create_download_item_widget(item)

    def _create_download_item_widget(self, item: DownloadItem):
        card = ModernCard(self.queue_list_frame)
        card.pack(fill='x', pady=4)

        progress = CircularProgress(card, size=45, thickness=4)
        progress.pack(side='left', padx=12, pady=10)

        status_colors = {
            "pending":     COLORS['text_dim'],
            "downloading": COLORS['accent'],
            "processing":  COLORS['warning'],
            "completed":   COLORS['success'],
            "failed":      COLORS['error'],
        }
        progress.set_color(status_colors.get(item.status, COLORS['text_dim']))
        progress.set_progress(item.progress if item.status == "downloading" else
                              100 if item.status in ("completed", "processing") else 0)

        info_frame = tk.Frame(card, bg=COLORS['bg_medium'])
        info_frame.pack(side='left', fill='both', expand=True, padx=(0, 12), pady=10)

        title = (item.title[:50] + "...") if len(item.title) > 50 else item.title
        tk.Label(info_frame, text=title, font=('Segoe UI', 11, 'bold'),
                 bg=COLORS['bg_medium'], fg=COLORS['text_primary'], anchor='w').pack(fill='x')

        if item.status == "downloading":
            status_text = f"{item.progress:.1f}% | {item.speed} | ETA: {item.eta}"
        elif item.status == "processing":
            status_text = "Processing..."
        elif item.status == "completed":
            status_text = "Completed ✓"
        elif item.status == "failed":
            status_text = f"Failed: {item.error[:40]}"
        else:
            status_text = "Waiting in queue..."

        tk.Label(info_frame, text=status_text, font=('Segoe UI', 9),
                 bg=COLORS['bg_medium'], anchor='w',
                 fg=status_colors.get(item.status, COLORS['text_dim'])).pack(fill='x')

    # ── History page ──────────────────────────────────────────────────────────

    def _create_history_page(self):
        page = tk.Frame(self.content_frame, bg=COLORS['bg_darkest'])
        self.pages["history"] = page

        header = tk.Frame(page, bg=COLORS['bg_darkest'])
        header.pack(fill='x', padx=30, pady=(25, 15))
        tk.Label(header, text="Download History", font=('Segoe UI', 20, 'bold'),
                 bg=COLORS['bg_darkest'], fg=COLORS['text_primary']).pack(side='left')
        ModernButton(header, "Clear All",
                     command=self._clear_history,
                     width=100, height=38,
                     bg=COLORS['bg_light'], hover_bg=COLORS['bg_hover']).pack(side='right')

        scroll_container = tk.Frame(page, bg=COLORS['bg_darkest'])
        scroll_container.pack(fill='both', expand=True, padx=30, pady=(0, 20))

        canvas = tk.Canvas(scroll_container, bg=COLORS['bg_darkest'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_container, orient='vertical', command=canvas.yview)

        self.history_list_frame = tk.Frame(canvas, bg=COLORS['bg_darkest'])
        self.history_list_frame.bind('<Configure>',
                                     lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=self.history_list_frame, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        bind_mousewheel_scroll(canvas)

    def _refresh_history_page(self):
        for w in self.history_list_frame.winfo_children():
            w.destroy()

        items = history.get_all()
        if not items:
            tk.Label(self.history_list_frame, text="No download history",
                     font=('Segoe UI', 12), bg=COLORS['bg_darkest'],
                     fg=COLORS['text_dim']).pack(pady=50)
            return

        for entry in items[:100]:
            card = ModernCard(self.history_list_frame)
            card.pack(fill='x', pady=3)

            color = COLORS['success'] if entry.get('status') == 'completed' else COLORS['error']
            tk.Frame(card, bg=color, width=4).pack(side='left', fill='y')

            info_frame = tk.Frame(card, bg=COLORS['bg_medium'])
            info_frame.pack(side='left', fill='both', expand=True, padx=12, pady=8)

            title = entry.get('title', 'Unknown')[:55]
            tk.Label(info_frame, text=title, font=('Segoe UI', 10, 'bold'),
                     bg=COLORS['bg_medium'], fg=COLORS['text_primary'], anchor='w').pack(fill='x')

            meta = f"{entry.get('type','video').upper()} | {entry.get('quality','')} | {entry.get('format','').upper()}"
            tk.Label(info_frame, text=meta, font=('Segoe UI', 9),
                     bg=COLORS['bg_medium'], fg=COLORS['text_dim'], anchor='w').pack(fill='x')

            timestamp = entry.get('timestamp', '')[:16].replace('T', ' ')
            tk.Label(card, text=timestamp, font=('Segoe UI', 9),
                     bg=COLORS['bg_medium'], fg=COLORS['text_muted']).pack(side='right', padx=12)

    def _clear_history(self):
        if messagebox.askyesno("Clear History", "Clear all download history?"):
            history.clear()
            self._refresh_history_page()

    # ── Settings page ─────────────────────────────────────────────────────────

    def _create_settings_page(self):
        page = tk.Frame(self.content_frame, bg=COLORS['bg_darkest'])
        self.pages["settings"] = page

        tk.Label(page, text="Settings", font=('Segoe UI', 20, 'bold'),
                 bg=COLORS['bg_darkest'], fg=COLORS['text_primary']).pack(anchor='w', padx=30, pady=(25, 20))

        scroll_container = tk.Frame(page, bg=COLORS['bg_darkest'])
        scroll_container.pack(fill='both', expand=True, padx=30, pady=(0, 20))

        canvas = tk.Canvas(scroll_container, bg=COLORS['bg_darkest'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_container, orient='vertical', command=canvas.yview)

        settings_frame = tk.Frame(canvas, bg=COLORS['bg_darkest'])
        settings_frame.bind('<Configure>',
                            lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=settings_frame, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        bind_mousewheel_scroll(canvas)

        # Download path
        tk.Label(settings_frame, text="DOWNLOAD LOCATION", font=('Segoe UI', 9, 'bold'),
                 bg=COLORS['bg_darkest'], fg=COLORS['text_dim']).pack(anchor='w', pady=(0, 8))

        path_card = ModernCard(settings_frame)
        path_card.pack(fill='x', pady=(0, 20))

        path_frame = tk.Frame(path_card, bg=COLORS['bg_medium'])
        path_frame.pack(fill='x', padx=12, pady=10)

        self.path_label = tk.Label(path_frame, text=settings.get('download_path'),
                                   font=('Segoe UI', 10), bg=COLORS['bg_medium'],
                                   fg=COLORS['text_dim'], anchor='w', wraplength=400)
        self.path_label.pack(side='left', fill='x', expand=True)

        ModernButton(path_frame, "Browse", command=self._browse_path,
                     width=80, height=32, font_size=9,
                     bg=COLORS['bg_light'], hover_bg=COLORS['bg_hover']).pack(side='right')

        # Video quality
        tk.Label(settings_frame, text="PREFERRED VIDEO QUALITY", font=('Segoe UI', 9, 'bold'),
                 bg=COLORS['bg_darkest'], fg=COLORS['text_dim']).pack(anchor='w', pady=(0, 8))

        video_card = ModernCard(settings_frame)
        video_card.pack(fill='x', pady=(0, 20))

        video_frame = tk.Frame(video_card, bg=COLORS['bg_medium'])
        video_frame.pack(fill='x', padx=12, pady=10)

        tk.Label(video_frame, text="Quality:", font=('Segoe UI', 10),
                 bg=COLORS['bg_medium'], fg=COLORS['text_secondary']).pack(side='left')

        self.video_quality_var = tk.StringVar(value=settings.get('video_quality'))
        ttk.Combobox(video_frame, textvariable=self.video_quality_var,
                     values=VIDEO_QUALITIES, width=18, state='readonly').pack(side='left', padx=10)

        tk.Label(video_frame, text="Format:", font=('Segoe UI', 10),
                 bg=COLORS['bg_medium'], fg=COLORS['text_secondary']).pack(side='left', padx=(20, 0))

        self.video_format_var = tk.StringVar(value=settings.get('video_format'))
        ttk.Combobox(video_frame, textvariable=self.video_format_var,
                     values=VIDEO_FORMATS, width=8, state='readonly').pack(side='left', padx=10)

        # Audio quality
        tk.Label(settings_frame, text="PREFERRED AUDIO QUALITY", font=('Segoe UI', 9, 'bold'),
                 bg=COLORS['bg_darkest'], fg=COLORS['text_dim']).pack(anchor='w', pady=(0, 8))

        audio_card = ModernCard(settings_frame)
        audio_card.pack(fill='x', pady=(0, 20))

        audio_frame = tk.Frame(audio_card, bg=COLORS['bg_medium'])
        audio_frame.pack(fill='x', padx=12, pady=10)

        tk.Label(audio_frame, text="Quality:", font=('Segoe UI', 10),
                 bg=COLORS['bg_medium'], fg=COLORS['text_secondary']).pack(side='left')

        self.audio_quality_var = tk.StringVar(value=settings.get('audio_quality'))
        ttk.Combobox(audio_frame, textvariable=self.audio_quality_var,
                     values=AUDIO_QUALITIES, width=12, state='readonly').pack(side='left', padx=10)

        tk.Label(audio_frame, text="Format:", font=('Segoe UI', 10),
                 bg=COLORS['bg_medium'], fg=COLORS['text_secondary']).pack(side='left', padx=(20, 0))

        self.audio_format_var = tk.StringVar(value=settings.get('audio_format'))
        ttk.Combobox(audio_frame, textvariable=self.audio_format_var,
                     values=AUDIO_FORMATS, width=8, state='readonly').pack(side='left', padx=10)

        # Advanced
        tk.Label(settings_frame, text="ADVANCED", font=('Segoe UI', 9, 'bold'),
                 bg=COLORS['bg_darkest'], fg=COLORS['text_dim']).pack(anchor='w', pady=(0, 8))

        adv_card = ModernCard(settings_frame)
        adv_card.pack(fill='x', pady=(0, 20))

        adv_frame = tk.Frame(adv_card, bg=COLORS['bg_medium'])
        adv_frame.pack(fill='x', padx=12, pady=10)

        tk.Label(adv_frame, text="Concurrent Downloads:", font=('Segoe UI', 10),
                 bg=COLORS['bg_medium'], fg=COLORS['text_secondary']).pack(side='left')

        self.concurrent_var = tk.StringVar(value=str(settings.get('max_concurrent')))
        ttk.Combobox(adv_frame, textvariable=self.concurrent_var,
                     values=['1', '2', '3', '4', '5'], width=5, state='readonly').pack(side='left', padx=10)

        check_frame = tk.Frame(adv_card, bg=COLORS['bg_medium'])
        check_frame.pack(fill='x', padx=12, pady=(0, 10))

        self.auto_paste_var = tk.BooleanVar(value=settings.get('auto_paste'))
        tk.Checkbutton(check_frame, text="Auto-detect clipboard URLs",
                       variable=self.auto_paste_var, bg=COLORS['bg_medium'],
                       fg=COLORS['text_secondary'], selectcolor=COLORS['bg_light'],
                       activebackground=COLORS['bg_medium'],
                       font=('Segoe UI', 10)).pack(anchor='w')

        self.sponsorblock_var = tk.BooleanVar(value=settings.get('sponsorblock'))
        tk.Checkbutton(check_frame, text="Remove sponsor segments (SponsorBlock)",
                       variable=self.sponsorblock_var, bg=COLORS['bg_medium'],
                       fg=COLORS['text_secondary'], selectcolor=COLORS['bg_light'],
                       activebackground=COLORS['bg_medium'],
                       font=('Segoe UI', 10)).pack(anchor='w', pady=(5, 0))

        # Update yt-dlp button in settings
        update_btn_frame = tk.Frame(adv_card, bg=COLORS['bg_medium'])
        update_btn_frame.pack(fill='x', padx=12, pady=(10, 0))
        
        self.update_btn = ModernButton(update_btn_frame, "Update yt-dlp Core",
                                       command=self._update_ytdlp,
                                       width=160, height=34, font_size=9,
                                       bg=COLORS['bg_light'], hover_bg=COLORS['bg_hover'])
        self.update_btn.pack(side='left')

        ModernButton(settings_frame, "Save Settings", command=self._save_settings,
                     width=150, height=45).pack(pady=20)

    def _update_ytdlp(self):
        self.update_btn.set_enabled(False)
        self.update_btn.text = "Updating..."
        self.update_btn._draw()
        
        def run():
            try:
                startupinfo = None
                if sys.platform == "win32":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                proc = subprocess.Popen(
                    [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    startupinfo=startupinfo, text=True
                )
                stdout, stderr = proc.communicate(timeout=120)
                
                global yt_dlp
                import importlib
                try:
                    if yt_dlp is not None:
                        importlib.reload(yt_dlp)
                    else:
                        import yt_dlp as new_yt_dlp
                        yt_dlp = new_yt_dlp
                except:
                    pass
                
                self.root.after(0, lambda: messagebox.showinfo("Update", "yt-dlp updated successfully!"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Update Error", f"Failed to update yt-dlp:\n{e}"))
            finally:
                self.root.after(0, lambda: [self.update_btn.set_enabled(True), setattr(self.update_btn, 'text', "Update yt-dlp Core"), self.update_btn._draw()])
                
        threading.Thread(target=run, daemon=True).start()

    def _browse_path(self):
        path = filedialog.askdirectory(initialdir=self.path_label.cget('text'))
        if path:
            self.path_label.config(text=path)

    def _save_settings(self):
        settings.set('download_path',  self.path_label.cget('text'))
        settings.set('video_quality',  self.video_quality_var.get())
        settings.set('video_format',   self.video_format_var.get())
        settings.set('audio_quality',  self.audio_quality_var.get())
        settings.set('audio_format',   self.audio_format_var.get())
        settings.set('max_concurrent', int(self.concurrent_var.get()))
        settings.set('auto_paste',     self.auto_paste_var.get())
        settings.set('sponsorblock',   self.sponsorblock_var.get())
        download_manager.max_workers = int(self.concurrent_var.get())
        messagebox.showinfo("Settings", "Settings saved successfully!")

    # ── Quick window ──────────────────────────────────────────────────────────

    def _open_quick_window(self):
        if self.quick_window is None or not self.quick_window.winfo_exists():
            self.quick_window = QuickDownloadWindow(self.root)
        else:
            self.quick_window.deiconify()
            self.quick_window.lift()

    # ── Status bar ────────────────────────────────────────────────────────────

    def _update_status(self):
        try:
            link_counts = link_queue.get_counts()
            if link_counts['pending'] > 0:
                self.link_status_label.config(
                    text=f"Links: {link_counts['pending']} processing, {link_counts['available']} ready",
                    fg=COLORS['warning'])
            elif link_counts['available'] > 0:
                self.link_status_label.config(
                    text=f"Links: {link_counts['available']} ready to download",
                    fg=COLORS['success'])
            else:
                self.link_status_label.config(text="Links: None", fg=COLORS['text_muted'])

            dl_status = download_manager.get_status()
            if dl_status['active'] > 0:
                self.download_status_label.config(
                    text=f"Downloads: {dl_status['active']} active", fg=COLORS['accent'])
            elif dl_status['pending'] > 0:
                self.download_status_label.config(
                    text=f"Downloads: {dl_status['pending']} queued", fg=COLORS['warning'])
            else:
                self.download_status_label.config(text="Downloads: Ready", fg=COLORS['success'])

            if 'pending' in self.nav_buttons:
                btn_text = "Pending Links"
                if link_counts['available'] > 0:
                    btn_text = f"Pending Links ({link_counts['available']})"
                self.nav_buttons['pending'].config(text=btn_text)

            if self.current_page == "pending":
                if not self.pending_refresh_scheduled:
                    self.pending_refresh_scheduled = True
                    self.root.after(500, self._throttled_refresh_pending)
            elif self.current_page == "queue":
                if not self.queue_refresh_scheduled:
                    self.queue_refresh_scheduled = True
                    self.root.after(500, self._throttled_refresh_queue)
        except:
            pass

    def _throttled_refresh_pending(self):
        self.pending_refresh_scheduled = False
        self._refresh_pending_page()

    def _throttled_refresh_queue(self):
        self.queue_refresh_scheduled = False
        self._refresh_queue_page()

    # ── Exit ──────────────────────────────────────────────────────────────────

    def _exit(self):
        status = download_manager.get_status()
        if status['active'] > 0:
            if not messagebox.askyesno("Exit", f"{status['active']} download(s) in progress. Exit anyway?"):
                return
        if self.quick_window:
            try:
                self.quick_window.destroy()
            except:
                pass
        self.root.destroy()

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._exit)
        self.root.mainloop()


# ============================================================================
# STARTUP CHECKER
# ============================================================================
class StartupChecker:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("YouTube Downloader Pro - Setup Check")
        self.root.geometry("500x440")
        self.root.configure(bg=COLORS['bg_darkest'])
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self._center_window()

        self._drag_start_x = 0
        self._drag_start_y = 0
        self._win_start_x = 0
        self._win_start_y = 0

        self.checks_done = False
        self.internet_ok = False
        self.ytdlp_ok = False
        self.ffmpeg_ok = False
        self.folder_ok = False

        self._build_ui()
        self.root.after(500, self._start_checks)

    def _center_window(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = 500, 440
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _start_drag(self, e):
        self._drag_start_x = e.x_root
        self._drag_start_y = e.y_root
        self._win_start_x = self.root.winfo_x()
        self._win_start_y = self.root.winfo_y()

    def _on_drag(self, e):
        dx = e.x_root - self._drag_start_x
        dy = e.y_root - self._drag_start_y
        self.root.geometry(f"+{self._win_start_x + dx}+{self._win_start_y + dy}")

    def _build_ui(self):
        outer = tk.Frame(self.root, bg=COLORS['bg_dark'], highlightthickness=1, highlightbackground=COLORS['border'])
        outer.pack(fill='both', expand=True, padx=2, pady=2)

        title_bar = tk.Frame(outer, bg=COLORS['bg_dark'])
        title_bar.pack(fill='x', padx=15, pady=(15, 5))
        title_bar.bind('<Button-1>', self._start_drag)
        title_bar.bind('<B1-Motion>', self._on_drag)

        tk.Label(title_bar, text="YT DOWNLOADER PRO", font=('Segoe UI', 12, 'bold'),
                 bg=COLORS['bg_dark'], fg=COLORS['accent']).pack(side='left')
        tk.Label(title_bar, text=" - HEALTH CHECK", font=('Segoe UI', 12, 'bold'),
                 bg=COLORS['bg_dark'], fg=COLORS['text_primary']).pack(side='left')

        close_btn = tk.Label(title_bar, text="✕", font=('Segoe UI', 12, 'bold'),
                             bg=COLORS['bg_dark'], fg=COLORS['text_dim'], cursor='hand2')
        close_btn.pack(side='right')
        close_btn.bind('<Button-1>', lambda e: sys.exit(0))
        close_btn.bind('<Enter>', lambda e: close_btn.config(fg=COLORS['error']))
        close_btn.bind('<Leave>', lambda e: close_btn.config(fg=COLORS['text_dim']))

        tk.Frame(outer, bg=COLORS['border'], height=1).pack(fill='x', padx=15, pady=(5, 15))

        self.rows_frame = tk.Frame(outer, bg=COLORS['bg_dark'])
        self.rows_frame.pack(fill='x', padx=25)

        self.status_indicators = []
        self.status_labels = []

        checks_info = [
            "Internet Connection",
            "yt-dlp Core Library",
            "FFmpeg Media Encoder",
            "Download Folder Permissions"
        ]

        for i, text in enumerate(checks_info):
            row = tk.Frame(self.rows_frame, bg=COLORS['bg_dark'], pady=6)
            row.pack(fill='x')

            ind = tk.Label(row, text="○", font=('Segoe UI', 12, 'bold'),
                           bg=COLORS['bg_dark'], fg=COLORS['text_dim'], width=3)
            ind.pack(side='left')
            self.status_indicators.append(ind)

            lbl = tk.Label(row, text=f"{text}: Pending...", font=('Segoe UI', 10),
                           bg=COLORS['bg_dark'], fg=COLORS['text_secondary'])
            lbl.pack(side='left', padx=10)
            self.status_labels.append(lbl)

        self.card = ModernCard(outer)
        self.card.pack(fill='both', expand=True, padx=25, pady=(15, 10))

        self.card_label = tk.Label(self.card, text="Initializing checks...", font=('Segoe UI', 10),
                                   bg=COLORS['bg_medium'], fg=COLORS['text_secondary'], wraplength=400, justify='center')
        self.card_label.pack(expand=True, padx=15, pady=15)

        self.btn_frame = tk.Frame(outer, bg=COLORS['bg_dark'])
        self.btn_frame.pack(fill='x', padx=25, pady=(5, 15))

        self.exit_btn = ModernButton(self.btn_frame, "Exit", command=lambda: sys.exit(0),
                                     width=90, height=36, bg=COLORS['bg_light'], hover_bg=COLORS['bg_hover'])
        self.exit_btn.pack(side='left')

        self.action_btns = []

    def _set_check_status(self, idx, status, text):
        colors = {
            "checking": COLORS['warning'],
            "pass": COLORS['success'],
            "warn": COLORS['warning'],
            "fail": COLORS['error'],
            "pending": COLORS['text_dim']
        }
        symbols = {
            "checking": "●",
            "pass": "✓",
            "warn": "⚠",
            "fail": "✗",
            "pending": "○"
        }
        self.status_indicators[idx].config(text=symbols[status], fg=colors[status])
        self.status_labels[idx].config(text=text, fg=COLORS['text_primary'] if status == "pass" else COLORS['text_secondary'])

    def _start_checks(self):
        threading.Thread(target=self._run_checks_thread, daemon=True).start()

    def _run_checks_thread(self):
        self.root.after(0, lambda: self._set_check_status(0, "checking", "Connecting to YouTube..."))
        time.sleep(0.3)
        import socket
        try:
            socket.setdefaulttimeout(4)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("www.youtube.com", 443))
            self.internet_ok = True
            self.root.after(0, lambda: self._set_check_status(0, "pass", "YouTube: Connected"))
        except:
            self.internet_ok = False
            self.root.after(0, lambda: self._set_check_status(0, "fail", "YouTube: Unreachable (Offline)"))

        self.root.after(0, lambda: self._set_check_status(1, "checking", "Verifying yt-dlp core..."))
        time.sleep(0.3)
        global yt_dlp
        if yt_dlp is None:
            try:
                import yt_dlp
            except ImportError:
                pass
        
        if yt_dlp is None:
            self.root.after(0, lambda: self._set_check_status(1, "checking", "yt-dlp missing. Installing..."))
            try:
                startupinfo = None
                if sys.platform == "win32":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"], startupinfo=startupinfo)
                import yt_dlp
                self.ytdlp_ok = True
                self.root.after(0, lambda: self._set_check_status(1, "pass", "yt-dlp: Installed successfully"))
            except Exception as e:
                self.ytdlp_ok = False
                self.root.after(0, lambda: self._set_check_status(1, "fail", f"yt-dlp: Install failed ({str(e)[:40]})"))
        else:
            self.ytdlp_ok = True
            try:
                ver = yt_dlp.version.__version__
            except:
                ver = "Installed"
            self.root.after(0, lambda: self._set_check_status(1, "pass", f"yt-dlp: Ready ({ver})"))

        self.root.after(0, lambda: self._set_check_status(2, "checking", "Locating FFmpeg..."))
        time.sleep(0.3)
        self.ffmpeg_ok = is_ffmpeg_available()
        if self.ffmpeg_ok:
            self.root.after(0, lambda: self._set_check_status(2, "pass", "FFmpeg: Available"))
        else:
            self.root.after(0, lambda: self._set_check_status(2, "warn", "FFmpeg: Missing (Merging/MP3 disabled)"))

        self.root.after(0, lambda: self._set_check_status(3, "checking", "Verifying download path..."))
        time.sleep(0.3)
        try:
            dpath = settings.get('download_path')
            p = Path(dpath)
            p.mkdir(parents=True, exist_ok=True)
            test_file = p / f".test_write_{int(time.time())}"
            test_file.touch()
            test_file.unlink()
            self.folder_ok = True
            self.root.after(0, lambda: self._set_check_status(3, "pass", f"Downloads: Writable ({p.name})"))
        except Exception as e:
            self.folder_ok = False
            self.root.after(0, lambda: self._set_check_status(3, "fail", "Downloads: Path not writable"))

        self.root.after(0, self._evaluate_results)

    def _clear_action_buttons(self):
        for btn in self.action_btns:
            btn.destroy()
        self.action_btns.clear()

    def _evaluate_results(self):
        self._clear_action_buttons()

        if not self.ytdlp_ok:
            self.card_label.config(
                text="CRITICAL ERROR: The core downloader library (yt-dlp) is missing and could not be installed automatically.\n\nTroubleshooting:\nRun 'pip install yt-dlp' in your cmd/powershell to fix this.",
                fg=COLORS['error']
            )
            retry = ModernButton(self.btn_frame, "Retry Checks", command=self._retry_all, width=120, height=36)
            retry.pack(side='right')
            self.action_btns.append(retry)
            return

        if not self.folder_ok:
            self.card_label.config(
                text=f"CRITICAL ERROR: The download directory is not writable:\n'{settings.get('download_path')}'\n\nTroubleshooting:\nPlease change the download path inside 'yt_downloader_settings.json' or run the app as Administrator.",
                fg=COLORS['error']
            )
            retry = ModernButton(self.btn_frame, "Retry Checks", command=self._retry_all, width=120, height=36)
            retry.pack(side='right')
            self.action_btns.append(retry)
            return

        if not self.internet_ok:
            self.card_label.config(
                text="WARNING: YouTube is unreachable. Please check your internet connection.\nDownloads will fail if you are offline.",
                fg=COLORS['warning']
            )
            launch = ModernButton(self.btn_frame, "Launch Anyway", command=self._launch_app, width=120, height=36, bg=COLORS['warning'], hover_bg='#ffbb33')
            launch.pack(side='right', padx=(10, 0))
            self.action_btns.append(launch)

            retry = ModernButton(self.btn_frame, "Retry Checks", command=self._retry_all, width=120, height=36, bg=COLORS['bg_light'], hover_bg=COLORS['bg_hover'])
            retry.pack(side='right')
            self.action_btns.append(retry)
            return

        if not self.ffmpeg_ok:
            self.card_label.config(
                text="FFmpeg is missing! High-quality downloads (>720p) and MP3/M4A audio extraction will fail.\n\nRecommendations:\nClick 'Install FFmpeg' to auto-install via winget, OR copy ffmpeg.exe to the script folder.",
                fg=COLORS['warning']
            )
            
            self.install_btn = ModernButton(self.btn_frame, "Install FFmpeg", command=self._install_ffmpeg, width=130, height=36, bg=COLORS['accent'], hover_bg=COLORS['accent_hover'])
            self.install_btn.pack(side='right', padx=(10, 0))
            self.action_btns.append(self.install_btn)

            self.ignore_btn = ModernButton(self.btn_frame, "Ignore & Launch", command=self._launch_app, width=130, height=36, bg=COLORS['bg_light'], hover_bg=COLORS['bg_hover'])
            self.ignore_btn.pack(side='right')
            self.action_btns.append(self.ignore_btn)
            return

        self.card_label.config(
            text="The app can run smoothly!\nLaunching application...",
            fg=COLORS['success']
        )
        launch = ModernButton(self.btn_frame, "Launch App", command=self._launch_app, width=120, height=36, bg=COLORS['success'], hover_bg='#00e676')
        launch.pack(side='right')
        self.action_btns.append(launch)

        self.root.after(1500, self._launch_app)

    def _retry_all(self):
        self._clear_action_buttons()
        for i in range(4):
            self._set_check_status(i, "pending", "Waiting...")
        self.card_label.config(text="Re-running checks...", fg=COLORS['text_secondary'])
        self.root.after(500, self._start_checks)

    def _install_ffmpeg(self):
        self.install_btn.set_enabled(False)
        self.ignore_btn.set_enabled(False)
        self.card_label.config(text="Downloading and installing FFmpeg via Windows Package Manager (winget)...\nThis may take a minute. Please wait...", fg=COLORS['warning'])
        
        def run():
            try:
                startupinfo = None
                if sys.platform == "win32":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                proc = subprocess.Popen(
                    ['winget', 'install', '--id', 'Gyan.FFmpeg', '--silent', '--accept-source-agreements', '--accept-package-agreements'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    startupinfo=startupinfo, text=True
                )
                stdout, stderr = proc.communicate(timeout=300)
                
                if is_ffmpeg_available():
                    self.root.after(0, self._on_install_success)
                else:
                    proc2 = subprocess.Popen(
                        ['winget', 'install', 'Gyan.FFmpeg', '--accept-source-agreements'],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        startupinfo=startupinfo, text=True
                    )
                    proc2.communicate(timeout=300)
                    if is_ffmpeg_available():
                        self.root.after(0, self._on_install_success)
                    else:
                        self.root.after(0, lambda: self._on_install_failed(stdout + "\n" + stderr))
            except Exception as e:
                self.root.after(0, lambda: self._on_install_failed(str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _on_install_success(self):
        self.ffmpeg_ok = True
        self._set_check_status(2, "pass", "FFmpeg: Installed successfully")
        self.card_label.config(text="FFmpeg installed successfully!\nThe app can now run smoothly.", fg=COLORS['success'])
        self._evaluate_results()

    def _on_install_failed(self, log):
        self._set_check_status(2, "fail", "FFmpeg: Installation failed")
        self.card_label.config(
            text="FFmpeg installation via winget failed.\n\nTroubleshooting:\n1. Open PowerShell and run: winget install Gyan.FFmpeg\n2. Or download ffmpeg static zip, extract it, and place ffmpeg.exe in the same folder as this script.",
            fg=COLORS['error']
        )
        self.install_btn.set_enabled(True)
        self.ignore_btn.set_enabled(True)
        self._evaluate_results()

    def _launch_app(self):
        try:
            self.root.destroy()
        except:
            pass
        app = MainApplication()
        app.run()

    def run(self):
        self.root.mainloop()


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    checker = StartupChecker()
    checker.run()
