"""
Dispatcharr IPTV Checker Plugin
Checks stream status and analyzes stream quality
"""

import logging
import requests
import subprocess
import json
import os
import re
import csv
import time
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Setup logging using Dispatcharr's format with plugin name prefix
LOGGER = logging.getLogger("plugins.iptv_checker")
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[IPTV Checker] %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)

class Plugin:
    """Dispatcharr IPTV Checker Plugin"""
    
    # Explicitly set the plugin key
    key = "iptv_checker"
    name = "IPTV Checker"
    version = "0.3.0"
    description = "Check stream status and quality for channels in specified Dispatcharr groups."
    
    fields = [
        {
            "id": "dispatcharr_url",
            "label": "🌐 Dispatcharr URL",
            "type": "string",
            "default": "",
            "placeholder": "http://192.168.1.10:9191",
            "help_text": "URL of your Dispatcharr instance (from your browser's address bar). Example: http://127.0.0.1:9191",
        },
        {
            "id": "dispatcharr_username",
            "label": "👤 Dispatcharr Admin Username",
            "type": "string",
            "help_text": "Your admin username for the Dispatcharr UI. Required for WRITE operations.",
        },
        {
            "id": "dispatcharr_password",
            "label": "🔑 Dispatcharr Admin Password",
            "type": "string",
            "input_type": "password",
            "help_text": "Your admin password for the Dispatcharr UI. Required for WRITE operations.",
        },
        {
            "id": "group_names",
            "label": "📂 Group(s) to Check (comma-separated)",
            "type": "string",
            "default": "",
            "help_text": "The name of the Dispatcharr Channel Group(s) to check. Leave blank to check all groups.",
        },
        {
            "id": "timeout",
            "label": "⏱️ Connection Timeout (seconds)",
            "type": "number",
            "default": 10,
            "help_text": "Timeout for each stream connection attempt. Default: 10",
        },
        {
            "id": "dead_connection_retries",
            "label": "🔄 Dead Connection Retries",
            "type": "number",
            "default": 3,
            "help_text": "Number of times to retry checking a stream if it appears to be dead. Default: 3",
        },
        {
            "id": "dead_rename_format",
            "label": "💀 Dead Channel Rename Format",
            "type": "string",
            "default": "{name} [DEAD]",
            "placeholder": "[DEAD] {name}",
            "help_text": "Format for renaming dead channels. Use {name} as placeholder for the original channel name. Examples: '[DEAD] {name}', '{name} [DEAD]', '[X] {name} [DEAD]'",
        },
        {
            "id": "move_to_group_name",
            "label": "⚰️ Move Dead Channels to Group",
            "type": "string",
            "default": "Graveyard",
            "help_text": "Enter the name for the group to move dead channels into.",
        },
        {
            "id": "low_framerate_rename_format",
            "label": "🐌 Low Framerate Rename Format - Less than 30fps",
            "type": "string",
            "default": "{name} [Slow]",
            "placeholder": "[SLOW] {name}",
            "help_text": "Format for renaming low framerate channels. Use {name} as placeholder for the original channel name. Examples: '[SLOW] {name}', '{name} [Slow]'",
        },
        {
            "id": "move_low_framerate_group",
            "label": "📁 Move Low Framerate Channels to Group",
            "type": "string",
            "default": "Slow",
            "help_text": "Enter the name for the group to move low framerate channels into.",
        },
        {
            "id": "video_format_suffixes",
            "label": "🎬 Add Video Format Suffixes - [4k], [FHD], [HD], [SD], [Unknown]",
            "type": "string",
            "default": "4k, FHD, HD, SD, Unknown",
            "help_text": "A comma-separated list of formats to add as a suffix (e.g., [HD]) to channel names.",
        },
        {
            "id": "enable_parallel_checking",
            "label": "⚡ Enable Parallel Stream Checking",
            "type": "boolean",
            "default": False,
            "help_text": "Check multiple streams simultaneously for significantly faster processing. Recommended for large channel lists.",
        },
        {
            "id": "parallel_workers",
            "label": "👷 Number of Parallel Workers",
            "type": "number",
            "default": 2,
            "help_text": "Number of streams to check simultaneously when parallel checking is enabled. Default: 2. Higher values = faster but more resource-intensive.",
        }
    ]
    
    actions = [
        {
            "id": "validate_settings",
            "label": "✅ Validate Settings",
            "description": "Validate all plugin settings (API connection, credentials, groups, etc.).",
        },
        {
            "id": "load_groups",
            "label": "📥 Load Group(s)",
            "description": "Load channels from the specified Dispatcharr group(s) (or all groups if blank).",
        },
        {
            "id": "check_streams",
            "label": "▶️ Start Stream Check",
            "description": "Start checking stream status and quality for all loaded channels.",
        },
        {
            "id": "view_progress",
            "label": "📊 View Check Progress",
            "description": "View the current progress and ETA of the running stream check.",
        },
        {
            "id": "cancel_check",
            "label": "🛑 Cancel Stream Check",
            "description": "Cancel the currently running stream check.",
        },
        {
            "id": "view_results",
            "label": "📋 View Last Results",
            "description": "View summary of the last completed stream check.",
        },
        {
            "id": "rename_channels",
            "label": "✏️ Rename Dead Channels",
            "description": "Rename all channels marked as 'Dead' in the last check using the configured rename format.",
            "confirm": { "required": True, "title": "Rename Dead Channels?", "message": "This action is irreversible. Continue?" }
        },
        {
            "id": "move_dead_channels",
            "label": "⚰️ Move Dead Channels to Group",
            "description": "Moves all channels marked as 'Dead' in the last check to the specified group.",
            "confirm": { "required": True, "title": "Move Dead Channels?", "message": "This action is irreversible. Continue?" }
        },
        {
            "id": "rename_low_framerate_channels",
            "label": "🐌 Rename Low Framerate Channels",
            "description": "Rename channels with streams under 30fps using the configured rename format.",
            "confirm": { "required": True, "title": "Rename Low Framerate Channels?", "message": "This action is irreversible. Continue?" }
        },
        {
            "id": "move_low_framerate_channels",
            "label": "📁 Move Low Framerate Channels to Group",
            "description": "Moves channels with streams under 30fps to the specified group.",
            "confirm": { "required": True, "title": "Move Low Framerate Channels?", "message": "This action is irreversible. Continue?" }
        },
        {
            "id": "add_video_format_suffix",
            "label": "🎬 Add Video Format Suffix to Channels",
            "description": "Adds a format suffix like [HD] or [FHD] to alive channel names.",
            "confirm": { "required": True, "title": "Add Video Format Suffixes?", "message": "This will rename channels based on the last check. This action is irreversible. Continue?" }
        },
        {
            "id": "view_table",
            "label": "📊 View Results Table",
            "description": "Display detailed results in table format. (Copy/paste into text editor for better formatting."
        },
        {
            "id": "export_results",
            "label": "💾 Export Results to CSV",
            "description": "Export the last check results to a CSV file. Will be saved in Docker container: /data/exports/"
        },
        {
            "id": "clear_csv_exports",
            "label": "🗑️ Clear CSV Exports",
            "description": "Delete all CSV export files created by this plugin.",
            "confirm": { "required": True, "title": "Clear All CSV Exports?", "message": "This will delete all CSV files in /data/exports/. This action cannot be undone. Continue?" }
        }
    ]
    
    def __init__(self):
        self.results_file = "/data/iptv_checker_results.json"
        self.loaded_channels_file = "/data/iptv_checker_loaded_channels.json"
        self.progress_file = "/data/iptv_checker_progress.json"
        self.check_progress = self._load_progress()
        self.check_lock = threading.Lock()  # Lock to prevent duplicate checks
        self.status_thread = None
        self.stop_status_updates = False
        self.pending_status_message = None
        self.completion_message = None
        self.timeout_retry_queue = []  # Queue for streams that timed out and need retry
        self.cached_token = None  # Cached API token
        self.token_cache_time = None  # Time when token was cached
        self.token_cache_duration = 3600  # Cache token for 1 hour (3600 seconds)
        LOGGER.info(f"Plugin v{self.version} initialized")

    def _load_progress(self):
        """Load check progress from persistent storage"""
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                LOGGER.warning(f"Failed to load progress file: {e}")
        return {"current": 0, "total": 0, "status": "idle", "start_time": None}

    def _save_progress(self):
        """Save check progress to persistent storage"""
        try:
            with open(self.progress_file, 'w') as f:
                json.dump(self.check_progress, f)
        except Exception as e:
            LOGGER.error(f"Failed to save progress file: {e}")

    def run(self, action, params, context):
        """Main plugin entry point"""
        LOGGER.info(f"Run called with action: {action}")
        LOGGER.info(f"Plugin key from context: {context.get('plugin_key', 'unknown')}")  # Debug line
        
        try:
            settings = context.get("settings", {})
            logger = context.get("logger", LOGGER)
            
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
            }

            if action not in action_map:
                return {"status": "error", "message": f"Unknown action: {action}"}

            # Pass context to actions that need it
            if action in ["check_streams"]:
                return action_map[action](settings, logger, context)
            else:
                return action_map[action](settings, logger)
                
        except Exception as e:
            self.check_progress['status'] = 'idle'
            self._save_progress()
            self._stop_status_updates()
            LOGGER.error(f"Error in plugin run: {str(e)}")
            return {"status": "error", "message": str(e)}

    def get_status_update_action(self, settings, logger, context):
        """Return pending status update with ETA if available"""
        
        # Check if we have a completion message
        if self.completion_message:
            message = self.completion_message
            self.completion_message = None  # Clear after reading
            return {"status": "success", "message": message}
        
        if self.check_progress['status'] == 'running':
            current, total = self.check_progress['current'], self.check_progress['total']
            percent = (current / total * 100) if total > 0 else 0
            
            # Calculate ETA
            if self.check_progress.get('start_time') and current > 0:
                elapsed_seconds = time.time() - self.check_progress['start_time']
                avg_time_per_stream = elapsed_seconds / current
                remaining_streams = total - current
                eta_seconds = remaining_streams * avg_time_per_stream
                eta_minutes = eta_seconds / 60
                
                if eta_minutes < 1:
                    eta_str = f"ETA: <1 min"
                else:
                    eta_str = f"ETA: {eta_minutes:.0f} min"
            else:
                eta_str = "ETA: calculating..."
            
            message = f"Checking streams {current}/{total} - {percent:.0f}% complete | {eta_str}"
            return {"status": "success", "message": message}
        
        if self.pending_status_message:
            message = self.pending_status_message
            self.pending_status_message = None  # Clear after reading
            return {"status": "success", "message": message}
        
        return {"status": "info", "message": "No status update available"}

    def _start_status_updates(self, context):
        """Start background thread for status updates"""
        if self.status_thread and self.status_thread.is_alive():
            return
            
        self.stop_status_updates = False
        self.status_thread = threading.Thread(target=self._status_update_loop, args=(context,))
        self.status_thread.daemon = True
        self.status_thread.start()

    def _stop_status_updates(self):
        """Stop background status updates"""
        self.stop_status_updates = True
        if self.status_thread:
            self.status_thread.join(timeout=2)

    def _status_update_loop(self, context):
        """Background loop to generate status updates every minute"""
        while not self.stop_status_updates and self.check_progress['status'] == 'running':
            time.sleep(60)  # Wait 60 seconds

            if self.check_progress['status'] == 'running' and not self.stop_status_updates:
                current = self.check_progress['current']
                total = self.check_progress['total']
                percent = (current / total * 100) if total > 0 else 0

                # Store the status message for retrieval
                self.pending_status_message = f"Checking streams {current}/{total} - {percent:.0f}% complete"

                # Log for debugging
                logger = context.get("logger", LOGGER)
                logger.info(f"STATUS UPDATE READY: {self.pending_status_message}")

    def validate_settings_action(self, settings, logger):
        """Validate all plugin settings including API connection, credentials, and groups."""
        validation_results = []
        has_errors = False

        # Validate Dispatcharr URL
        dispatcharr_url = settings.get("dispatcharr_url", "").strip()
        if not dispatcharr_url:
            validation_results.append("❌ Dispatcharr URL is not configured")
            has_errors = True
        else:
            validation_results.append(f"✅ Dispatcharr URL configured: {dispatcharr_url}")

        # Validate credentials
        username = settings.get("dispatcharr_username", "").strip()
        password = settings.get("dispatcharr_password", "").strip()

        if not username:
            validation_results.append("❌ Admin Username is not configured")
            has_errors = True
        else:
            validation_results.append(f"✅ Admin Username configured: {username}")

        if not password:
            validation_results.append("❌ Admin Password is not configured")
            has_errors = True
        else:
            validation_results.append("✅ Admin Password is configured")

        # Test API connection if credentials are provided
        if dispatcharr_url and username and password:
            try:
                token, error = self._get_api_token(settings, logger)
                if error:
                    validation_results.append(f"❌ API Connection Failed: {error}")
                    has_errors = True
                else:
                    validation_results.append("✅ API Connection successful")

                    # Validate groups if specified
                    group_names_str = settings.get("group_names", "").strip()
                    if group_names_str:
                        try:
                            all_groups = self._get_api_data("/api/channels/groups/", token, settings)
                            group_name_to_id = {g['name']: g['id'] for g in all_groups if 'name' in g and 'id' in g}
                            input_names = {name.strip() for name in group_names_str.split(',') if name.strip()}
                            valid_names = {n for n in input_names if n in group_name_to_id}
                            invalid_names = input_names - valid_names

                            if valid_names:
                                validation_results.append(f"✅ Valid groups found: {', '.join(valid_names)}")
                            if invalid_names:
                                validation_results.append(f"⚠️ Invalid groups (not found): {', '.join(invalid_names)}")
                                has_errors = True
                        except Exception as e:
                            validation_results.append(f"❌ Failed to validate groups: {str(e)}")
                            has_errors = True
                    else:
                        validation_results.append("ℹ️ No specific groups configured (will check all groups)")
            except Exception as e:
                validation_results.append(f"❌ Validation error: {str(e)}")
                has_errors = True

        # Validate other settings
        timeout = settings.get("timeout", 10)
        if timeout <= 0:
            validation_results.append(f"⚠️ Connection Timeout should be greater than 0 (current: {timeout})")
            has_errors = True
        else:
            validation_results.append(f"✅ Connection Timeout: {timeout} seconds")

        parallel_workers = settings.get("parallel_workers", 2)
        if parallel_workers < 1:
            validation_results.append(f"⚠️ Parallel Workers should be at least 1 (current: {parallel_workers})")
            has_errors = True
        else:
            validation_results.append(f"✅ Parallel Workers: {parallel_workers}")

        # Return results
        status = "error" if has_errors else "success"
        message = "\n".join(validation_results)

        if has_errors:
            message += "\n\n⚠️ Please fix the errors above before using the plugin."
        else:
            message += "\n\n✅ All settings are valid! You can now use the plugin."

        return {"status": status, "message": message}

    def view_progress_action(self, settings, logger):
        """View the current progress of a running stream check."""
        if self.check_progress['status'] != 'running':
            return {"status": "info", "message": "No stream check is currently running.\n\nUse '▶️ Start Stream Check' to begin checking streams."}

        current, total = self.check_progress['current'], self.check_progress['total']
        percent = (current / total * 100) if total > 0 else 0

        # Calculate ETA
        if self.check_progress.get('start_time') and current > 0:
            elapsed_seconds = time.time() - self.check_progress['start_time']
            avg_time_per_stream = elapsed_seconds / current
            remaining_streams = total - current
            eta_seconds = remaining_streams * avg_time_per_stream
            eta_minutes = eta_seconds / 60

            if eta_minutes < 1:
                eta_str = f"ETA: <1 min"
            else:
                eta_str = f"ETA: {eta_minutes:.0f} min"
        else:
            eta_str = "ETA: calculating..."

        message = f"🔄 Checking streams {current}/{total} - {percent:.0f}% complete | {eta_str}"
        return {"status": "success", "message": message}

    def cancel_check_action(self, settings, logger):
        """Cancel the currently running stream check."""
        if self.check_progress['status'] != 'running':
            return {"status": "info", "message": "No stream check is currently running."}

        # Signal the background thread to stop
        self._stop_status_updates()

        # Get current progress for the message
        current = self.check_progress['current']
        total = self.check_progress['total']

        # Reset status to idle
        self.check_progress['status'] = 'idle'
        self._save_progress()

        logger.info(f"Stream check cancelled by user. Processed {current}/{total} streams before cancellation.")

        return {"status": "success", "message": f"✅ Stream check cancelled.\n\nProcessed {current}/{total} streams before cancellation.\n\nPartial results have been saved and can be viewed with '📋 View Last Results'."}

    def view_results_action(self, settings, logger):
        """View summary of the last completed stream check."""
        if self.check_progress['status'] == 'running':
            return {"status": "info", "message": "A stream check is currently running.\n\nUse '📊 View Check Progress' to see the current status."}

        if not os.path.exists(self.results_file):
            return {"status": "info", "message": "No results available yet.\n\nUse '▶️ Start Stream Check' to begin checking streams."}

        with open(self.results_file, 'r') as f:
            results = json.load(f)

        if not results:
            return {"status": "info", "message": "No results available yet.\n\nUse '▶️ Start Stream Check' to begin checking streams."}

        # Show results summary
        alive = sum(1 for r in results if r.get('status') == 'Alive')
        formats = {r.get('format', 'Unknown'): 0 for r in results if r.get('status') == 'Alive'}
        for r in results:
            if r.get('status') == 'Alive':
                formats[r.get('format', 'Unknown')] += 1

        summary = [
            f"📊 Last Check Results ({len(results)} streams):",
            f"✅ Alive: {alive}",
            f"❌ Dead: {len(results) - alive}\n",
            "📺 Alive Stream Formats:"
        ]
        for fmt, count in sorted(formats.items()):
            if count > 0:
                summary.append(f"  • {fmt}: {count}")

        return {"status": "success", "message": "\n".join(summary)}

    def _get_api_token(self, settings, logger, force_refresh=False):
        """Get an API access token using username and password with caching."""
        # Check if we have a valid cached token
        if not force_refresh and self.cached_token and self.token_cache_time:
            time_elapsed = time.time() - self.token_cache_time
            if time_elapsed < self.token_cache_duration:
                logger.debug(f"Using cached API token (age: {time_elapsed:.0f}s)")
                return self.cached_token, None

        dispatcharr_url = settings.get("dispatcharr_url", "").strip().rstrip('/')
        username = settings.get("dispatcharr_username", "")
        password = settings.get("dispatcharr_password", "")

        if not all([dispatcharr_url, username, password]):
            return None, "Dispatcharr URL, Username, and Password must be configured."

        try:
            url = f"{dispatcharr_url}/api/accounts/token/"
            payload = {"username": username, "password": password}
            response = requests.post(url, json=payload, timeout=15)

            if response.status_code == 401:
                # Invalidate cache on auth failure
                self.cached_token = None
                self.token_cache_time = None
                return None, "Authentication failed. Please check your username and password."

            response.raise_for_status()
            access_token = response.json().get("access")

            if not access_token:
                return None, "Login successful, but no access token was returned by the API."

            # Cache the token
            self.cached_token = access_token
            self.token_cache_time = time.time()

            logger.info("Successfully obtained and cached API access token.")
            return access_token, None
        except requests.exceptions.ConnectionError as e:
            return None, f"Unable to connect to the Dispatcharr URL: {e}"
        except requests.RequestException as e:
            return None, f"A network error occurred while authenticating: {e}"

    def _get_api_data(self, endpoint, token, settings):
        """Helper to perform GET requests to the Dispatcharr API."""
        dispatcharr_url = settings.get("dispatcharr_url", "").strip().rstrip('/')
        url = f"{dispatcharr_url}{endpoint}"
        headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        json_data = response.json()
        if isinstance(json_data, dict):
            return json_data.get('results', json_data)
        elif isinstance(json_data, list):
            return json_data
        return []
    
    def _post_api_data(self, endpoint, token, payload, settings):
        """Helper to perform POST requests to the Dispatcharr API."""
        dispatcharr_url = settings.get("dispatcharr_url", "").strip().rstrip('/')
        url = f"{dispatcharr_url}{endpoint}"
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

    def _trigger_m3u_refresh(self, token, settings, logger):
        """Triggers a global M3U refresh to update the GUI via WebSockets."""
        logger.info("Triggering M3U refresh to update the GUI...")
        try:
            self._post_api_data("/api/m3u/refresh/", token, {}, settings)
            logger.info("M3U refresh triggered successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to trigger M3U refresh: {e}")
            return False

    def load_groups_action(self, settings, logger):
        """Load channels and streams from specified Dispatcharr groups."""
        try:
            token, error = self._get_api_token(settings, logger)
            if error: return {"status": "error", "message": error}

            group_names_str = settings.get("group_names", "").strip()
            all_groups = self._get_api_data("/api/channels/groups/", token, settings)
            group_name_to_id = {g['name']: g['id'] for g in all_groups if 'name' in g and 'id' in g}

            if not group_names_str:
                target_group_names, target_group_ids = set(group_name_to_id.keys()), set(group_name_to_id.values())
                if not target_group_ids: return {"status": "error", "message": "No groups found in Dispatcharr."}
            else:
                input_names = {name.strip() for name in group_names_str.split(',') if name.strip()}
                valid_names, invalid_names = {n for n in input_names if n in group_name_to_id}, input_names - {n for n in input_names if n in group_name_to_id}
                target_group_ids, target_group_names = {group_name_to_id[name] for name in valid_names}, valid_names
                if not target_group_ids: return {"status": "error", "message": f"None of the specified groups could be found: {', '.join(invalid_names)}"}

            all_channels = self._get_api_data("/api/channels/channels/", token, settings)
            loaded_channels = []
            for channel in all_channels:
                if channel.get('channel_group_id') in target_group_ids:
                    logger.info(f"Fetching streams for channel: {channel.get('name')}")
                    channel_streams = self._get_api_data(f"/api/channels/channels/{channel['id']}/streams/", token, settings)
                    loaded_channels.append({**channel, "streams": channel_streams})
            
            with open(self.loaded_channels_file, 'w') as f: json.dump(loaded_channels, f)

            total_streams = sum(len(c.get('streams', [])) for c in loaded_channels)
            group_msg = "all groups" if not group_names_str else f"group(s): {', '.join(target_group_names)}"

            timeout = settings.get("timeout", 10)
            retries = settings.get("dead_connection_retries", 3)
            parallel_enabled = settings.get("enable_parallel_checking", False)
            parallel_workers = settings.get("parallel_workers", 2)

            # Estimate time based on mode
            if parallel_enabled:
                # Parallel mode: divide by workers, account for overhead
                estimated_seconds = (total_streams / parallel_workers) * 8.5 * 1.1  # 10% overhead
                mode_info = f" (parallel mode with {parallel_workers} workers)"
            else:
                # Sequential mode: ~8-10 seconds average per stream + 20% buffer
                estimated_seconds = total_streams * 8.5 * 1.2  # 20% extra time
                mode_info = " (sequential mode)"

            estimated_minutes = estimated_seconds / 60

            message = f"Successfully loaded {len(loaded_channels)} channels with {total_streams} streams from {group_msg}."
            if 'invalid_names' in locals() and invalid_names:
                message += f"\n\nWarning: Ignored groups not found: {', '.join(invalid_names)}"
            if total_streams > 0:
                message += f"\n\nNext, click '▶️ Start Stream Check'. Estimated time{mode_info}: {estimated_minutes:.0f} minutes."
                if not parallel_enabled and total_streams > 50:
                    message += f"\n\nTip: Enable 'Parallel Stream Checking' in settings to speed up processing significantly!"

            return {"status": "success", "message": message}
        except Exception as e: return {"status": "error", "message": str(e)}

    def check_streams_action(self, settings, logger, context=None):
        """Check status and format of all loaded streams with auto status updates."""
        # Use lock to prevent race condition when starting multiple checks
        with self.check_lock:
            # Check if a check is already running
            if self.check_progress['status'] == 'running':
                current, total = self.check_progress['current'], self.check_progress['total']
                percent = (current / total * 100) if total > 0 else 0
                return {"status": "info", "message": f"A stream check is already running ({percent:.0f}% complete).\n\nUse '📊 View Check Progress' to monitor the current check."}

            if not os.path.exists(self.loaded_channels_file):
                return {"status": "error", "message": "No channels loaded. Please run '📥 Load Group(s)' first."}

            with open(self.loaded_channels_file, 'r') as f:
                loaded_channels = json.load(f)

            all_streams = [
                {"channel_id": ch['id'], "channel_name": ch['name'], "stream_url": s['url'], "stream_id": s['id']}
                for ch in loaded_channels for s in ch.get('streams', []) if s.get('url')
            ]

            if not all_streams:
                return {"status": "error", "message": "The loaded groups contain no streams to check."}

            # Set status to running atomically within the lock
            self.check_progress = {"current": 0, "total": len(all_streams), "status": "running", "start_time": time.time()}
            self._save_progress()
            logger.info(f"Starting check for {len(all_streams)} streams...")

            # Start background status updates
            if context:
                self._start_status_updates(context)
        
        # Return immediately to avoid timeout, processing continues in background
        timeout = settings.get("timeout", 10)
        parallel_enabled = settings.get("enable_parallel_checking", False)
        parallel_workers = settings.get("parallel_workers", 2)

        # Calculate estimated time based on mode
        if parallel_enabled:
            estimated_total_time = (len(all_streams) / parallel_workers) * 8.5 * 1.1 / 60  # 10% overhead
            mode_info = f" (parallel mode with {parallel_workers} workers)"
        else:
            estimated_total_time = len(all_streams) * 8.5 * 1.2 / 60  # 20% buffer
            mode_info = " (sequential mode)"

        # Start the actual processing in background
        import threading
        processing_thread = threading.Thread(
            target=self._process_streams_background,
            args=(all_streams, settings, logger)
        )
        processing_thread.daemon = True
        processing_thread.start()

        return {"status": "success", "message": f"✅ Stream checking started for {len(all_streams)} streams.\nEstimated completion time{mode_info}: {estimated_total_time:.0f} minutes.\n\nUse '📊 View Check Progress' to monitor progress."}

    def _process_streams_background(self, all_streams, settings, logger):
        """Background processing of streams to avoid request timeout"""
        enable_parallel = settings.get("enable_parallel_checking", False)

        if enable_parallel:
            self._process_streams_parallel(all_streams, settings, logger)
        else:
            self._process_streams_sequential(all_streams, settings, logger)

    def _process_streams_sequential(self, all_streams, settings, logger):
        """Sequential stream processing (original implementation)"""
        results = []
        timeout = settings.get("timeout", 10)
        retries = settings.get("dead_connection_retries", 3)
        self.timeout_retry_queue = []
        streams_processed_since_retry = 0

        try:
            for i, stream_data in enumerate(all_streams):
                if self.stop_status_updates:  # Allow early termination
                    break

                self.check_progress["current"] = i + 1
                self._save_progress()

                # Check stream - NO immediate retries, we'll handle them in the background queue
                result = self.check_stream(stream_data, timeout, 0, logger, skip_retries=True)

                # If stream timed out and we have retries enabled, add to retry queue
                if result.get('error_type') == 'Timeout' and retries > 0:
                    self.timeout_retry_queue.append({**stream_data, "retry_count": 0})
                    logger.info(f"Added '{stream_data.get('channel_name')}' to retry queue due to timeout")

                results.append({**stream_data, **result})
                streams_processed_since_retry += 1

                # Process timeout retry queue every 4 streams
                if streams_processed_since_retry >= 4 and self.timeout_retry_queue:
                    retry_stream = self.timeout_retry_queue.pop(0)
                    retry_stream["retry_count"] += 1

                    if retry_stream["retry_count"] <= retries:
                        logger.info(f"Retrying timeout stream: '{retry_stream.get('channel_name')}' (attempt {retry_stream['retry_count']}/{retries})")
                        retry_result = self.check_stream(retry_stream, timeout, 0, logger, skip_retries=True)  # No immediate retries

                        # Update the original result in the results list
                        for j, existing_result in enumerate(results):
                            if (existing_result.get('channel_id') == retry_stream.get('channel_id') and
                                existing_result.get('stream_id') == retry_stream.get('stream_id')):
                                results[j] = {**retry_stream, **retry_result}
                                break

                        # If still timing out, add back to queue for another retry
                        if retry_result.get('error_type') == 'Timeout' and retry_stream["retry_count"] < retries:
                            self.timeout_retry_queue.append(retry_stream)

                    streams_processed_since_retry = 0

                # Add 3 second delay between stream checks
                time.sleep(3)

            # Process any remaining timeout retries
            while self.timeout_retry_queue:
                retry_stream = self.timeout_retry_queue.pop(0)
                if retry_stream["retry_count"] < retries:
                    retry_stream["retry_count"] += 1
                    logger.info(f"Final retry for timeout stream: '{retry_stream.get('channel_name')}' (attempt {retry_stream['retry_count']}/{retries})")
                    retry_result = self.check_stream(retry_stream, timeout, 0, logger, skip_retries=True)

                    # Update the original result in the results list
                    for j, existing_result in enumerate(results):
                        if (existing_result.get('channel_id') == retry_stream.get('channel_id') and
                            existing_result.get('stream_id') == retry_stream.get('stream_id')):
                            results[j] = {**retry_stream, **retry_result}
                            break

            with open(self.results_file, 'w') as f:
                json.dump(results, f, indent=2)

        except Exception as e:
            logger.error(f"Background stream processing error: {e}")
        finally:
            self.check_progress['status'] = 'idle'
            self.check_progress['end_time'] = time.time()
            self._save_progress()
            self._stop_status_updates()

            # Set completion message
            processed_count = len(results)
            self.completion_message = f"Stream checking completed. Processed {processed_count} streams."
            logger.info(f"Stream checking completed. Processed {processed_count} streams.")

    def _process_streams_parallel(self, all_streams, settings, logger):
        """Parallel stream processing using ThreadPoolExecutor"""
        results = []
        timeout = settings.get("timeout", 10)
        retries = settings.get("dead_connection_retries", 3)
        workers = settings.get("parallel_workers", 2)

        # Thread-safe data structures
        import threading
        results_lock = threading.Lock()
        results_dict = {}  # Use dict to track results by stream index

        try:
            logger.info(f"Starting parallel stream checking with {workers} workers")

            # First pass: check all streams in parallel
            with ThreadPoolExecutor(max_workers=workers) as executor:
                # Submit all stream checks
                future_to_index = {
                    executor.submit(self.check_stream, stream_data, timeout, 0, logger, skip_retries=True): i
                    for i, stream_data in enumerate(all_streams)
                }

                # Process results as they complete
                for future in as_completed(future_to_index):
                    if self.stop_status_updates:
                        executor.shutdown(wait=False)
                        break

                    index = future_to_index[future]
                    stream_data = all_streams[index]

                    try:
                        result = future.result()

                        with results_lock:
                            results_dict[index] = {**stream_data, **result}
                            self.check_progress["current"] = len(results_dict)
                            self._save_progress()

                    except Exception as e:
                        logger.error(f"Error checking stream '{stream_data.get('channel_name')}': {e}")
                        with results_lock:
                            results_dict[index] = {
                                **stream_data,
                                'status': 'Dead',
                                'error': str(e),
                                'error_type': 'Other',
                                'format': 'N/A',
                                'framerate_num': 0
                            }
                            self.check_progress["current"] = len(results_dict)
                            self._save_progress()

            # Rebuild results list in original order
            results = [results_dict[i] for i in range(len(all_streams)) if i in results_dict]

            # Handle retries for timeout streams if enabled
            if retries > 0:
                timeout_streams = [(i, r) for i, r in enumerate(results) if r.get('error_type') == 'Timeout']

                if timeout_streams:
                    logger.info(f"Found {len(timeout_streams)} timeout streams, retrying...")

                    for retry_attempt in range(retries):
                        if not timeout_streams:
                            break

                        logger.info(f"Retry attempt {retry_attempt + 1}/{retries} for {len(timeout_streams)} streams")

                        with ThreadPoolExecutor(max_workers=workers) as executor:
                            future_to_result_index = {
                                executor.submit(
                                    self.check_stream,
                                    {k: v for k, v in result.items() if k in ['channel_id', 'channel_name', 'stream_url', 'stream_id']},
                                    timeout, 0, logger, skip_retries=True
                                ): result_index
                                for result_index, result in timeout_streams
                            }

                            for future in as_completed(future_to_result_index):
                                result_index = future_to_result_index[future]
                                try:
                                    retry_result = future.result()
                                    # Update the result
                                    results[result_index] = {**results[result_index], **retry_result}
                                except Exception as e:
                                    logger.error(f"Error during retry: {e}")

                        # Find remaining timeout streams for next retry
                        timeout_streams = [(i, r) for i, r in enumerate(results) if r.get('error_type') == 'Timeout']

            with open(self.results_file, 'w') as f:
                json.dump(results, f, indent=2)

        except Exception as e:
            logger.error(f"Background parallel stream processing error: {e}")
        finally:
            self.check_progress['status'] = 'idle'
            self.check_progress['end_time'] = time.time()
            self._save_progress()
            self._stop_status_updates()

            # Set completion message
            processed_count = len(results)
            self.completion_message = f"Stream checking completed. Processed {processed_count} streams (parallel mode with {workers} workers)."
            logger.info(f"Stream checking completed. Processed {processed_count} streams.")

    def rename_channels_action(self, settings, logger):
        """Rename channels that were marked as dead in the last check."""
        rename_format = settings.get("dead_rename_format", "").strip()
        if not rename_format:
            return {"status": "error", "message": "Please configure a Dead Channel Rename Format before renaming."}

        if "{name}" not in rename_format:
            return {"status": "error", "message": "Dead Channel Rename Format must contain {name} placeholder."}

        if not os.path.exists(self.results_file):
            return {"status": "error", "message": "No check results found. Please run 'Check Streams' first."}

        with open(self.results_file, 'r') as f: results = json.load(f)

        dead_channels = {r['channel_id']: r['channel_name'] for r in results if r['status'] == 'Dead'}
        if not dead_channels: return {"status": "success", "message": "No dead channels found in the last check."}

        payload = []
        for cid, name in dead_channels.items():
            new_name = rename_format.replace('{name}', name)

            if new_name != name:
                payload.append({'id': cid, 'name': new_name})

        if not payload: return {"status": "success", "message": "No channels needed renaming."}

        try:
            token, error = self._get_api_token(settings, logger)
            if error: return {"status": "error", "message": error}
            count = self._perform_bulk_patch(token, settings, logger, payload)
            self._trigger_m3u_refresh(token, settings, logger)
            return {"status": "success", "message": f"Successfully renamed {count} dead channels. GUI refresh triggered."}
        except Exception as e: return {"status": "error", "message": str(e)}

    def move_dead_channels_action(self, settings, logger):
        """Move channels marked as dead to a new group."""
        move_to_group_name = settings.get("move_to_group_name", "Graveyard").strip()
        if not move_to_group_name:
            return {"status": "error", "message": "Please enter a destination group name in the settings."}

        if not os.path.exists(self.results_file):
            return {"status": "error", "message": "No check results found. Please run 'Check Streams' first."}

        with open(self.results_file, 'r') as f: results = json.load(f)
        
        dead_channel_ids = {r['channel_id'] for r in results if r['status'] == 'Dead'}
        if not dead_channel_ids: return {"status": "success", "message": "No dead channels were found in the last check."}
        
        try:
            token, error = self._get_api_token(settings, logger)
            if error: return {"status": "error", "message": error}
            
            all_groups = self._get_api_data("/api/channels/groups/", token, settings)
            dest_group = next((g for g in all_groups if g['name'] == move_to_group_name), None)

            if dest_group:
                new_group_id = dest_group['id']
                logger.info(f"Destination group '{move_to_group_name}' found with ID: {new_group_id}")
            else:
                logger.info(f"Destination group '{move_to_group_name}' not found. Creating it...")
                new_group = self._post_api_data("/api/channels/groups/", token, {'name': move_to_group_name}, settings)
                new_group_id = new_group['id']
                logger.info(f"Group '{move_to_group_name}' created with ID: {new_group_id}")
            
            payload = [{'id': cid, 'channel_group_id': new_group_id} for cid in dead_channel_ids]
            moved_count = self._perform_bulk_patch(token, settings, logger, payload)
            self._trigger_m3u_refresh(token, settings, logger)
            return {"status": "success", "message": f"Successfully moved {moved_count} dead channels to group '{move_to_group_name}'. GUI refresh triggered."}

        except Exception as e: return {"status": "error", "message": str(e)}
        
    def rename_low_framerate_channels_action(self, settings, logger):
        """Rename channels with low framerate streams."""
        rename_format = settings.get("low_framerate_rename_format", "").strip()

        if not rename_format:
            return {"status": "error", "message": "Please configure a Low Framerate Rename Format."}

        if "{name}" not in rename_format:
            return {"status": "error", "message": "Low Framerate Rename Format must contain {name} placeholder."}

        if not os.path.exists(self.results_file):
            return {"status": "error", "message": "No check results found. Please run 'Check Streams' first."}

        with open(self.results_file, 'r') as f: results = json.load(f)

        low_fps_channels = {r['channel_id']: r['channel_name'] for r in results if 0 < r.get('framerate_num', 0) < 30}
        if not low_fps_channels: return {"status": "success", "message": "No low framerate channels found."}

        payload = []
        for cid, name in low_fps_channels.items():
            new_name = rename_format.replace('{name}', name)

            if new_name != name:
                payload.append({'id': cid, 'name': new_name})

        if not payload: return {"status": "success", "message": "No channels needed renaming."}

        try:
            token, error = self._get_api_token(settings, logger)
            if error: return {"status": "error", "message": error}
            count = self._perform_bulk_patch(token, settings, logger, payload)
            self._trigger_m3u_refresh(token, settings, logger)
            return {"status": "success", "message": f"Successfully renamed {count} low framerate channels. GUI refresh triggered."}
        except Exception as e: return {"status": "error", "message": str(e)}

    def move_low_framerate_channels_action(self, settings, logger):
        """Move channels with low framerate streams to a new group."""
        group_name = settings.get("move_low_framerate_group", "Slow").strip()
        if not group_name:
            return {"status": "error", "message": "Please enter a destination group name."}

        if not os.path.exists(self.results_file):
            return {"status": "error", "message": "No check results found. Please run 'Check Streams' first."}

        with open(self.results_file, 'r') as f: results = json.load(f)
        
        low_fps_channel_ids = {r['channel_id'] for r in results if 0 < r.get('framerate_num', 0) < 30}
        if not low_fps_channel_ids: return {"status": "success", "message": "No low framerate channels found to move."}
        
        try:
            token, error = self._get_api_token(settings, logger)
            if error: return {"status": "error", "message": error}
            
            all_groups = self._get_api_data("/api/channels/groups/", token, settings)
            dest_group = next((g for g in all_groups if g['name'] == group_name), None)

            if dest_group:
                new_group_id = dest_group['id']
            else:
                logger.info(f"Destination group '{group_name}' not found. Creating it...")
                new_group = self._post_api_data("/api/channels/groups/", token, {'name': group_name}, settings)
                new_group_id = new_group['id']
            
            payload = [{'id': cid, 'channel_group_id': new_group_id} for cid in low_fps_channel_ids]
            moved_count = self._perform_bulk_patch(token, settings, logger, payload)
            self._trigger_m3u_refresh(token, settings, logger)
            return {"status": "success", "message": f"Successfully moved {moved_count} low framerate channels to group '{group_name}'. GUI refresh triggered."}
        except Exception as e: return {"status": "error", "message": str(e)}

    def add_video_format_suffix_action(self, settings, logger):
        """Adds a format suffix like [HD] to channel names."""
        suffixes_to_add_str = settings.get("video_format_suffixes", "4k, FHD, HD, SD, Unknown").strip().lower()
        if not suffixes_to_add_str:
            return {"status": "error", "message": "Please specify which video formats should have a suffix added."}
        
        suffixes_to_add = {s.strip() for s in suffixes_to_add_str.split(',')}
        
        if not os.path.exists(self.results_file):
            return {"status": "error", "message": "No check results found. Please run 'Check Streams' first."}

        with open(self.results_file, 'r') as f: results = json.load(f)
        
        channel_formats = {}
        for r in results:
            if r['status'] == 'Alive':
                channel_formats[r['channel_id']] = r.get('format', 'Unknown')

        if not channel_formats: return {"status": "success", "message": "No alive channels found to update."}

        try:
            token, error = self._get_api_token(settings, logger)
            if error: return {"status": "error", "message": error}
            
            all_channels = self._get_api_data("/api/channels/channels/", token, settings)
            channel_id_to_name = {c['id']: c['name'] for c in all_channels}

            payload = []
            for cid, fmt in channel_formats.items():
                if fmt.lower() in suffixes_to_add:
                    current_name = channel_id_to_name.get(cid)
                    suffix = f" [{fmt.upper()}]"
                    if current_name and not current_name.endswith(suffix):
                        payload.append({'id': cid, 'name': current_name + suffix})

            if not payload: return {"status": "success", "message": "No channels needed a format suffix added."}
            
            updated_count = self._perform_bulk_patch(token, settings, logger, payload)
            self._trigger_m3u_refresh(token, settings, logger)
            return {"status": "success", "message": f"Successfully added format suffixes to {updated_count} channels. GUI refresh triggered."}

        except Exception as e: return {"status": "error", "message": str(e)}

    def view_table_action(self, settings, logger):
        """Display results in table format"""
        if not os.path.exists(self.results_file): return {"status": "error", "message": "No results available."}
        with open(self.results_file, 'r') as f: results = json.load(f)
        lines = ["="*120, f"{'Channel Name':<35} {'Status':<8} {'Format':<8} {'FPS':<8} {'Error Type':<20} {'Error Details':<35}", "="*120]
        for r in results:
            fps = r.get('framerate_num', 0)
            fps_str = f"{fps:.1f}" if fps > 0 else "N/A"
            error_type = r.get('error_type', 'N/A')
            error_details = r.get('error', '')[:34] if r.get('error') else ''
            lines.append(f"{r.get('channel_name', 'N/A')[:34]:<35} {r.get('status', 'N/A'):<8} {r.get('format', 'N/A'):<8} {fps_str:<8} {error_type:<20} {error_details:<35}")
        lines.append("="*120)
        return {"status": "success", "message": "\n".join(lines)}

    def _generate_csv_header_comments(self, settings, results):
        """Generate CSV header comments with settings and statistics"""
        lines = []
        lines.append("# IPTV Checker Plugin - Export Results")
        lines.append(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"# Plugin Version: {self.version}")
        lines.append("#")

        # Add timing information
        if self.check_progress.get('start_time') and self.check_progress.get('end_time'):
            start_time = self.check_progress['start_time']
            end_time = self.check_progress['end_time']
            start_str = datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')
            end_str = datetime.fromtimestamp(end_time).strftime('%Y-%m-%d %H:%M:%S')
            duration_seconds = end_time - start_time
            hours = int(duration_seconds // 3600)
            minutes = int((duration_seconds % 3600) // 60)
            seconds = int(duration_seconds % 60)

            lines.append("# Check Timing:")
            lines.append(f"#   Start Time: {start_str}")
            lines.append(f"#   End Time: {end_str}")
            if hours > 0:
                lines.append(f"#   Duration: {hours}h {minutes}m {seconds}s")
            elif minutes > 0:
                lines.append(f"#   Duration: {minutes}m {seconds}s")
            else:
                lines.append(f"#   Duration: {seconds}s")
            lines.append("#")

        # Add plugin settings (excluding sensitive information)
        lines.append("# Plugin Settings:")
        lines.append(f"#   Group(s) Checked: {settings.get('group_names', 'All groups')}")
        lines.append(f"#   Connection Timeout: {settings.get('timeout', 10)} seconds")
        lines.append(f"#   Dead Connection Retries: {settings.get('dead_connection_retries', 3)}")
        lines.append(f"#   Dead Rename Format: {settings.get('dead_rename_format', '{name} [DEAD]')}")
        lines.append(f"#   Move Dead to Group: {settings.get('move_to_group_name', 'Graveyard')}")
        lines.append(f"#   Low Framerate Rename Format: {settings.get('low_framerate_rename_format', '{name} [Slow]')}")
        lines.append(f"#   Move Low Framerate to Group: {settings.get('move_low_framerate_group', 'Slow')}")
        lines.append(f"#   Video Format Suffixes: {settings.get('video_format_suffixes', '4k, FHD, HD, SD, Unknown')}")
        lines.append(f"#   Parallel Checking Enabled: {settings.get('enable_parallel_checking', False)}")
        lines.append(f"#   Parallel Workers: {settings.get('parallel_workers', 2)}")
        lines.append("#")

        # Calculate cumulative statistics
        total_streams = len(results)
        alive_streams = sum(1 for r in results if r.get('status') == 'Alive')
        dead_streams = total_streams - alive_streams

        # Format distribution
        format_counts = {}
        for r in results:
            if r.get('status') == 'Alive':
                fmt = r.get('format', 'Unknown')
                format_counts[fmt] = format_counts.get(fmt, 0) + 1

        # Average framerate for alive streams
        alive_framerates = [r.get('framerate_num', 0) for r in results if r.get('status') == 'Alive' and r.get('framerate_num', 0) > 0]
        avg_framerate = sum(alive_framerates) / len(alive_framerates) if alive_framerates else 0

        # Error type distribution
        error_counts = {}
        for r in results:
            if r.get('status') == 'Dead':
                error_type = r.get('error_type', 'Other')
                error_counts[error_type] = error_counts.get(error_type, 0) + 1

        # Add cumulative statistics
        lines.append("# Cumulative Statistics:")
        lines.append(f"#   Total Streams: {total_streams}")
        lines.append(f"#   Alive Streams: {alive_streams} ({(alive_streams/total_streams*100):.1f}%)")
        lines.append(f"#   Dead Streams: {dead_streams} ({(dead_streams/total_streams*100):.1f}%)")

        if format_counts:
            lines.append("#")
            lines.append("#   Alive Stream Formats:")
            for fmt in sorted(format_counts.keys()):
                count = format_counts[fmt]
                lines.append(f"#     {fmt}: {count} ({(count/alive_streams*100):.1f}%)")

        if avg_framerate > 0:
            lines.append("#")
            lines.append(f"#   Average Framerate (Alive): {avg_framerate:.1f} fps")

        # Low framerate streams
        low_fps_count = sum(1 for r in results if r.get('status') == 'Alive' and 0 < r.get('framerate_num', 0) < 30)
        if low_fps_count > 0:
            lines.append(f"#   Low Framerate Streams (<30fps): {low_fps_count}")

        if error_counts:
            lines.append("#")
            lines.append("#   Error Type Distribution:")
            for error_type in sorted(error_counts.keys()):
                count = error_counts[error_type]
                lines.append(f"#     {error_type}: {count} ({(count/dead_streams*100):.1f}%)")

        lines.append("#")
        lines.append("# " + "="*80)
        lines.append("#")

        return lines

    def export_results_action(self, settings, logger):
        """Export results to CSV"""
        if not os.path.exists(self.results_file): return {"status": "error", "message": "No results to export."}
        with open(self.results_file, 'r') as f: results = json.load(f)

        # Round framerate to whole number for cleaner CSV
        for result in results:
            if 'framerate_num' in result and result['framerate_num'] > 0:
                result['framerate_num'] = round(result['framerate_num'])

        filepath = f"/data/exports/iptv_checker_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        os.makedirs("/data/exports", exist_ok=True)
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            # Write header comments
            header_comments = self._generate_csv_header_comments(settings, results)
            for comment_line in header_comments:
                f.write(comment_line + '\n')

            # Write CSV data
            writer = csv.DictWriter(f, fieldnames=['channel_id', 'channel_name', 'stream_id', 'status', 'format', 'framerate_num', 'error_type', 'error'], extrasaction='ignore')
            writer.writeheader()
            writer.writerows(results)
        return {"status": "success", "message": f"Results exported to {filepath}"}

    def clear_csv_exports_action(self, settings, logger):
        """Delete all CSV export files created by this plugin."""
        exports_dir = "/data/exports"

        if not os.path.exists(exports_dir):
            return {"status": "info", "message": "No exports directory found. No CSV files to delete."}

        # Find all CSV files that match our naming pattern
        csv_files = [f for f in os.listdir(exports_dir) if f.startswith('iptv_checker_results_') and f.endswith('.csv')]

        if not csv_files:
            return {"status": "info", "message": "No CSV export files found in /data/exports/."}

        # Delete all matching CSV files
        deleted_count = 0
        for csv_file in csv_files:
            try:
                filepath = os.path.join(exports_dir, csv_file)
                os.remove(filepath)
                deleted_count += 1
                logger.info(f"Deleted CSV export: {csv_file}")
            except Exception as e:
                logger.error(f"Failed to delete {csv_file}: {e}")

        if deleted_count == 0:
            return {"status": "error", "message": "Failed to delete any CSV files."}
        elif deleted_count < len(csv_files):
            return {"status": "success", "message": f"⚠️ Partially cleared: Deleted {deleted_count} of {len(csv_files)} CSV files.\n\nSome files could not be deleted. Check logs for details."}
        else:
            return {"status": "success", "message": f"✅ Successfully deleted {deleted_count} CSV export file(s) from /data/exports/."}

    def _perform_bulk_patch(self, token, settings, logger, payload):
        """Send a bulk PATCH request to the Dispatcharr API."""
        if not payload: return 0
        dispatcharr_url = settings.get("dispatcharr_url", "").strip().rstrip('/')
        url = f"{dispatcharr_url}/api/channels/channels/edit/bulk/"
        headers = {'Authorization': f"Bearer {token}", 'Content-Type': 'application/json'}
        logger.info(f"Sending bulk patch for {len(payload)} channels.")
        response = requests.patch(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        logger.info(f"Successfully patched {len(payload)} channels.")
        return len(payload)

    def _get_stream_format(self, resolution_str):
        """Determine video format from a resolution string."""
        if 'x' not in resolution_str: return "Unknown"
        try:
            width = int(resolution_str.split('x')[0])
            if width >= 3800: return "4K"
            if width >= 1900: return "FHD"
            if width >= 1200: return "HD"
            if width > 0: return "SD"
            return "Unknown"
        except: return "Unknown"
        
    def parse_framerate(self, framerate_str):
        """Parse framerate string like '30000/1001' to a float."""
        try:
            if '/' in framerate_str:
                num, den = map(float, framerate_str.split('/'))
                return num / den if den != 0 else 0
            return float(framerate_str)
        except (ValueError, ZeroDivisionError): return 0

    def check_stream(self, stream_data, timeout, retries, logger, skip_retries=False):
        """Check individual stream status with optional retries."""
        url, channel_name = stream_data.get('stream_url'), stream_data.get('channel_name')
        last_error = "Unknown error"
        last_error_type = "Other"
        default_return = {'status': 'Dead', 'error': '', 'error_type': 'Other', 'format': 'N/A', 'framerate_num': 0}

        # Determine how many attempts to make
        max_attempts = 1 if skip_retries else (retries + 1)

        for attempt in range(max_attempts):
            try:
                cmd = ['/usr/local/bin/ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', '-user_agent', 'IPTVChecker 1.0', '-timeout', str(timeout * 1000000), url]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
                
                if result.returncode == 0:
                    probe_data = json.loads(result.stdout)
                    video_stream = next((s for s in probe_data.get('streams', []) if s['codec_type'] == 'video'), None)
                    if video_stream:
                        resolution = f"{video_stream.get('width', 0)}x{video_stream.get('height', 0)}"
                        framerate_num = self.parse_framerate(video_stream.get('r_frame_rate', '0/1'))
                        return {'status': 'Alive', 'error': '', 'error_type': 'N/A', 'format': self._get_stream_format(resolution), 'framerate_num': framerate_num}
                    else: 
                        last_error = 'No video stream found'
                        last_error_type = 'No Video Stream'
                else: 
                    error_output = result.stderr.strip() or 'Stream not accessible'
                    last_error = error_output
                    
                    # Categorize the error type based on common ffprobe error patterns
                    error_lower = error_output.lower()
                    if 'timed out' in error_lower or 'timeout' in error_lower or 'connection timeout' in error_lower:
                        last_error_type = 'Timeout'
                        last_error = 'Connection timeout'
                    elif '404' in error_output or 'not found' in error_lower or 'no such file' in error_lower:
                        last_error_type = '404 Not Found'
                        last_error = '404 Not Found'
                    elif '403' in error_output or 'forbidden' in error_lower:
                        last_error_type = '403 Forbidden' 
                        last_error = '403 Forbidden'
                    elif '500' in error_output or 'internal server error' in error_lower:
                        last_error_type = 'Server Error'
                        last_error = '500 Server Error'
                    elif 'connection refused' in error_lower:
                        last_error_type = 'Connection Refused'
                        last_error = 'Connection refused'
                    elif 'network unreachable' in error_lower or 'no route to host' in error_lower:
                        last_error_type = 'Network Unreachable'
                        last_error = 'Network unreachable'
                    elif 'invalid data found' in error_lower or 'invalid argument' in error_lower:
                        last_error_type = 'Invalid Stream'
                        last_error = 'Invalid stream format'
                    elif 'protocol not supported' in error_lower:
                        last_error_type = 'Unsupported Protocol'
                        last_error = 'Unsupported protocol'
                    elif result.returncode == 1:
                        # Common ffprobe return code for unreachable streams
                        last_error_type = 'Stream Unreachable'
                        last_error = 'Stream unreachable'
                    else:
                        last_error_type = 'Other'
                        # Keep original error but make it cleaner
                        if 'stream not accessible' in error_lower:
                            last_error = 'Stream not accessible'
                        
            except subprocess.TimeoutExpired: 
                last_error = 'Connection timeout'
                last_error_type = 'Timeout'
            except Exception as e: 
                last_error = str(e)
                last_error_type = 'Other'

            # Only do immediate retries if not skipping them and not the last attempt
            if not skip_retries and attempt < max_attempts - 1:
                logger.info(f"Channel '{channel_name}' stream check failed. Retrying ({attempt+1}/{retries})...")
                time.sleep(1)
        
        default_return['error'] = last_error
        default_return['error_type'] = last_error_type
        return default_return

# Export for Dispatcharr plugin system - Single shared instance to maintain state
_plugin_instance = Plugin()

# Export the same instance with different names for compatibility
plugin = _plugin_instance
plugin_instance = _plugin_instance
iptv_checker = _plugin_instance
IPTV_CHECKER = _plugin_instance

# Export class-level attributes
fields = Plugin.fields
actions = Plugin.actions