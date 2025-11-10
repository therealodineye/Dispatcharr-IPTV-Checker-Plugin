# Dispatcharr IPTV Checker Plugin

**Description:** Check IPTV stream status, analyze stream quality, and manage channels based on results

## Features

- **Stream Status Checking:** Verify if IPTV streams are alive or dead with smart retry logic
- **Background Processing:** Stream checks run in background threads to prevent browser timeouts
- **Technical Analysis:** Extract resolution, framerate, and video format information
- **Dispatcharr Integration:** Direct API communication with automatic authentication
- **Channel Management:** Automated renaming and moving of channels based on analysis results
- **Group-Based Operations:** Work with existing Dispatcharr channel groups
- **Real-Time Progress Tracking:** Live ETA calculations based on actual processing speed
- **Smart Retry System:** Timeout streams queued and retried after other streams for better success rates
- **Enhanced Error Categorization:** Detailed error types (Timeout, 404, 403, Connection Refused, etc.)
- **Enhanced CSV Exports:** Includes error types and rounded framerate values
- **Server-Friendly Processing:** 3-second delays between checks for stability

## Requirements

### System Dependencies
This plugin requires **ffmpeg** and **ffprobe** to be installed in the Dispatcharr container for stream analysis.

**Default Locations:**
- **ffprobe:** `/usr/local/bin/ffprobe` (plugin default)
- **ffmpeg:** `/usr/local/bin/ffmpeg`

**Verify Installation:**
```bash
docker exec dispatcharr which ffprobe
docker exec dispatcharr which ffmpeg
```

### Dispatcharr Setup
- Active Dispatcharr installation with configured channels and groups
- Valid Dispatcharr username and password for API access
- Channel groups containing IPTV streams to analyze

## Installation

1. Log in to Dispatcharr's web UI
2. Navigate to **Plugins**
3. Click **Import Plugin** and upload the plugin zip file
4. Enable the plugin after installation

## Settings Reference

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| Dispatcharr URL | string | - | Full URL of your Dispatcharr instance |
| Dispatcharr Username | string | - | Username for API authentication |
| Dispatcharr Password | password | - | Password for API authentication |
| Groups to Check | string | - | Comma-separated group names, empty = all groups |
| Connection Timeout | number | 10 | Seconds to wait for stream connection |
| Dead Connection Retries | number | 3 | Number of retry attempts for failed streams |
| Dead Channel Rename Format | string | "{name} [DEAD]" | Format for renaming dead channels. Use {name} as placeholder |
| Move Dead Channels to Group | string | "Graveyard" | Group to move dead channels to |
| Low Framerate Rename Format | string | "{name} [Slow]" | Format for renaming low FPS channels. Use {name} as placeholder |
| Move Low Framerate Group | string | "Slow" | Group to move low framerate channels to |
| Video Format Suffixes | string | "4k, FHD, HD, SD, Unknown" | Formats to add as suffixes |
| Enable Parallel Checking | boolean | false | Check multiple streams simultaneously for faster processing |
| Number of Parallel Workers | number | 2 | How many streams to check at once (when parallel enabled) |

## Usage Guide

### Step-by-Step Workflow

