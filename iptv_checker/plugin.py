"""
Dispatcharr IPTV Checker Plugin
Checks stream status and analyzes stream quality
"""

import logging
import subprocess
import json
import os
import re
import csv
import time
import threading
import urllib.request
import urllib.error
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# Django ORM imports (plugins run inside the Django backend process)
from apps.channels.models import Channel, ChannelGroup, Stream, ChannelStream
from django.db import transaction
from core.utils import send_websocket_update

# Scheduler imports
try:
    import pytz
    PYTZ_AVAILABLE = True
except ImportError:
    PYTZ_AVAILABLE = False

# Django/Dispatcharr imports for metadata updates
try:
    from apps.proxy.ts_proxy.services.channel_service import ChannelService
    DISPATCHARR_INTEGRATION_AVAILABLE = True
except ImportError:
    DISPATCHARR_INTEGRATION_AVAILABLE = False

# Setup logging
class PluginNameFilter(logging.Filter):
    def filter(self, record):
        if not record.getMessage().startswith('[IPTV Checker]'):
            record.msg = f'[IPTV Checker] {record.msg}'
        return True

LOGGER = logging.getLogger("plugins.iptv_checker")
LOGGER.addFilter(PluginNameFilter())

# ---------------------------------------------------------------------------
# MODULE-LEVEL SHARED STATE
# All Plugin instances in the same process share these objects, which means
# a background thread writing to _shared_progress is immediately visible to
# any new instance that reads it — no file-read race condition.
# ---------------------------------------------------------------------------
_shared_progress_lock = threading.Lock()
_shared_progress = {"current": 0, "total": 0, "status": "idle", "start_time": None}
_shared_load_progress = {"current": 0, "total": 0, "status": "idle"}
_shared_completion_message = None          # set by bg thread, cleared on first read
_shared_pending_status_message = None      # set by status-update loop
_shared_stop_status_updates = False
_shared_status_thread = None
_shared_check_lock = threading.Lock()      # prevents duplicate check starts
_shared_timeout_retry_queue = []

# Scheduler globals
_bg_scheduler_thread = None
_scheduler_stop_event = threading.Event()
_scheduler_pending_run = False


def _get_shared_progress():
    with _shared_progress_lock:
        return dict(_shared_progress)


def _set_shared_progress(updates):
    with _shared_progress_lock:
        _shared_progress.update(updates)


class SchedulerConfig:
    DEFAULT_TIMEZONE = "America/Chicago"
    SCHEDULER_CHECK_INTERVAL = 30
    SCHEDULER_TIME_WINDOW = 30
    SCHEDULER_ERROR_WAIT = 60
    SCHEDULER_STOP_TIMEOUT = 5


# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------
class Plugin:
    key = "iptv_checker"
    name = "IPTV Checker"
    version = "0.6.0c"
    description = "Check stream status and quality for channels in specified Dispatcharr groups."

    # ------------------------------------------------------------------
    # Timezone helper
    # ------------------------------------------------------------------
    @staticmethod
    def _load_timezones_from_file():
        try:
            timezone_file = "/usr/share/zoneinfo/zone1970.tab"
            if not os.path.exists(timezone_file):
                timezone_file = os.path.join(os.path.dirname(__file__), 'zone1970.tab')
            timezones = []
            with open(timezone_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('#') or not line.strip():
                        continue
                    parts = line.strip().split('\t')
                    if len(parts) >= 3:
                        tz_name = parts[2]
                        timezones.append({"label": tz_name, "value": tz_name})
            timezones.sort(key=lambda x: x['label'])
            return timezones
        except Exception as e:
            LOGGER.warning(f"Could not load timezones: {e}, using fallback")
            return [
                {"label": "America/New_York", "value": "America/New_York"},
                {"label": "America/Los_Angeles", "value": "America/Los_Angeles"},
                {"label": "America/Chicago", "value": "America/Chicago"},
                {"label": "America/Denver", "value": "America/Denver"},
                {"label": "Europe/London", "value": "Europe/London"},
                {"label": "Europe/Paris", "value": "Europe/Paris"},
                {"label": "Europe/Berlin", "value": "Europe/Berlin"},
                {"label": "Asia/Tokyo", "value": "Asia/Tokyo"},
                {"label": "Asia/Shanghai", "value": "Asia/Shanghai"},
                {"label": "Australia/Sydney", "value": "Australia/Sydney"},
            ]

    # ------------------------------------------------------------------
    # Fields / actions
    # ------------------------------------------------------------------
    @property
    def fields(self):
        _, version_message = self._get_latest_version()
        return [
            {"id": "version_status", "label": "📦 Plugin Version", "type": "info", "help_text": version_message},
            {"id": "group_names", "label": "📂 Group(s) to Check (comma-separated)", "type": "string", "default": "", "help_text": "Channel Group names to check. Leave blank for all groups."},
            {"id": "check_alternative_streams", "label": "🔄 Check Alternative Streams", "type": "boolean", "default": True, "help_text": "Check all backup streams too. Significantly increases check time."},
            {"id": "timeout", "label": "⏱️ Connection Timeout (seconds)", "type": "number", "default": 10, "help_text": "Network connection timeout. Default: 10"},
            {"id": "probe_timeout", "label": "🔍 Probe Timeout (seconds)", "type": "number", "default": 20, "help_text": "Max time to wait for stream data after connection. Default: 20"},
            {"id": "dead_connection_retries", "label": "🔄 Dead Connection Retries", "type": "number", "default": 3, "help_text": "Retries for apparently-dead streams. Default: 3"},
            {"id": "dead_rename_format", "label": "💀 Dead Channel Rename Format", "type": "string", "default": "{name} [DEAD]", "placeholder": "[DEAD] {name}", "help_text": "Use {name} as placeholder. E.g. '{name} [DEAD]'"},
            {"id": "move_to_group_name", "label": "⚰️ Move Dead Channels to Group", "type": "string", "default": "Graveyard", "help_text": "Destination group for dead channels."},
            {"id": "low_framerate_rename_format", "label": "🐌 Low Framerate Rename Format", "type": "string", "default": "{name} [Slow]", "placeholder": "[SLOW] {name}", "help_text": "Use {name} as placeholder."},
            {"id": "move_low_framerate_group", "label": "📁 Move Low Framerate Channels to Group", "type": "string", "default": "Slow", "help_text": "Destination group for low-fps channels."},
            {"id": "video_format_suffixes", "label": "🎬 Add Video Format Suffixes", "type": "string", "default": "UHD, FHD, HD, SD, Unknown", "help_text": "Comma-separated formats to suffix channel names with."},
            {"id": "enable_parallel_checking", "label": "⚡ Enable Parallel Stream Checking", "type": "boolean", "default": True, "help_text": "Check multiple streams simultaneously."},
            {"id": "parallel_workers", "label": "👷 Number of Parallel Workers", "type": "number", "default": 2, "help_text": "Simultaneous stream checks. Default: 2"},
            {"id": "ffprobe_flags", "label": "🔍 FFprobe Analysis Flags", "type": "string", "default": "-show_streams,-show_frames,-show_packets,-loglevel error", "help_text": "Comma-separated ffprobe flags."},
            {"id": "ffprobe_analysis_duration", "label": "⏱️ FFprobe Analysis Duration (seconds)", "type": "number", "default": 5, "help_text": "Duration for frame/packet analysis. Default: 5"},
            {"id": "ffprobe_path", "label": "📍 FFprobe Path", "type": "string", "default": "/usr/local/bin/ffprobe", "help_text": "Full path to ffprobe binary."},
            {"id": "scheduled_times", "label": "⏰ Scheduled Check Times (Cron Format)", "type": "string", "default": "", "placeholder": "0 4 * * *,0 3 1 * *", "help_text": "Comma-separated cron expressions. Leave blank to disable."},
            {"id": "scheduler_timezone", "label": "🌍 Scheduler Timezone", "type": "select", "default": "America/Chicago", "options": self._load_timezones_from_file(), "help_text": "Timezone for scheduled checks."},
            {"id": "scheduler_export_csv", "label": "💾 Export CSV After Scheduled Checks", "type": "boolean", "default": False},
            {"id": "scheduler_rename_dead_channels", "label": "💀 Rename Dead Channels After Scheduled Checks", "type": "boolean", "default": False},
            {"id": "scheduler_rename_low_framerate_channels", "label": "🐌 Rename Low Framerate Channels After Scheduled Checks", "type": "boolean", "default": False},
            {"id": "scheduler_add_video_format_suffix", "label": "🎬 Add Video Format Suffix After Scheduled Checks", "type": "boolean", "default": False},
            {"id": "scheduler_move_dead_channels", "label": "⚰️ Move Dead Channels After Scheduled Checks", "type": "boolean", "default": False},
            {"id": "scheduler_move_low_framerate_channels", "label": "📁 Move Low Framerate Channels After Scheduled Checks", "type": "boolean", "default": False},
        ]

    actions = [
        {"id": "validate_settings", "label": "✅ Validate Settings", "description": "Validate plugin settings (database connectivity, groups, etc.)."},
        {"id": "update_schedule", "label": "📅 Update Schedule", "description": "Apply schedule settings. Empty = stop scheduler."},
        {"id": "check_scheduler_status", "label": "🔍 Check Scheduler Status", "description": "Display scheduler thread status."},
        {"id": "load_groups", "label": "📥 Load Group(s)", "description": "Load channels from specified group(s)."},
        {"id": "check_streams", "label": "▶️ Start Stream Check", "description": "Start checking stream status and quality."},
        {"id": "view_progress", "label": "📊 View Check Progress", "description": "View current progress and ETA."},
        {"id": "cancel_check", "label": "🛑 Cancel Stream Check", "description": "Cancel the currently running check."},
        {"id": "view_results", "label": "📋 View Last Results", "description": "View summary of the last completed check."},
        {"id": "rename_channels", "label": "✏️ Rename Dead Channels", "description": "Rename dead channels using configured format.", "confirm": {"required": True, "title": "Rename Dead Channels?", "message": "This action is irreversible. Continue?"}},
        {"id": "move_dead_channels", "label": "⚰️ Move Dead Channels to Group", "description": "Move dead channels to configured group.", "confirm": {"required": True, "title": "Move Dead Channels?", "message": "This action is irreversible. Continue?"}},
        {"id": "rename_low_framerate_channels", "label": "🐌 Rename Low Framerate Channels", "description": "Rename channels under 30fps.", "confirm": {"required": True, "title": "Rename Low Framerate Channels?", "message": "This action is irreversible. Continue?"}},
        {"id": "move_low_framerate_channels", "label": "📁 Move Low Framerate Channels to Group", "description": "Move low-fps channels to configured group.", "confirm": {"required": True, "title": "Move Low Framerate Channels?", "message": "This action is irreversible. Continue?"}},
        {"id": "add_video_format_suffix", "label": "🎬 Add Video Format Suffix to Channels", "description": "Add format suffix like [HD] to alive channel names.", "confirm": {"required": True, "title": "Add Video Format Suffixes?", "message": "This will rename channels. Irreversible. Continue?"}},
        {"id": "view_table", "label": "📊 View Results Table", "description": "Display detailed results in table format."},
        {"id": "export_results", "label": "💾 Export Results to CSV", "description": "Export results to /data/exports/"},
        {"id": "cleanup_orphaned_tasks", "label": "🧹 Cleanup Orphaned Tasks", "description": "Remove orphaned Celery periodic tasks."},
        {"id": "clear_csv_exports", "label": "🗑️ Clear CSV Exports", "description": "Delete all CSV export files.", "confirm": {"required": True, "title": "Clear All CSV Exports?", "message": "Deletes all CSV files in /data/exports/. Cannot be undone. Continue?"}},
    ]

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------
    def __init__(self):
        self.results_file = "/data/iptv_checker_results.json"
        self.loaded_channels_file = "/data/iptv_checker_loaded_channels.json"
        self.progress_file = "/data/iptv_checker_progress.json"
        self.version_check_cache = None
        self.version_check_time = None
        self.version_check_duration = 86400

        # On first construction bootstrap shared progress from disk so state
        # survives a full process restart (e.g. Dispatcharr reload).
        with _shared_progress_lock:
            if _shared_progress.get('_bootstrapped') is None:
                disk = self._load_progress_from_disk()
                _shared_progress.update(disk)
                _shared_progress['_bootstrapped'] = True

        LOGGER.info(f"Plugin v{self.version} initialized")

    # ------------------------------------------------------------------
    # Progress helpers — always use module-level shared dict
    # ------------------------------------------------------------------
    def _load_progress_from_disk(self):
        """Load progress from the JSON file (used only at bootstrap)."""
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                LOGGER.warning(f"Failed to load progress file: {e}")
        return {"current": 0, "total": 0, "status": "idle", "start_time": None}

    def _save_progress(self):
        """Persist current shared progress to disk (for crash recovery)."""
        try:
            tmp = self.progress_file + '.tmp'
            with _shared_progress_lock:
                data = dict(_shared_progress)
            with open(tmp, 'w') as f:
                json.dump(data, f)
            os.replace(tmp, self.progress_file)
        except Exception as e:
            LOGGER.error(f"Failed to save progress file: {e}")

    @property
    def check_progress(self):
        """Always return the live shared dict (read-only view)."""
        return _get_shared_progress()

    # ------------------------------------------------------------------
    # JSON file helpers
    # ------------------------------------------------------------------
    def _load_json_file(self, filepath):
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, ValueError) as e:
            LOGGER.error(f"Corrupted JSON file {filepath}: {e}")
            return None
        except Exception as e:
            LOGGER.error(f"Failed to load JSON file {filepath}: {e}")
            return None

    def _save_json_file(self, filepath, data, indent=None):
        try:
            tmp_path = filepath + '.tmp'
            with open(tmp_path, 'w') as f:
                json.dump(data, f, indent=indent, default=str)
            os.replace(tmp_path, filepath)
        except Exception as e:
            LOGGER.error(f"Failed to save JSON file {filepath}: {e}")

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------
    def on_load(self, context):
        LOGGER.info("Plugin loaded")

    def on_unload(self):
        LOGGER.info("Plugin unloading - stopping scheduler")
        self._stop_background_scheduler()

    # ------------------------------------------------------------------
    # Scheduler helpers
    # ------------------------------------------------------------------
    def _parse_scheduled_times(self, scheduled_times_str):
        if not scheduled_times_str or not scheduled_times_str.strip():
            return []
        cron_expressions = []
        for expr in scheduled_times_str.split(','):
            expr = expr.strip()
            if expr:
                parts = expr.split()
                if len(parts) == 5:
                    cron_expressions.append(expr)
                else:
                    LOGGER.warning(f"Invalid cron expression (must have 5 fields): {expr}")
        return cron_expressions

    def _cron_matches(self, cron_expr, dt):
        try:
            parts = cron_expr.split()
            if len(parts) != 5:
                return False
            minute_expr, hour_expr, day_expr, month_expr, weekday_expr = parts
            if not self._cron_field_matches(minute_expr, dt.minute, 0, 59):
                return False
            if not self._cron_field_matches(hour_expr, dt.hour, 0, 23):
                return False
            if not self._cron_field_matches(day_expr, dt.day, 1, 31):
                return False
            if not self._cron_field_matches(month_expr, dt.month, 1, 12):
                return False
            cron_weekday = (dt.weekday() + 1) % 7
            if not self._cron_field_matches(weekday_expr, cron_weekday, 0, 6):
                return False
            return True
        except Exception as e:
            LOGGER.error(f"Error matching cron expression '{cron_expr}': {e}")
            return False

    def _cron_field_matches(self, field_expr, current_value, min_val, max_val):
        field_expr = field_expr.strip()
        if field_expr == '*':
            return True
        if field_expr.startswith('*/'):
            try:
                return current_value % int(field_expr[2:]) == 0
            except ValueError:
                return False
        if ',' in field_expr:
            try:
                return current_value in [int(v.strip()) for v in field_expr.split(',')]
            except ValueError:
                return False
        if '-' in field_expr:
            try:
                start, end = field_expr.split('-')
                return int(start.strip()) <= current_value <= int(end.strip())
            except (ValueError, IndexError):
                return False
        try:
            return current_value == int(field_expr)
        except ValueError:
            return False

    def _start_background_scheduler(self, settings):
        global _bg_scheduler_thread, _scheduler_pending_run
        if not PYTZ_AVAILABLE:
            LOGGER.error("Scheduler requires pytz")
            return
        self._stop_background_scheduler()
        scheduled_times_str = settings.get("scheduled_times", "")
        if not scheduled_times_str:
            return
        scheduled_times = self._parse_scheduled_times(scheduled_times_str)
        if not scheduled_times:
            return
        tz_str = settings.get('scheduler_timezone', SchedulerConfig.DEFAULT_TIMEZONE)
        try:
            local_tz = pytz.timezone(tz_str)
        except pytz.exceptions.UnknownTimeZoneError:
            tz_str = SchedulerConfig.DEFAULT_TIMEZONE
            local_tz = pytz.timezone(tz_str)

        def scheduler_loop():
            global _scheduler_pending_run
            last_run = {}
            LOGGER.info(f"Scheduler started. Timezone: {tz_str}, Cron: {scheduled_times}")
            while not _scheduler_stop_event.is_set():
                try:
                    now = datetime.now(local_tz)
                    current_minute = now.replace(second=0, microsecond=0)
                    for cron_expr in scheduled_times:
                        if self._cron_matches(cron_expr, now):
                            if last_run.get(cron_expr) == current_minute:
                                continue
                            LOGGER.info(f"⏰ SCHEDULED RUN at {now.strftime('%Y-%m-%d %H:%M:%S')} for {cron_expr}")
                            last_run[cron_expr] = current_minute
                            if _get_shared_progress().get('status') == 'running':
                                LOGGER.warning("Scheduled run: check already running, queuing")
                                _scheduler_pending_run = True
                            else:
                                try:
                                    self._execute_scheduled_check(settings)
                                except Exception as e:
                                    LOGGER.error(f"Scheduled check failed: {e}", exc_info=True)
                            break
                    if _scheduler_pending_run and _get_shared_progress().get('status') != 'running':
                        LOGGER.info("⏰ Executing queued scheduled run")
                        _scheduler_pending_run = False
                        try:
                            self._execute_scheduled_check(settings)
                        except Exception as e:
                            LOGGER.error(f"Queued scheduled check failed: {e}", exc_info=True)
                    _scheduler_stop_event.wait(SchedulerConfig.SCHEDULER_CHECK_INTERVAL)
                except Exception as e:
                    LOGGER.error(f"Scheduler loop error: {e}", exc_info=True)
                    _scheduler_stop_event.wait(SchedulerConfig.SCHEDULER_ERROR_WAIT)
            LOGGER.info("Scheduler stopped")

        _bg_scheduler_thread = threading.Thread(target=scheduler_loop, name="iptv-checker-scheduler", daemon=True)
        _bg_scheduler_thread.start()
        LOGGER.info("Background scheduler thread started")

    def _stop_background_scheduler(self):
        global _bg_scheduler_thread, _scheduler_pending_run
        if _bg_scheduler_thread and _bg_scheduler_thread.is_alive():
            LOGGER.info("Stopping scheduler thread...")
            _scheduler_stop_event.set()
            _bg_scheduler_thread.join(timeout=SchedulerConfig.SCHEDULER_STOP_TIMEOUT)
            _scheduler_stop_event.clear()
            _scheduler_pending_run = False
            _bg_scheduler_thread = None
            LOGGER.info("Scheduler thread stopped")

    def _execute_scheduled_check(self, settings):
        LOGGER.info("⏰ Starting scheduled check sequence")
        scheduled_logger = logging.getLogger("plugins.iptv_checker.scheduled")
        scheduled_logger.setLevel(logging.INFO)
        if not any(isinstance(f, PluginNameFilter) for f in scheduled_logger.filters):
            scheduled_logger.addFilter(PluginNameFilter())
        try:
            load_result = self.load_groups_action(settings, scheduled_logger)
            if load_result.get('status') != 'success':
                LOGGER.error(f"⏰ SCHEDULED: Load groups failed: {load_result.get('message')}")
                return
            check_result = self.check_streams_action(settings, scheduled_logger, context={'scheduled': True})
            if check_result.get('status') != 'success':
                LOGGER.error(f"⏰ SCHEDULED: Stream check failed: {check_result.get('message')}")
                return
            while _get_shared_progress().get('status') == 'running':
                time.sleep(5)
            LOGGER.info("⏰ SCHEDULED: Stream check completed")
            if settings.get('scheduler_export_csv', False):
                self.export_results_action(settings, scheduled_logger)
            if settings.get('scheduler_rename_dead_channels', False):
                self.rename_channels_action(settings, scheduled_logger)
            if settings.get('scheduler_rename_low_framerate_channels', False):
                self.rename_low_framerate_channels_action(settings, scheduled_logger)
            if settings.get('scheduler_add_video_format_suffix', False):
                self.add_video_format_suffix_action(settings, scheduled_logger)
            if settings.get('scheduler_move_dead_channels', False):
                self.move_dead_channels_action(settings, scheduled_logger)
            if settings.get('scheduler_move_low_framerate_channels', False):
                self.move_low_framerate_channels_action(settings, scheduled_logger)
            LOGGER.info("⏰ SCHEDULED: Sequence completed")
        except Exception as e:
            LOGGER.error(f"⏰ SCHEDULED: Error: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Version check
    # ------------------------------------------------------------------
    def _get_latest_version(self, owner="PiratesIRC", repo="Dispatcharr-IPTV-Checker-Plugin"):
        if self.version_check_cache and self.version_check_time:
            if time.time() - self.version_check_time < self.version_check_duration:
                return self.version_check_cache
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
        headers = {'User-Agent': 'Dispatcharr-Plugin-Version-Checker'}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                json_data = json.loads(response.read().decode('utf-8'))
                latest_version = json_data.get("tag_name", "").strip()
                if not latest_version:
                    result = (None, "ℹ️ Version Check: Unable to determine latest version")
                else:
                    latest_clean = latest_version.lstrip('v')
                    current_clean = self.version.lstrip('v')
                    try:
                        lp = [int(x) for x in latest_clean.split('.')]
                        cp = [int(x) for x in current_clean.split('.')]
                        ml = max(len(lp), len(cp))
                        lp += [0] * (ml - len(lp))
                        cp += [0] * (ml - len(cp))
                        if lp > cp:
                            message = f"🔔 Update Available: v{latest_version} (current: v{self.version})"
                        else:
                            message = f"✅ Version Status: Up to date (v{self.version})"
                    except (ValueError, AttributeError):
                        message = f"✅ Version Status: Up to date (v{self.version})"
                    result = (latest_version, message)
        except Exception:
            result = (None, f"ℹ️ Version Check: Unable to check (current: v{self.version})")
        self.version_check_cache = result
        self.version_check_time = time.time()
        return result

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def run(self, action, params, context):
        LOGGER.info(f"Run called with action: {action}")
        try:
            settings = context.get("settings", {})
            logger = context.get("logger", LOGGER)
            if action not in ["get_status_update"]:
                self._start_background_scheduler(settings)
            if logger is not LOGGER and not any(isinstance(f, PluginNameFilter) for f in logger.filters):
                logger.addFilter(PluginNameFilter())
            action_map = {
                "validate_settings": self.validate_settings_action,
                "load_groups": self.load_groups_action,
                "check_streams": self.check_streams_action,
                "view_progress": self.view_progress_action,
                "cancel_check": self.cancel_check_action,
                "view_results": self.view_results_action,
                "rename_channels": self.rename_channels_action,
                "move_dead_channels": self.move_dead_channels_action,
                "rename_low_framerate_channels": self.rename_low_framerate_channels_action,
                "move_low_framerate_channels": self.move_low_framerate_channels_action,
                "add_video_format_suffix": self.add_video_format_suffix_action,
                "view_table": self.view_table_action,
                "export_results": self.export_results_action,
                "clear_csv_exports": self.clear_csv_exports_action,
                "update_schedule": self.update_schedule_action,
                "cleanup_orphaned_tasks": self.cleanup_orphaned_tasks_action,
                "check_scheduler_status": self.check_scheduler_status_action,
                "get_status_update": self.get_status_update_action,
            }
            if action not in action_map:
                return {"status": "error", "message": f"Unknown action: {action}"}
            if action in ["check_streams", "get_status_update"]:
                return action_map[action](settings, logger, context)
            else:
                return action_map[action](settings, logger)
        except Exception as e:
            _set_shared_progress({'status': 'idle'})
            self._save_progress()
            self._stop_status_updates()
            LOGGER.error(f"Error in plugin run: {str(e)}")
            return {"status": "error", "message": str(e)}

    # ------------------------------------------------------------------
    # Status update helpers
    # ------------------------------------------------------------------
    def get_status_update_action(self, settings, logger, context):
        global _shared_completion_message, _shared_pending_status_message
        if _shared_completion_message:
            message = _shared_completion_message
            _shared_completion_message = None
            return {"status": "success", "message": message}
        prog = _get_shared_progress()
        if prog['status'] == 'running':
            current, total = prog['current'], prog['total']
            percent = (current / total * 100) if total > 0 else 0
            if prog.get('start_time') and current > 0:
                elapsed = time.time() - prog['start_time']
                eta_seconds = (elapsed / current) * (total - current)
                eta_str = "ETA: <1 min" if eta_seconds < 60 else f"ETA: {eta_seconds/60:.0f} min"
            else:
                eta_str = "ETA: calculating..."
            return {"status": "success", "message": f"Checking streams {current}/{total} - {percent:.0f}% complete | {eta_str}"}
        if _shared_pending_status_message:
            message = _shared_pending_status_message
            _shared_pending_status_message = None
            return {"status": "success", "message": message}
        return {"status": "info", "message": "No status update available"}

    def _start_status_updates(self, context):
        global _shared_status_thread, _shared_stop_status_updates
        if _shared_status_thread and _shared_status_thread.is_alive():
            return
        _shared_stop_status_updates = False
        _shared_status_thread = threading.Thread(target=self._status_update_loop, args=(context,), daemon=True)
        _shared_status_thread.start()

    def _stop_status_updates(self):
        global _shared_stop_status_updates, _shared_status_thread
        _shared_stop_status_updates = True
        if _shared_status_thread:
            _shared_status_thread.join(timeout=2)

    def _status_update_loop(self, context):
        global _shared_pending_status_message, _shared_stop_status_updates
        while not _shared_stop_status_updates and _get_shared_progress()['status'] == 'running':
            time.sleep(60)
            if _get_shared_progress()['status'] == 'running' and not _shared_stop_status_updates:
                prog = _get_shared_progress()
                current, total = prog['current'], prog['total']
                percent = (current / total * 100) if total > 0 else 0
                _shared_pending_status_message = f"Checking streams {current}/{total} - {percent:.0f}% complete"

    # ------------------------------------------------------------------
    # Validate settings
    # ------------------------------------------------------------------
    def validate_settings_action(self, settings, logger):
        validation_results = []
        has_errors = False
        try:
            channel_count = Channel.objects.count()
            group_count = ChannelGroup.objects.count()
            stream_count = Stream.objects.count()
            validation_results.append(f"✅ DB OK ({channel_count} channels, {group_count} groups, {stream_count} streams)")
            group_names_str = settings.get("group_names", "").strip()
            if group_names_str:
                try:
                    all_groups = self._get_all_groups(logger)
                    gmap = {g['name']: g['id'] for g in all_groups}
                    input_names = {n.strip() for n in group_names_str.split(',') if n.strip()}
                    valid = {n for n in input_names if n in gmap}
                    invalid = input_names - valid
                    if valid:
                        validation_results.append(f"✅ Groups: {', '.join(valid)}")
                    if invalid:
                        validation_results.append(f"⚠️ Invalid groups: {', '.join(invalid)}")
                        has_errors = True
                except Exception as e:
                    validation_results.append(f"❌ Failed to validate groups: {str(e)}")
                    has_errors = True
            else:
                validation_results.append("ℹ️ No groups specified (will check all)")
        except Exception as e:
            validation_results.append(f"❌ DB error: {str(e)[:100]}")
            has_errors = True

        for key, label, min_val in [("timeout", "Timeout", 1), ("parallel_workers", "Workers", 1), ("ffprobe_analysis_duration", "Analysis duration", 1)]:
            val = settings.get(key, min_val)
            if val < min_val:
                validation_results.append(f"⚠️ {label} must be >= {min_val} (current: {val})")
                has_errors = True

        scheduled_times_str = settings.get("scheduled_times", "").strip()
        if scheduled_times_str:
            scheduled_times = self._parse_scheduled_times(scheduled_times_str)
            if not scheduled_times:
                validation_results.append(f"❌ Invalid cron expression(s): '{scheduled_times_str}'")
                has_errors = True
            else:
                validation_results.append(f"✅ Cron schedule(s) valid: {', '.join(scheduled_times)}")
            scheduler_timezone = settings.get("scheduler_timezone", SchedulerConfig.DEFAULT_TIMEZONE)
            if PYTZ_AVAILABLE:
                try:
                    pytz.timezone(scheduler_timezone)
                    validation_results.append(f"✅ Timezone valid: {scheduler_timezone}")
                except pytz.exceptions.UnknownTimeZoneError:
                    validation_results.append(f"❌ Unknown timezone: {scheduler_timezone}")
                    has_errors = True
            else:
                validation_results.append("⚠️ pytz not available")

        status = "error" if has_errors else "success"
        message = "\n".join(validation_results)
        message += "\n\n⚠️ Please fix the errors above." if has_errors else "\n\n✅ Settings valid. Ready to use!"
        return {"status": status, "message": message}

    # ------------------------------------------------------------------
    # View progress / cancel / view results
    # ------------------------------------------------------------------
    def view_progress_action(self, settings, logger):
        global _shared_load_progress
        if _shared_load_progress.get('status') == 'loading':
            lp = _shared_load_progress
            current, total = lp['current'], lp['total']
            percent = (current / total * 100) if total > 0 else 0
            if lp.get('start_time') and current > 0:
                elapsed = time.time() - lp['start_time']
                eta_seconds = (elapsed / current) * (total - current)
                eta_str = "ETA: <1 min" if eta_seconds < 60 else f"ETA: {eta_seconds/60:.0f} min"
            else:
                eta_str = "ETA: calculating..."
            return {"status": "success", "message": f"📥 Loading channels {current}/{total} - {percent:.0f}% complete | {eta_str}"}

        prog = _get_shared_progress()
        if prog['status'] != 'running':
            return {"status": "info", "message": "No operation is currently running.\n\nUse '📥 Load Group(s)' to load channels or '▶️ Start Stream Check' to begin."}

        current, total = prog['current'], prog['total']
        percent = (current / total * 100) if total > 0 else 0
        if prog.get('start_time') and current > 0:
            elapsed = time.time() - prog['start_time']
            eta_seconds = (elapsed / current) * (total - current)
            eta_str = "ETA: <1 min" if eta_seconds < 60 else f"ETA: {eta_seconds/60:.0f} min"
        else:
            eta_str = "ETA: calculating..."
        return {"status": "success", "message": f"🔄 Checking streams {current}/{total} - {percent:.0f}% complete | {eta_str}"}

    def cancel_check_action(self, settings, logger):
        prog = _get_shared_progress()
        if prog['status'] != 'running':
            return {"status": "info", "message": "No stream check is currently running."}
        self._stop_status_updates()
        current, total = prog['current'], prog['total']
        _set_shared_progress({'status': 'idle'})
        self._save_progress()
        logger.info(f"Stream check cancelled by user at {current}/{total}")
        return {"status": "success", "message": f"✅ Stream check cancelled.\n\nProcessed {current}/{total} streams.\n\nPartial results saved — use '📋 View Last Results'."}

    def view_results_action(self, settings, logger):
        prog = _get_shared_progress()

        # Primary: trust the in-process shared state
        if prog['status'] == 'running':
            return {"status": "info", "message": "A stream check is currently running.\n\nUse '📊 View Check Progress' to see status."}

        # Secondary safety net: if somehow status is still 'running' in a
        # freshly-bootstrapped instance but the file looks done, fall through.
        # (Shouldn't happen with shared state but belt-and-suspenders.)
        results = self._load_json_file(self.results_file)
        if results is None:
            return {"status": "info", "message": "No results available yet.\n\nUse '▶️ Start Stream Check' to begin."}

        alive = sum(1 for r in results if r.get('status') == 'Alive')
        formats: dict = {}
        for r in results:
            if r.get('status') == 'Alive':
                fmt = r.get('format', 'Unknown')
                formats[fmt] = formats.get(fmt, 0) + 1

        summary = [
            f"📊 Last Check Results ({len(results)} streams):",
            f"✅ Alive: {alive}",
            f"❌ Dead: {len(results) - alive}\n",
            "📺 Alive Stream Formats:",
        ]
        for fmt, count in sorted(formats.items()):
            if count > 0:
                summary.append(f"  • {fmt}: {count}")
        return {"status": "success", "message": "\n".join(summary)}

    # ------------------------------------------------------------------
    # Frontend refresh
    # ------------------------------------------------------------------
    def _trigger_frontend_refresh(self, settings, logger):
        try:
            send_websocket_update('updates', 'update', {"type": "plugin", "plugin": self.name, "message": "Channels updated"})
            logger.info("Frontend refresh triggered via WebSocket")
            return True
        except Exception as e:
            logger.warning(f"Could not trigger frontend refresh: {e}")
        return False

    # ------------------------------------------------------------------
    # ORM helpers
    # ------------------------------------------------------------------
    def _get_all_groups(self, logger):
        return list(ChannelGroup.objects.all().values('id', 'name'))

    def _get_all_channels(self, logger, group_ids=None):
        qs = Channel.objects.select_related('channel_group').all()
        if group_ids:
            qs = qs.filter(channel_group_id__in=group_ids)
        return list(qs.values('id', 'name', 'channel_number', 'channel_group_id', 'uuid'))

    def _get_channel_streams_bulk(self, channel_ids, logger, check_alternative=True):
        qs = ChannelStream.objects.filter(channel_id__in=channel_ids).select_related('stream').order_by('channel_id', 'order')
        if not check_alternative:
            qs = qs.filter(order=0)
        streams_by_channel = defaultdict(list)
        for cs in qs:
            streams_by_channel[cs.channel_id].append({
                'id': cs.stream.id,
                'name': cs.stream.name,
                'url': cs.stream.url,
                'channelstream': {'order': cs.order}
            })
        return streams_by_channel

    def _bulk_update_channels(self, updates, fields, logger):
        if not updates:
            return 0
        channel_ids = [u['id'] for u in updates]
        channels = {ch.id: ch for ch in Channel.objects.filter(id__in=channel_ids)}
        to_update = []
        for u in updates:
            ch = channels.get(u['id'])
            if ch:
                for field in fields:
                    if field in u:
                        setattr(ch, field, u[field])
                to_update.append(ch)
        if to_update:
            with transaction.atomic():
                Channel.objects.bulk_update(to_update, fields)
            logger.info(f"Bulk updated {len(to_update)} channels ({', '.join(fields)})")
        return len(to_update)

    def _get_or_create_group(self, name, logger):
        group, created = ChannelGroup.objects.get_or_create(name=name)
        if created:
            logger.info(f"Created new group '{name}' (ID: {group.id})")
        return group

    # ------------------------------------------------------------------
    # Load groups
    # ------------------------------------------------------------------
    def load_groups_action(self, settings, logger):
        try:
            group_names_str = settings.get("group_names", "").strip()
            all_groups = self._get_all_groups(logger)
            group_name_to_id = {g['name']: g['id'] for g in all_groups}
            if not group_names_str:
                logger.warning(f"⚠️ No groups specified — loading ALL {len(group_name_to_id)} groups")
                target_group_names = set(group_name_to_id.keys())
                target_group_ids = set(group_name_to_id.values())
                if not target_group_ids:
                    return {"status": "error", "message": "No groups found in Dispatcharr."}
            else:
                input_names = {n.strip() for n in group_names_str.split(',') if n.strip()}
                valid_names = {n for n in input_names if n in group_name_to_id}
                invalid_names = input_names - valid_names
                target_group_ids = {group_name_to_id[n] for n in valid_names}
                target_group_names = valid_names
                if invalid_names:
                    logger.warning(f"⚠️ Groups not found: {', '.join(invalid_names)}")
                if not target_group_ids:
                    return {"status": "error", "message": f"None of the specified groups found: {', '.join(invalid_names)}"}

            channels_in_groups = self._get_all_channels(logger, group_ids=target_group_ids)
            return self._load_groups_sync(channels_in_groups, settings, logger, group_names_str, target_group_names)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _load_groups_sync(self, channels_in_groups, settings, logger, group_names_str, target_group_names):
        check_alternative = settings.get("check_alternative_streams", True)
        channel_ids = [ch['id'] for ch in channels_in_groups]
        streams_by_channel = self._get_channel_streams_bulk(channel_ids, logger, check_alternative=check_alternative)
        loaded_channels = []
        for channel in channels_in_groups:
            channel_streams = streams_by_channel.get(channel['id'], [])
            loaded_channels.append({**channel, "streams": channel_streams})
        self._save_json_file(self.loaded_channels_file, loaded_channels)
        return self._build_load_success_message(loaded_channels, settings, group_names_str, target_group_names)

    def _build_load_success_message(self, loaded_channels, settings, group_names_str, target_group_names):
        total_streams = sum(len(c.get('streams', [])) for c in loaded_channels)
        group_msg = "all groups" if not group_names_str else f"group(s): {', '.join(target_group_names)}"
        parallel_enabled = settings.get("enable_parallel_checking", False)
        parallel_workers = settings.get("parallel_workers", 2)
        check_alternative = settings.get("check_alternative_streams", True)
        if parallel_enabled:
            estimated_seconds = (total_streams / parallel_workers) * 10
            mode_info = f"parallel mode with {parallel_workers} workers"
        else:
            estimated_seconds = total_streams * 10
            mode_info = "sequential mode"
        estimated_minutes = int(estimated_seconds / 60)
        stream_type_msg = "streams (including alternatives)" if check_alternative else "streams (primary only)"
        message = f"Successfully loaded {len(loaded_channels)} channels with {total_streams} {stream_type_msg} from {group_msg}."
        if total_streams > 0:
            message += f"\n\nNext, click '▶️ Start Stream Check'\nEstimated time: ~{estimated_minutes} minutes ({mode_info})"
            if not parallel_enabled and total_streams > 50:
                message += "\n\nTip: Enable 'Parallel Stream Checking' to speed up processing!"
        return {"status": "success", "message": message}

    # ------------------------------------------------------------------
    # Check streams
    # ------------------------------------------------------------------
    def check_streams_action(self, settings, logger, context=None):
        with _shared_check_lock:
            prog = _get_shared_progress()
            if prog['status'] == 'running':
                current, total = prog['current'], prog['total']
                percent = (current / total * 100) if total > 0 else 0
                return {"status": "info", "message": f"A stream check is already running ({percent:.0f}% complete).\n\nUse '📊 View Check Progress' to monitor."}

            loaded_channels = self._load_json_file(self.loaded_channels_file)
            if loaded_channels is None:
                return {"status": "error", "message": "No channels loaded (or data corrupted). Please run '📥 Load Group(s)' first."}

            all_streams = [
                {"channel_id": ch['id'], "channel_name": ch['name'], "stream_url": s['url'], "stream_id": s['id']}
                for ch in loaded_channels for s in ch.get('streams', []) if s.get('url')
            ]
            if not all_streams:
                return {"status": "error", "message": "The loaded groups contain no streams to check."}

            _set_shared_progress({"current": 0, "total": len(all_streams), "status": "running", "start_time": time.time()})
            self._save_progress()
            logger.info(f"Starting check for {len(all_streams)} streams...")
            if context:
                self._start_status_updates(context)

        parallel_enabled = settings.get("enable_parallel_checking", False)
        parallel_workers = settings.get("parallel_workers", 2)
        if parallel_enabled:
            estimated_total_time = int((len(all_streams) / parallel_workers) * 10 / 60)
            mode_info = f"parallel mode with {parallel_workers} workers"
        else:
            estimated_total_time = int(len(all_streams) * 10 / 60)
            mode_info = "sequential mode"

        processing_thread = threading.Thread(
            target=self._process_streams_background,
            args=(all_streams, settings, logger),
            daemon=True
        )
        processing_thread.start()

        return {"status": "success", "message": f"✅ Stream checking started for {len(all_streams)} streams\nEstimated time: ~{estimated_total_time} minutes ({mode_info})\n\nUse '📊 View Check Progress' to monitor."}

    def _process_streams_background(self, all_streams, settings, logger):
        if settings.get("enable_parallel_checking", False):
            self._process_streams_parallel(all_streams, settings, logger)
        else:
            self._process_streams_sequential(all_streams, settings, logger)

    def _finalize_check(self, results, settings, logger, mode_info=""):
        """Common teardown for both sequential and parallel processing."""
        global _shared_completion_message
        # --- CRITICAL: set idle FIRST, save SECOND ---
        _set_shared_progress({'status': 'idle', 'end_time': time.time()})
        self._save_progress()
        self._stop_status_updates()
        self._save_json_file(self.results_file, results, indent=2)
        self._trigger_frontend_refresh(settings, logger)
        msg = f"Stream checking completed. Processed {len(results)} streams"
        if mode_info:
            msg += f" ({mode_info})"
        msg += "."
        _shared_completion_message = msg
        logger.info(msg)

    def _process_streams_sequential(self, all_streams, settings, logger):
        global _shared_stop_status_updates
        results = []
        timeout = settings.get("timeout", 10)
        retries = settings.get("dead_connection_retries", 3)
        retry_queue = []
        streams_since_retry = 0
        channel_map = {}
        loaded_channels = self._load_json_file(self.loaded_channels_file)
        if loaded_channels:
            channel_map = {ch.get('id'): ch for ch in loaded_channels}
        retryable_errors = ['Timeout', 'Connection Refused', 'Network Unreachable', 'Stream Unreachable', 'Server Error']

        try:
            for i, stream_data in enumerate(all_streams):
                if _shared_stop_status_updates:
                    break
                _set_shared_progress({"current": i + 1})
                self._save_progress()

                result = self.check_stream(stream_data, timeout, 0, logger, skip_retries=True, settings=settings, retry_attempt=0)
                if result.get('dispatcharr_metadata'):
                    ch_data = channel_map.get(stream_data.get('channel_id'))
                    if ch_data:
                        result['metadata_updated'] = self._update_dispatcharr_metadata(ch_data, stream_data.get('stream_id'), result['dispatcharr_metadata'], logger)

                if result.get('error_type') in retryable_errors and retries > 0:
                    retry_queue.append({**stream_data, "retry_count": 0})

                results.append({**stream_data, **result})
                streams_since_retry += 1

                if streams_since_retry >= 4 and retry_queue:
                    retry_stream = retry_queue.pop(0)
                    retry_stream["retry_count"] += 1
                    if retry_stream["retry_count"] <= retries:
                        retry_result = self.check_stream(retry_stream, timeout, 0, logger, skip_retries=True, settings=settings, retry_attempt=retry_stream["retry_count"])
                        if retry_result.get('dispatcharr_metadata'):
                            ch_data = channel_map.get(retry_stream.get('channel_id'))
                            if ch_data:
                                retry_result['metadata_updated'] = self._update_dispatcharr_metadata(ch_data, retry_stream.get('stream_id'), retry_result['dispatcharr_metadata'], logger)
                        for j, er in enumerate(results):
                            if er.get('channel_id') == retry_stream.get('channel_id') and er.get('stream_id') == retry_stream.get('stream_id'):
                                results[j] = {**retry_stream, **retry_result}
                                break
                        if retry_result.get('error_type') in retryable_errors and retry_stream["retry_count"] < retries:
                            retry_queue.append(retry_stream)
                    streams_since_retry = 0
                time.sleep(3)

            while retry_queue:
                retry_stream = retry_queue.pop(0)
                if retry_stream["retry_count"] < retries:
                    retry_stream["retry_count"] += 1
                    retry_result = self.check_stream(retry_stream, timeout, 0, logger, skip_retries=True, settings=settings, retry_attempt=retry_stream["retry_count"])
                    if retry_result.get('dispatcharr_metadata'):
                        ch_data = channel_map.get(retry_stream.get('channel_id'))
                        if ch_data:
                            retry_result['metadata_updated'] = self._update_dispatcharr_metadata(ch_data, retry_stream.get('stream_id'), retry_result['dispatcharr_metadata'], logger)
                    for j, er in enumerate(results):
                        if er.get('channel_id') == retry_stream.get('channel_id') and er.get('stream_id') == retry_stream.get('stream_id'):
                            results[j] = {**retry_stream, **retry_result}
                            break
        except Exception as e:
            logger.error(f"Background sequential processing error: {e}")
        finally:
            self._finalize_check(results, settings, logger)

    def _process_streams_parallel(self, all_streams, settings, logger):
        global _shared_stop_status_updates
        results = []
        timeout = settings.get("timeout", 10)
        retries = settings.get("dead_connection_retries", 3)
        workers = settings.get("parallel_workers", 2)
        results_lock = threading.Lock()
        results_dict = {}
        channel_map = {}
        loaded_channels = self._load_json_file(self.loaded_channels_file)
        if loaded_channels:
            channel_map = {ch.get('id'): ch for ch in loaded_channels}
        retryable_errors = ['Timeout', 'Connection Refused', 'Network Unreachable', 'Stream Unreachable', 'Server Error']

        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_index = {
                    executor.submit(self.check_stream, stream_data, timeout, 0, logger, skip_retries=True, settings=settings, retry_attempt=0): i
                    for i, stream_data in enumerate(all_streams)
                }
                for future in as_completed(future_to_index):
                    if _shared_stop_status_updates:
                        executor.shutdown(wait=False)
                        break
                    index = future_to_index[future]
                    stream_data = all_streams[index]
                    try:
                        result = future.result()
                        if result.get('dispatcharr_metadata'):
                            ch_data = channel_map.get(stream_data.get('channel_id'))
                            if ch_data:
                                result['metadata_updated'] = self._update_dispatcharr_metadata(ch_data, stream_data.get('stream_id'), result['dispatcharr_metadata'], logger)
                            else:
                                result['metadata_updated'] = False
                        with results_lock:
                            results_dict[index] = {**stream_data, **result}
                            _set_shared_progress({"current": len(results_dict)})
                            self._save_progress()
                    except Exception as e:
                        logger.error(f"Error checking '{stream_data.get('channel_name')}': {e}")
                        with results_lock:
                            results_dict[index] = {**stream_data, 'status': 'Dead', 'error': str(e), 'error_type': 'Other', 'format': 'N/A', 'framerate_num': 0, 'ffprobe_data': {}}
                            _set_shared_progress({"current": len(results_dict)})
                            self._save_progress()

            results = [results_dict[i] for i in range(len(all_streams)) if i in results_dict]

            if retries > 0:
                retry_streams = [(i, r) for i, r in enumerate(results) if r.get('error_type') in retryable_errors]
                for retry_pass in range(retries):
                    if not retry_streams:
                        break
                    with ThreadPoolExecutor(max_workers=workers) as executor:
                        fmap = {
                            executor.submit(self.check_stream, {k: v for k, v in r.items() if k in ['channel_id', 'channel_name', 'stream_url', 'stream_id']}, timeout, 0, logger, skip_retries=True, settings=settings, retry_attempt=retry_pass + 1): ri
                            for ri, r in retry_streams
                        }
                        for future in as_completed(fmap):
                            ri = fmap[future]
                            try:
                                rr = future.result()
                                if rr.get('dispatcharr_metadata'):
                                    ch_data = channel_map.get(results[ri].get('channel_id'))
                                    if ch_data:
                                        rr['metadata_updated'] = self._update_dispatcharr_metadata(ch_data, results[ri].get('stream_id'), rr['dispatcharr_metadata'], logger)
                                results[ri] = {**results[ri], **rr}
                            except Exception as e:
                                logger.error(f"Error during retry: {e}")
                    retry_streams = [(i, r) for i, r in enumerate(results) if r.get('error_type') in retryable_errors]

        except Exception as e:
            logger.error(f"Background parallel processing error: {e}")
        finally:
            self._finalize_check(results, settings, logger, mode_info=f"parallel, {workers} workers")

    # ------------------------------------------------------------------
    # Channel mutation actions
    # ------------------------------------------------------------------
    def rename_channels_action(self, settings, logger):
        rename_format = settings.get("dead_rename_format", "{name} [DEAD]").strip()
        if not rename_format or "{name}" not in rename_format:
            return {"status": "error", "message": "Dead Channel Rename Format must contain {name} placeholder."}
        results = self._load_json_file(self.results_file)
        if results is None:
            return {"status": "error", "message": "No check results found. Please run 'Check Streams' first."}
        dead = {r['channel_id']: r['channel_name'] for r in results if r['status'] == 'Dead'}
        if not dead:
            return {"status": "success", "message": "No dead channels found."}
        payload = [{'id': cid, 'name': rename_format.replace('{name}', name)} for cid, name in dead.items() if rename_format.replace('{name}', name) != name]
        if not payload:
            return {"status": "success", "message": "No channels needed renaming."}
        try:
            count = self._bulk_update_channels(payload, ['name'], logger)
            self._trigger_frontend_refresh(settings, logger)
            return {"status": "success", "message": f"Successfully renamed {count} dead channels."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def move_dead_channels_action(self, settings, logger):
        group_name = settings.get("move_to_group_name", "Graveyard").strip()
        if not group_name:
            return {"status": "error", "message": "Please configure a destination group name."}
        results = self._load_json_file(self.results_file)
        if results is None:
            return {"status": "error", "message": "No check results found. Please run 'Check Streams' first."}
        dead_ids = {r['channel_id'] for r in results if r['status'] == 'Dead'}
        if not dead_ids:
            return {"status": "success", "message": "No dead channels found."}
        try:
            dest_group = self._get_or_create_group(group_name, logger)
            payload = [{'id': cid, 'channel_group_id': dest_group.id} for cid in dead_ids]
            count = self._bulk_update_channels(payload, ['channel_group_id'], logger)
            self._trigger_frontend_refresh(settings, logger)
            return {"status": "success", "message": f"Moved {count} dead channels to '{group_name}'."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def rename_low_framerate_channels_action(self, settings, logger):
        rename_format = settings.get("low_framerate_rename_format", "{name} [Slow]").strip()
        if not rename_format or "{name}" not in rename_format:
            return {"status": "error", "message": "Low Framerate Rename Format must contain {name} placeholder."}
        results = self._load_json_file(self.results_file)
        if results is None:
            return {"status": "error", "message": "No check results found. Please run 'Check Streams' first."}
        low_fps = {r['channel_id']: r['channel_name'] for r in results if 0 < r.get('framerate_num', 0) < 30}
        if not low_fps:
            return {"status": "success", "message": "No low framerate channels found."}
        payload = [{'id': cid, 'name': rename_format.replace('{name}', name)} for cid, name in low_fps.items() if rename_format.replace('{name}', name) != name]
        if not payload:
            return {"status": "success", "message": "No channels needed renaming."}
        try:
            count = self._bulk_update_channels(payload, ['name'], logger)
            self._trigger_frontend_refresh(settings, logger)
            return {"status": "success", "message": f"Renamed {count} low framerate channels."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def move_low_framerate_channels_action(self, settings, logger):
        group_name = settings.get("move_low_framerate_group", "Slow").strip()
        if not group_name:
            return {"status": "error", "message": "Please configure a destination group name."}
        results = self._load_json_file(self.results_file)
        if results is None:
            return {"status": "error", "message": "No check results found. Please run 'Check Streams' first."}
        low_fps_ids = {r['channel_id'] for r in results if 0 < r.get('framerate_num', 0) < 30}
        if not low_fps_ids:
            return {"status": "success", "message": "No low framerate channels found."}
        try:
            dest_group = self._get_or_create_group(group_name, logger)
            payload = [{'id': cid, 'channel_group_id': dest_group.id} for cid in low_fps_ids]
            count = self._bulk_update_channels(payload, ['channel_group_id'], logger)
            self._trigger_frontend_refresh(settings, logger)
            return {"status": "success", "message": f"Moved {count} low framerate channels to '{group_name}'."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def add_video_format_suffix_action(self, settings, logger):
        suffixes_str = settings.get("video_format_suffixes", "UHD, FHD, HD, SD, Unknown").strip().lower()
        if not suffixes_str:
            return {"status": "error", "message": "Please specify video formats to suffix."}
        suffixes = {s.strip() for s in suffixes_str.split(',')}
        results = self._load_json_file(self.results_file)
        if results is None:
            return {"status": "error", "message": "No check results found. Please run 'Check Streams' first."}
        channel_formats = {r['channel_id']: r.get('format', 'Unknown') for r in results if r['status'] == 'Alive'}
        if not channel_formats:
            return {"status": "success", "message": "No alive channels found."}
        try:
            all_channels = self._get_all_channels(logger)
            id_to_name = {c['id']: c['name'] for c in all_channels}
            payload = []
            skip_not_in, skip_has, skip_missing = 0, 0, 0
            for cid, fmt in channel_formats.items():
                if fmt.lower() not in suffixes:
                    skip_not_in += 1
                    continue
                current_name = id_to_name.get(cid)
                if not current_name:
                    skip_missing += 1
                    continue
                suffix = f" [{fmt.upper()}]"
                if current_name.endswith(suffix):
                    skip_has += 1
                else:
                    payload.append({'id': cid, 'name': current_name + suffix})
            if not payload:
                parts = []
                if skip_has:
                    parts.append(f"{skip_has} already have suffix")
                if skip_not_in:
                    parts.append(f"{skip_not_in} format not in list")
                if skip_missing:
                    parts.append(f"{skip_missing} not found in DB")
                return {"status": "success", "message": f"No channels needed updating.\n\nReason: {' • '.join(parts) or 'All up to date'}"}
            count = self._bulk_update_channels(payload, ['name'], logger)
            self._trigger_frontend_refresh(settings, logger)
            return {"status": "success", "message": f"Added format suffixes to {count} channels."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ------------------------------------------------------------------
    # View table / export
    # ------------------------------------------------------------------
    def view_table_action(self, settings, logger):
        results = self._load_json_file(self.results_file)
        if results is None:
            return {"status": "error", "message": "No results available."}
        lines = ["=" * 120, f"{'Channel Name':<35} {'Status':<8} {'Format':<8} {'FPS':<8} {'Error Type':<20} {'Error Details':<35}", "=" * 120]
        for r in results:
            fps = r.get('framerate_num', 0)
            fps_str = f"{fps:.1f}" if fps > 0 else "N/A"
            lines.append(f"{r.get('channel_name','N/A')[:34]:<35} {r.get('status','N/A'):<8} {r.get('format','N/A'):<8} {fps_str:<8} {r.get('error_type','N/A'):<20} {(r.get('error','') or '')[:34]:<35}")
        lines.append("=" * 120)
        return {"status": "success", "message": "\n".join(lines)}

    def _generate_csv_header_comments(self, settings, results):
        lines = ["# IPTV Checker Plugin - Export Results", f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", f"# Plugin Version: {self.version}", "#"]
        prog = _get_shared_progress()
        if prog.get('start_time') and prog.get('end_time'):
            start_str = datetime.fromtimestamp(prog['start_time']).strftime('%Y-%m-%d %H:%M:%S')
            end_str = datetime.fromtimestamp(prog['end_time']).strftime('%Y-%m-%d %H:%M:%S')
            dur = prog['end_time'] - prog['start_time']
            h, m, s = int(dur // 3600), int((dur % 3600) // 60), int(dur % 60)
            lines += ["# Check Timing:", f"#   Start Time: {start_str}", f"#   End Time: {end_str}", f"#   Duration: {h}h {m}m {s}s" if h else (f"#   Duration: {m}m {s}s" if m else f"#   Duration: {s}s"), "#"]
        lines += ["# Plugin Settings:", f"#   Group(s) Checked: {settings.get('group_names', 'All groups')}", f"#   Connection Timeout: {settings.get('timeout', 10)}s", f"#   Probe Timeout: {settings.get('probe_timeout', 20)}s", f"#   Retries: {settings.get('dead_connection_retries', 3)}", f"#   Parallel: {settings.get('enable_parallel_checking', False)} ({settings.get('parallel_workers', 2)} workers)", "#"]
        total = len(results)
        alive = sum(1 for r in results if r.get('status') == 'Alive')
        dead = total - alive
        lines += ["# Statistics:", f"#   Total: {total}", f"#   Alive: {alive} ({alive/total*100:.1f}%)" if total else "#   Alive: 0", f"#   Dead: {dead} ({dead/total*100:.1f}%)" if total else "#   Dead: 0", "#", "# " + "=" * 80, "#"]
        return lines

    def export_results_action(self, settings, logger):
        results = self._load_json_file(self.results_file)
        if results is None:
            return {"status": "error", "message": "No results to export."}
        for result in results:
            if result.get('framerate_num', 0) > 0:
                result['framerate_num'] = round(result['framerate_num'])
            if 'ffprobe_data' in result and isinstance(result['ffprobe_data'], dict):
                for k, v in result.pop('ffprobe_data').items():
                    result[f'ffprobe_{k}'] = v
        base_fields = ['channel_id', 'channel_name', 'stream_id', 'status', 'format', 'framerate_num', 'error_type', 'error', 'retry_count', 'connection_timeout_seconds', 'probe_timeout_seconds', 'ffprobe_monitoring_seconds']
        extra_fields = sorted({k for r in results for k in r if k.startswith('ffprobe_')})
        fieldnames = base_fields + extra_fields
        filepath = f"/data/exports/iptv_checker_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        os.makedirs("/data/exports", exist_ok=True)
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            for line in self._generate_csv_header_comments(settings, results):
                f.write(line + '\n')
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(results)
        return {"status": "success", "message": f"Results exported to {filepath}"}

    def clear_csv_exports_action(self, settings, logger):
        exports_dir = "/data/exports"
        if not os.path.exists(exports_dir):
            return {"status": "info", "message": "No exports directory found."}
        csv_files = [f for f in os.listdir(exports_dir) if f.startswith('iptv_checker_results_') and f.endswith('.csv')]
        if not csv_files:
            return {"status": "info", "message": "No CSV export files found."}
        deleted = 0
        for csv_file in csv_files:
            try:
                os.remove(os.path.join(exports_dir, csv_file))
                deleted += 1
            except Exception as e:
                logger.error(f"Failed to delete {csv_file}: {e}")
        if deleted == 0:
            return {"status": "error", "message": "Failed to delete any CSV files."}
        if deleted < len(csv_files):
            return {"status": "success", "message": f"⚠️ Deleted {deleted}/{len(csv_files)} CSV files. Check logs for errors."}
        return {"status": "success", "message": f"✅ Deleted {deleted} CSV file(s) from /data/exports/."}

    # ------------------------------------------------------------------
    # Schedule management
    # ------------------------------------------------------------------
    def update_schedule_action(self, settings, logger):
        try:
            scheduled_times_str = settings.get("scheduled_times", "").strip()
            if not scheduled_times_str:
                self._stop_background_scheduler()
                return {"status": "success", "message": "✅ Schedule cleared. Scheduler stopped."}
            scheduled_times = self._parse_scheduled_times(scheduled_times_str)
            if not scheduled_times:
                return {"status": "error", "message": f"❌ Invalid cron format: '{scheduled_times_str}'"}
            scheduler_timezone = settings.get("scheduler_timezone", SchedulerConfig.DEFAULT_TIMEZONE)
            if PYTZ_AVAILABLE:
                try:
                    pytz.timezone(scheduler_timezone)
                except pytz.exceptions.UnknownTimeZoneError:
                    return {"status": "error", "message": f"❌ Unknown timezone: {scheduler_timezone}"}
            else:
                return {"status": "error", "message": "❌ pytz not installed. Cannot use scheduler."}
            self._start_background_scheduler(settings)
            return {"status": "success", "message": f"✅ Schedule updated!\n\nCron: {', '.join(scheduled_times)}\nTimezone: {scheduler_timezone}\nStatus: Running ✓"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to update schedule: {str(e)}"}

    def cleanup_orphaned_tasks_action(self, settings, logger):
        try:
            from django_celery_beat.models import PeriodicTask
            from django.db.models import Q
        except ImportError:
            return {"status": "error", "message": "❌ django-celery-beat not available."}
        try:
            query = Q(name__icontains='iptv_checker') | Q(task__icontains='iptv_checker') | Q(name__icontains='IPTV Checker') | Q(task__icontains='IPTV Checker')
            orphaned = PeriodicTask.objects.filter(query)
            count = orphaned.count()
            if count == 0:
                return {"status": "success", "message": "✅ No orphaned tasks found."}
            task_names = list(orphaned.values_list('name', flat=True))
            deleted_count, _ = orphaned.delete()
            return {"status": "success", "message": f"✅ Cleaned up {deleted_count} task(s):\n" + "\n".join(f"  • {n}" for n in task_names)}
        except Exception as e:
            return {"status": "error", "message": f"❌ Failed: {str(e)}"}

    def check_scheduler_status_action(self, settings, logger):
        global _bg_scheduler_thread, _scheduler_pending_run
        try:
            lines = ["🔍 Scheduler Status Report", "=" * 60, ""]
            if _bg_scheduler_thread is None:
                lines += ["📊 Thread Status:", "  • Thread: Not created", "  • Status: ❌ Not Running", ""]
            elif _bg_scheduler_thread.is_alive():
                lines += ["📊 Thread Status:", f"  • Thread: Alive (ID: {_bg_scheduler_thread.ident})", "  • Status: ✅ Running", ""]
            else:
                lines += ["📊 Thread Status:", "  • Thread: Stopped", "  • Status: ⚠️ Stopped", ""]

            scheduled_times_str = settings.get("scheduled_times", "").strip()
            scheduler_timezone = settings.get("scheduler_timezone", SchedulerConfig.DEFAULT_TIMEZONE)
            lines.append("⚙️ Configuration:")
            if scheduled_times_str:
                scheduled_times = self._parse_scheduled_times(scheduled_times_str)
                lines.append(f"  • Cron: {', '.join(scheduled_times)}")
            else:
                lines.append("  • Cron: Not configured")
            lines.append(f"  • Timezone: {scheduler_timezone}")
            if PYTZ_AVAILABLE:
                try:
                    tz = pytz.timezone(scheduler_timezone)
                    now = datetime.now(tz)
                    lines.append(f"  • Current Time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                except Exception:
                    lines.append("  • Current Time: Invalid timezone")
            lines.append(f"  • pytz: {'Available ✓' if PYTZ_AVAILABLE else 'Not Available ✗'}")
            lines.append(f"  • Queued Run: {'Yes' if _scheduler_pending_run else 'No'}")
            lines.append("")

            prog = _get_shared_progress()
            lines.append("🔄 Current Check Status:")
            lines.append(f"  • Status: {prog.get('status', 'idle').title()}")
            if prog.get('status') == 'running':
                current, total = prog.get('current', 0), prog.get('total', 0)
                percent = (current / total * 100) if total > 0 else 0
                lines.append(f"  • Progress: {current}/{total} ({percent:.1f}%)")
            lines.append("")
            lines.append("💡 Recommendations:")
            if not scheduled_times_str:
                lines.append("  ⚠️ Configure cron expressions to enable scheduling")
            elif not PYTZ_AVAILABLE:
                lines.append("  ⚠️ Install pytz for timezone support")
            elif not _bg_scheduler_thread or not _bg_scheduler_thread.is_alive():
                lines.append("  ⚠️ Scheduler not running — try '📅 Update Schedule'")
            else:
                lines.append("  ✅ Scheduler configured and running")
            return {"status": "success", "message": "\n".join(lines)}
        except Exception as e:
            return {"status": "error", "message": f"❌ Failed: {str(e)}"}

    # ------------------------------------------------------------------
    # Stream checking
    # ------------------------------------------------------------------
    def _get_stream_format(self, resolution_str):
        if 'x' not in resolution_str:
            return "Unknown"
        try:
            width = int(resolution_str.split('x')[0])
            if width >= 3800:
                return "UHD"
            if width >= 1900:
                return "FHD"
            if width >= 1200:
                return "HD"
            if width > 0:
                return "SD"
            return "Unknown"
        except Exception:
            return "Unknown"

    def parse_framerate(self, framerate_str):
        try:
            if '/' in framerate_str:
                num, den = map(float, framerate_str.split('/'))
                return num / den if den != 0 else 0
            return float(framerate_str)
        except (ValueError, ZeroDivisionError):
            return 0

    def _mask_url_in_error(self, error_message, stream_url, stream_id):
        if not error_message or not stream_url:
            return error_message
        masked = error_message.replace(stream_url, f"[Stream ID: {stream_id}]")
        try:
            import urllib.parse
            encoded = urllib.parse.quote(stream_url, safe='')
            if encoded in masked:
                masked = masked.replace(encoded, f"[Stream ID: {stream_id}]")
        except Exception:
            pass
        return masked

    def check_stream(self, stream_data, timeout, retries, logger, skip_retries=False, settings=None, retry_attempt=0):
        url = stream_data.get('stream_url')
        channel_name = stream_data.get('channel_name')
        stream_id = stream_data.get('stream_id', 'unknown')
        last_error = "Unknown error"
        last_error_type = "Other"
        probe_timeout = settings.get('probe_timeout', 20) if settings else 20

        default_return = {
            'status': 'Dead', 'error': '', 'error_type': 'Other', 'format': 'N/A',
            'framerate_num': 0, 'ffprobe_data': {},
            'dispatcharr_metadata': {
                'video_codec': None, 'resolution': '0x0', 'width': 0, 'height': 0,
                'source_fps': None, 'pixel_format': None, 'video_bitrate': None,
                'audio_codec': None, 'sample_rate': None, 'audio_channels': None,
                'audio_bitrate': None, 'stream_type': None
            },
            'retry_count': retry_attempt, 'connection_timeout_seconds': timeout,
            'probe_timeout_seconds': probe_timeout, 'ffprobe_monitoring_seconds': 0
        }

        retry_info = f" (retry {retry_attempt})" if retry_attempt > 0 else ""
        logger.debug(f"Checking stream{retry_info}: '{channel_name}'")

        max_attempts = 1 if skip_retries else (retries + 1)
        ffprobe_flags_str = settings.get('ffprobe_flags', '-show_streams,-show_frames,-show_packets,-loglevel error') if settings else '-show_streams,-show_frames,-show_packets,-loglevel error'
        ffprobe_flags = [f.strip() for f in ffprobe_flags_str.split(',') if f.strip()]
        ffprobe_path = settings.get('ffprobe_path', '/usr/local/bin/ffprobe') if settings else '/usr/local/bin/ffprobe'

        cmd = [
            ffprobe_path,
            '-print_format', 'json',
            '-user_agent', 'VLC/3.0.21 LibVLC/3.0.21',
            '-timeout', str(timeout * 1000000),
            '-analyzeduration', str(probe_timeout * 1000000),
            '-probesize', '10000000'
        ]

        has_loglevel = any('loglevel' in f for f in ffprobe_flags)
        if has_loglevel:
            for f in ffprobe_flags:
                if 'loglevel' in f:
                    cmd.extend(f.split())
        else:
            cmd.extend(['-v', 'quiet'])

        for f in ffprobe_flags:
            if f.startswith('-show_'):
                cmd.append(f)

        if '-show_streams' not in cmd:
            cmd.append('-show_streams')

        analysis_duration = 0
        if any(f in cmd for f in ['-show_frames', '-show_packets']):
            analysis_duration = settings.get('ffprobe_analysis_duration', 5) if settings else 5
            cmd.extend(['-read_intervals', f'%+{analysis_duration}'])

        cmd.append(url)
        total_timeout = probe_timeout + analysis_duration + 5

        for attempt in range(max_attempts):
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=total_timeout)
                if result.returncode == 0:
                    probe_data = json.loads(result.stdout)
                    video_stream = next((s for s in probe_data.get('streams', []) if s['codec_type'] == 'video'), None)
                    audio_stream = next((s for s in probe_data.get('streams', []) if s['codec_type'] == 'audio'), None)

                    if video_stream:
                        width = video_stream.get('width', 0)
                        height = video_stream.get('height', 0)
                        resolution = f"{width}x{height}"
                        framerate_num = round(self.parse_framerate(video_stream.get('r_frame_rate', '0/1')), 1)
                        video_codec = video_stream.get('codec_name', 'unknown')
                        pixel_format = video_stream.get('pix_fmt', 'unknown')
                        video_bitrate = None
                        if video_stream.get('bit_rate'):
                            try:
                                video_bitrate = float(video_stream['bit_rate']) / 1000.0
                            except (ValueError, TypeError):
                                pass

                        audio_codec = sample_rate = audio_channels = audio_bitrate = None
                        if audio_stream:
                            audio_codec = audio_stream.get('codec_name', 'unknown')
                            try:
                                sample_rate = int(audio_stream['sample_rate']) if audio_stream.get('sample_rate') else None
                            except (ValueError, TypeError):
                                pass
                            ac = audio_stream.get('channel_layout') or audio_stream.get('channels')
                            if isinstance(ac, int):
                                ac = {1: 'mono', 2: 'stereo', 6: '5.1', 8: '7.1'}.get(ac, f'{ac}ch')
                            audio_channels = ac
                            if audio_stream.get('bit_rate'):
                                try:
                                    audio_bitrate = float(audio_stream['bit_rate']) / 1000.0
                                except (ValueError, TypeError):
                                    pass

                        stream_type = None
                        if probe_data.get('format'):
                            fmt_name = probe_data['format'].get('format_name', '')
                            if 'mpegts' in fmt_name:
                                stream_type = 'mpegts'
                            elif 'hls' in fmt_name or 'm3u8' in fmt_name:
                                stream_type = 'hls'
                            elif 'flv' in fmt_name:
                                stream_type = 'flv'
                            else:
                                stream_type = fmt_name.split(',')[0] if fmt_name else 'unknown'

                        ffprobe_extra = {}
                        if probe_data.get('frames'):
                            ffprobe_extra['frame_count'] = len(probe_data['frames'])
                        if probe_data.get('packets'):
                            pkts = probe_data['packets']
                            ffprobe_extra['packet_count'] = len(pkts)
                            if not video_bitrate:
                                total_size = sum(int(p.get('size', 0)) for p in pkts)
                                total_dur = sum(float(p.get('duration_time', 0)) for p in pkts)
                                if total_dur > 0:
                                    video_bitrate = (total_size * 8) / (total_dur * 1000)
                                    ffprobe_extra['calculated_bitrate_kbps'] = video_bitrate

                        stream_format = self._get_stream_format(resolution)
                        logger.info(f"✓ '{channel_name}' ALIVE - {stream_format} {resolution} {framerate_num:.1f}fps")
                        return {
                            'status': 'Alive', 'error': '', 'error_type': 'N/A',
                            'format': stream_format, 'framerate_num': framerate_num,
                            'ffprobe_data': ffprobe_extra,
                            'dispatcharr_metadata': {
                                'video_codec': video_codec, 'resolution': resolution,
                                'width': width, 'height': height, 'source_fps': framerate_num,
                                'pixel_format': pixel_format, 'video_bitrate': video_bitrate,
                                'audio_codec': audio_codec, 'sample_rate': sample_rate,
                                'audio_channels': audio_channels, 'audio_bitrate': audio_bitrate,
                                'stream_type': stream_type
                            },
                            'retry_count': retry_attempt, 'connection_timeout_seconds': timeout,
                            'probe_timeout_seconds': probe_timeout, 'ffprobe_monitoring_seconds': analysis_duration
                        }
                    else:
                        last_error = 'No video stream found'
                        last_error_type = 'No Video Stream'
                else:
                    error_output = result.stderr.strip() or 'Stream not accessible'
                    last_error = error_output
                    el = error_output.lower()
                    if 'timed out' in el or 'timeout' in el:
                        last_error_type = 'Timeout'
                    elif 'option not found' in el or 'unrecognized option' in el:
                        last_error_type = 'FFprobe Option Error'
                    elif '404' in error_output:
                        last_error_type = '404 Not Found'
                    elif '403' in error_output or 'forbidden' in el:
                        last_error_type = '403 Forbidden'
                    elif '500' in error_output or 'internal server error' in el:
                        last_error_type = 'Server Error'
                    elif 'connection refused' in el:
                        last_error_type = 'Connection Refused'
                    elif 'network unreachable' in el or 'no route to host' in el:
                        last_error_type = 'Network Unreachable'
                    elif 'invalid data found' in el or 'invalid argument' in el:
                        last_error_type = 'Invalid Stream'
                    elif 'protocol not supported' in el:
                        last_error_type = 'Unsupported Protocol'
                    elif result.returncode == 1:
                        last_error_type = 'Stream Unreachable'
                    else:
                        last_error_type = 'Other'
            except subprocess.TimeoutExpired:
                last_error = f'Connection timeout after {total_timeout}s'
                last_error_type = 'Timeout'
            except Exception as e:
                last_error = str(e)
                last_error_type = 'Other'

            if not skip_retries and attempt < max_attempts - 1:
                time.sleep(1)

        logger.info(f"✗ '{channel_name}' DEAD - {last_error_type}")
        default_return['error'] = self._mask_url_in_error(last_error, url, stream_id)
        default_return['error_type'] = last_error_type
        return default_return

    def _update_dispatcharr_metadata(self, channel_data, stream_id, metadata, logger):
        if not DISPATCHARR_INTEGRATION_AVAILABLE or not metadata:
            return False
        try:
            channel_uuid = channel_data.get('uuid')
            if not channel_uuid:
                return False
            all_none = all(v is None for v in metadata.values())
            if all_none:
                try:
                    from apps.proxy.ts_proxy.models import Stream as ProxyStream
                    stream = ProxyStream.objects.filter(id=stream_id).first()
                    if stream:
                        stream.stream_stats = {}
                        stream.save(update_fields=['stream_stats'])
                        return True
                    return False
                except Exception as e:
                    logger.error(f"Failed to clear stream_stats for {stream_id}: {e}")
                    return False
            clean_metadata = {k: v for k, v in metadata.items() if v is not None}
            if not clean_metadata:
                return False
            try:
                success = ChannelService._update_stream_stats_in_db(stream_id=stream_id, **clean_metadata)
                return bool(success)
            except Exception as e:
                logger.error(f"Failed to update DB metadata for stream {stream_id}: {e}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error updating metadata for stream {stream_id}: {e}")
            return False
