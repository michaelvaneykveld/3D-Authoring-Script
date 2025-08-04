import subprocess
import json
import re
import sys

def analyze_video(file_path):
    """
    Analyzes a video file using ffprobe and ffmpeg to determine its properties,
    including 3D format and black bar detection.

    Args:
        file_path (str): The path to the video file.

    Returns:
        dict: A dictionary containing video properties, or None if analysis fails.
    """
    print(f"\n--- Analyzing Video File: {file_path} ---")
    analysis_results = {}

    # 1. Get stream info with ffprobe
    try:
        ffprobe_cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'stream=index,codec_type,codec_name,width,height,display_aspect_ratio,r_frame_rate,nb_frames,tags:format=duration',
            '-of', 'json', file_path
        ]
        print("Running ffprobe to get stream info...")
        result = subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True, encoding='utf-8')
        result_json = json.loads(result.stdout)
        video_info = result_json['streams'][0]
        format_info = result_json.get('format', {})
        
        # Find the first video stream
        video_info = next((s for s in result_json['streams'] if s['codec_type'] == 'video'), None)
        
        analysis_results['total_width'] = video_info.get('width')
        analysis_results['total_height'] = video_info.get('height')

        # Extract and parse frame rate
        fps_string = video_info.get('r_frame_rate', '0/1')
        analysis_results['fps_string'] = fps_string
        try:
            num, den = map(int, fps_string.split('/'))
            analysis_results['fps_float'] = num / den if den > 0 else 0.0
        except (ValueError, ZeroDivisionError):
            analysis_results['fps_float'] = 0.0

        # Extract and parse duration
        duration_str = format_info.get('duration') # Duration is in the 'format' section
        try:
            duration_sec = float(duration_str)
        except (ValueError, TypeError):
            duration_sec = 0.0
        analysis_results['duration_seconds'] = duration_sec
        m, s = divmod(duration_sec, 60)
        h, m = divmod(m, 60)
        analysis_results['duration_formatted'] = f"{int(h):02d}:{int(m):02d}:{int(s):02d}"

        # Extract total frames, with a fallback to calculation
        nb_frames_str = video_info.get('nb_frames', '0')
        if nb_frames_str and nb_frames_str.isdigit() and int(nb_frames_str) > 0:
            analysis_results['total_frames'] = int(nb_frames_str)
            analysis_results['frames_estimated'] = False
        else:
            analysis_results['total_frames'] = int(duration_sec * analysis_results['fps_float'])
            analysis_results['frames_estimated'] = True

        total_frames_display = f"~{analysis_results['total_frames']} (estimated)" if analysis_results['frames_estimated'] else str(analysis_results['total_frames'])
        analysis_results['total_frames_display'] = total_frames_display

        analysis_results['display_aspect_ratio'] = video_info.get('display_aspect_ratio', 'N/A')

        if not all([analysis_results['total_width'], analysis_results['total_height']]):
             print("Error: Could not determine video resolution from ffprobe.")
             return None

    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError, IndexError) as e:
        print(f"Error running ffprobe: {e}", file=sys.stderr)
        print("Please ensure ffprobe is installed and in your PATH.", file=sys.stderr)
        return None

    # 2. Determine 3D SBS type based on storage aspect ratio
    storage_aspect_ratio = analysis_results['total_width'] / analysis_results['total_height']
    # Full SBS is ~3.55:1 (32:9), Half SBS is ~1.77:1 (16:9)
    analysis_results['sbs_type'] = 'Full SBS' if storage_aspect_ratio > 2.5 else 'Half SBS'
    print(f"  [✓] Detected 3D Format: {analysis_results['sbs_type']}")
    print(f"  [✓] Detected Frame Rate: {analysis_results['fps_float']:.3f} FPS ({analysis_results['fps_string']})")
    print(f"  [✓] Detected Duration: {analysis_results['duration_formatted']}")
    print(f"  [✓] Total Frames: {analysis_results['total_frames_display']}")

    # 3. Detect black bars with ffmpeg's cropdetect
    try:
        # Analyze for 10 seconds starting from 25% into the video for better accuracy.
        # If the video is shorter than 20s, just start from the beginning.
        start_time = int(analysis_results['duration_seconds'] * 0.25) if analysis_results['duration_seconds'] > 20 else 0

        ffmpeg_cmd = [
            'ffmpeg', '-ss', str(start_time), '-t', '10', '-i', file_path,
            '-vf', 'cropdetect', '-f', 'null', '-'
        ]
        print("Running ffmpeg cropdetect to find black bars...")
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, encoding='utf-8')

        crop_line = next((line for line in reversed(result.stderr.strip().split('\n')) if 'crop=' in line), None)

        if not crop_line or not (match := re.search(r'crop=(\d+):(\d+):(\d+):(\d+)', crop_line)):
            print("  [!] Could not detect crop information. Assuming no black bars.")
            analysis_results.update({
                'has_black_bars': False, 'active_width': analysis_results['total_width'],
                'active_height': analysis_results['total_height'], 'top_bar_height': 0, 'bottom_bar_height': 0
            })
        else:
            w, h, x, y = [int(v) for v in match.groups()]
            analysis_results.update({
                'active_width': w, 'active_height': h, 'top_bar_height': y,
                'bottom_bar_height': analysis_results['total_height'] - h - y
            })
            analysis_results['has_black_bars'] = analysis_results['top_bar_height'] > 0 or analysis_results['bottom_bar_height'] > 0
            status = "Detected black bars" if analysis_results['has_black_bars'] else "No black bars detected"
            print(f"  [✓] {status}. Active video area: {w}x{h}")

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Warning: Could not run ffmpeg cropdetect: {e}", file=sys.stderr)
        print("Will proceed assuming no black bars.", file=sys.stderr)
        analysis_results.update({
            'has_black_bars': False, 'active_width': analysis_results['total_width'],
            'active_height': analysis_results['total_height'], 'top_bar_height': 0, 'bottom_bar_height': 0
        })

    # 4. Calculate active area aspect ratio
    aw, ah = analysis_results['active_width'], analysis_results['active_height']
    analysis_results['active_area_aspect_ratio'] = f"{aw/ah:.3f}:1" if ah > 0 else "N/A"

    # 5. Extract chapter information
    try:
        ffprobe_cmd_chapters = [
            'ffprobe', '-v', 'error', '-print_format', 'json',
            '-show_chapters', file_path
        ]
        print("Running ffprobe to extract chapter markers...")
        result = subprocess.run(ffprobe_cmd_chapters, capture_output=True, text=True, check=True, encoding='utf-8')
        chapters_json = json.loads(result.stdout)
        chapters = chapters_json.get('chapters', [])

        if chapters:
            # Format timestamps to hh:mm:ss.zzz as required by tsMuxeR
            chapter_times = []
            for chap in chapters:
                start_s = float(chap.get('start_time', 0))
                m, s = divmod(start_s, 60)
                h, m = divmod(m, 60)
                chapter_times.append(f"{int(h):02d}:{int(m):02d}:{s:06.3f}")
            analysis_results['chapters'] = chapter_times
            print(f"  [✓] Found {len(chapters)} chapters.")
        else:
            analysis_results['chapters'] = []
            print("  [i] No chapters found in the source file.")
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"Warning: Could not extract chapters: {e}", file=sys.stderr)
        analysis_results['chapters'] = []

    # 6. Extract audio and subtitle stream information
    audio_streams = []
    subtitle_streams = []
    for stream in result_json.get('streams', []):
        if stream.get('codec_type') == 'audio':
            audio_streams.append({
                'index': stream.get('index'), 'codec': stream.get('codec_name'),
                'lang': stream.get('tags', {}).get('language', 'und'),
            })
        elif stream.get('codec_type') == 'subtitle':
            subtitle_streams.append({
                'index': stream.get('index'), 'codec': stream.get('codec_name'),
                'lang': stream.get('tags', {}).get('language', 'und'),
            })
    analysis_results['audio_streams'] = audio_streams
    analysis_results['subtitle_streams'] = subtitle_streams

    print("--- Analysis Complete ---")
    return analysis_results

if __name__ == '__main__':
    # Example usage for direct testing of this script
    if len(sys.argv) > 1:
        if results := analyze_video(sys.argv[1]):
            print("\n--- FINAL RESULTS ---")
            for key, value in results.items():
                print(f"{key}: {value}")
    else:
        print("Usage: python video_analyzer.py <path_to_video_file>")