1. **Configure Authentication**
   - Enter your **Dispatcharr URL** (e.g., http://127.0.0.1:9191)
   - Enter your **Dispatcharr Username** and **Password**
   - Optionally specify **Groups to Check** (leave empty to check all)
   - Configure retry and timeout settings
   - Optionally enable **Parallel Checking** for faster processing
   - Click **Save Settings**

2. **Validate Settings** *(Recommended)*
   - Click **Run** on **✅ Validate Settings**
   - Verifies connection, credentials, and group names
   - Confirms configuration before starting checks

3. **Load Channel Groups**
   - Click **Run** on **📥 Load Group(s)**
   - Review available groups and channel counts
   - Note the estimated checking time (varies by mode)
   - Tip appears if parallel mode would significantly speed up processing

4. **Check Streams**
   - Click **Run** on **▶️ Start Stream Check**
   - Processing runs in the background to prevent browser timeouts
   - Returns immediately with estimated completion time
   - Stream checking includes 3-second delays between checks for server stability

5. **Monitor Progress**
   - Click **📋 View Last Results** for real-time status with ETA
   - Shows format: "Checking streams X/Y - Z% complete | ETA: N min"
   - ETA calculated dynamically based on actual processing speed
   - Progress updates continue even if browser times out

6. **View Results**
   - Click **📋 View Last Results** for summary when complete
   - Shows alive/dead counts and format distribution
   - Use **📊 View Results Table** for detailed tabular format

7. **Manage Channels**
   - Use channel management actions based on results
   - All operations include confirmation dialogs
   - GUI automatically refreshes after changes

8. **Export Data**
   - Click **💾 Export Results to CSV** to save analysis data
   - CSV includes comprehensive header comments with:
     - Plugin settings used for the check
     - Cumulative statistics (alive/dead counts, percentages)
     - Format distribution and average framerate
     - Error type breakdown
   - Use **🗑️ Clear CSV Exports** to clean up old export files

## Action Reference

### Setup & Validation
- **✅ Validate Settings:** Verify API connection, credentials, and group names

### Core Stream Checking
- **📥 Load Group(s):** Load channels from specified groups
- **▶️ Start Stream Check:** Begin checking all loaded streams in background thread
- **📋 View Last Results:** View real-time progress with ETA or summary of completed check

### Channel Management
- **✏️ Rename Dead Channels:** Apply rename format to dead streams
- **⚰️ Move Dead Channels to Group:** Relocate dead channels
- **🐌 Rename Low Framerate Channels:** Apply rename format to slow streams (<30fps)
- **📁 Move Low Framerate Channels to Group:** Relocate slow channels
- **🎬 Add Video Format Suffix to Channels:** Apply format tags ([4K], [FHD], [HD], [SD])

### Data Export
- **📊 View Results Table:** Detailed tabular format for copy/paste
- **💾 Export Results to CSV:** Save analysis data with comprehensive statistics
- **🗑️ Clear CSV Exports:** Delete all CSV files in /data/exports/

## Channel Management Features

### Dead Channel Management
- **Rename Dead Channels:** Rename dead channels using customizable format string (e.g., "[DEAD] {name}")
- **Move Dead Channels:** Automatically relocate dead channels to the specified group

### Low Framerate Management (<30fps)
- **Rename Low FPS Channels:** Rename low FPS channels using customizable format string (e.g., "{name} [Slow]")
- **Move Low FPS Channels:** Automatically relocate slow channels to the specified group

### Video Format Management
- **Add Format Suffixes:** Add [4K], [FHD], [HD], [SD] tags based on resolution

### Smart Features
- **Flexible Renaming:** Use {name} placeholder in format strings for complete control over channel naming
- **Auto Group Creation:** Creates target groups if they don't exist
- **GUI Refresh:** Automatically updates Dispatcharr interface after changes
- **Confirmation Dialogs:** All destructive operations require explicit confirmation

## Output Data

### Stream Analysis Results
- **Name:** Channel name from Dispatcharr
- **Status:** Alive or Dead
- **Resolution:** Video resolution (e.g., 1920x1080)
- **Format:** Detected format (4K/FHD/HD/SD)
- **Framerate:** Frames per second (rounded to 1 decimal)
- **Error Type:** Categorized failure reason (Timeout, 404 Not Found, 403 Forbidden, 500 Server Error, Connection Refused, Network Unreachable, Invalid Stream, Unsupported Protocol, Stream Unreachable, No Video Stream, Other)
- **Error Details:** Specific failure messages for dead streams

### Quality Detection Rules
- **Low Framerate:** Streams with <30fps
- **Format Detection:**
  - **4K:** 3840x2160+
  - **FHD:** 1920x1080+
  - **HD:** 1280x720+
  - **SD:** Below HD resolution

### CSV Export Enhancements
Each exported CSV includes comprehensive header comments:
- **Metadata:** Generation timestamp and settings used
- **Configuration:** All plugin settings (timeout, retries, rename formats, etc.)
- **Statistics:** Total/alive/dead stream counts with percentages
- **Format Distribution:** Breakdown of video formats among alive streams
- **Performance Metrics:** Average framerate for alive streams
- **Error Analysis:** Distribution of error types among dead streams

## File Locations

- **Results:** `/data/iptv_checker_results.json`
- **Loaded Channels:** `/data/iptv_checker_loaded_channels.json`
- **Progress State:** `/data/iptv_checker_progress.json` *(persists across restarts)*
- **CSV Exports:** `/data/exports/iptv_checker_results_YYYYMMDD_HHMMSS.csv`

## Advanced Features

### Background Processing
- Stream checks run in background threads to prevent browser/request timeouts
- Returns immediately with estimated completion time
- Processing continues even if browser connection is lost
- Check progress anytime using "View Last Results"

### Smart Retry System
- Timeout streams queued and retried after processing other streams (not immediately)
- Provides server recovery time between retry attempts
- Improves success rates for intermittent connection issues
- Retry queue processes every 4 streams to balance throughput and recovery time
- Multiple retry attempts per stream based on configured retry count

### Real-Time ETA Calculation
- ETA calculated dynamically based on actual processing speed
- Updates in real-time as streams are checked
- More accurate than static time estimates
- Accounts for network conditions and stream response times

### Performance Optimizations
- **3-Second Delays:** Added between stream checks for server stability and reliability
- **Accurate Time Estimates:** Based on real-world performance data (~8.5s per stream average)
- **Server-Friendly Processing:** Delays reduce load on IPTV providers
- **Background Threading:** Prevents browser timeouts during long-running checks

## Troubleshooting

### First Step: Restart Container
**For any plugin issues, always try refreshing your browser (F5) and then restarting the Dispatcharr container:**
```bash
docker restart dispatcharr
```

### Common Issues

**"Plugin not found" Errors:**
- Refresh browser page (F5)
- Restart Dispatcharr container
- Check plugin folder structure

**Authentication Errors:**
- Use **✅ Validate Settings** to test configuration
- Verify Dispatcharr URL is accessible from the browser
- Ensure username and password are correct
- Check user has appropriate API access permissions
- Restart container: `docker restart dispatcharr`

**"No Groups Found" Error:**
- Check that channel groups exist in Dispatcharr
- Verify group names are spelled correctly (case-sensitive)
- Use **✅ Validate Settings** to verify group names
- Restart container: `docker restart dispatcharr`

**"No stream check is currently running" Message:**
- This should no longer occur with persistent progress tracking
- If it appears, check if `/data/iptv_checker_progress.json` exists
- Restart container: `docker restart dispatcharr`

**Stream Check Failures:**
- Increase timeout setting for slow streams
- Adjust retry count for unstable connections
- Try enabling parallel mode for better timeout handling
- Check network connectivity from the container
- Restart container: `docker restart dispatcharr`

**Progress Stuck or Not Updating:**
- Stream checking runs in background thread and continues even if browser times out
- Use **📋 View Last Results** to check current status with real-time ETA
- Processing continues independently of browser connection
- Check container logs for actual processing status
- Restart container if truly stuck: `docker restart dispatcharr`

### Debugging Commands

**Check Plugin Status:**
```bash
docker exec dispatcharr ls -la /data/plugins/iptv_checker/
```

**View Progress State:**
```bash
docker exec dispatcharr cat /data/iptv_checker_progress.json
```

**Monitor Plugin Activity:**
```bash
docker logs dispatcharr | grep -i iptv
```

**Test ffprobe Installation:**
```bash
docker exec dispatcharr /usr/local/bin/ffprobe -version
```

**Check Processing Status:**
```bash
docker logs dispatcharr | tail -20
```

## Performance Notes

### Time Estimates
- Based on ~8.5 seconds per stream average with 20% buffer for reliability
- Real-time ETA calculated dynamically based on actual processing speed
- ETA updates as streams are checked to provide accurate completion time
- Accounts for network conditions and individual stream response times

### Processing Behavior
- **Background Processing:** Runs in separate thread to prevent browser timeouts
- **Server-Friendly:** 3-second delays between stream checks for stability
- **Smart Retries:** Timeout streams retried after processing other streams
- **Retry Interval:** Retry queue processes every 4 streams for optimal recovery time

### Recommendations
- Increase timeout setting for slow or unstable streams
- Adjust retry count based on connection reliability
- Monitor progress with "View Last Results" for real-time ETA
- Allow background processing to complete even if browser times out

## Limitations

- Requires valid Dispatcharr authentication
- Limited to ffprobe-supported stream formats
- Channel management operations are permanent (backup recommended)
- Background processing requires sufficient system resources

## Contributing

This plugin integrates deeply with Dispatcharr's API and channel management system. When reporting issues:
1. Include Dispatcharr version information
2. Provide relevant container logs
3. Test with small channel groups first
4. Document specific API error messages and error types
5. Note current progress from **📋 View Last Results** including ETA information
6. Check `/data/iptv_checker_results.json` for completed results
