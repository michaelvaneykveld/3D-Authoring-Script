import os
import subprocess
import json
import sys

def _check_file_structure(bdmv_root_path):
    """Checks for the existence of mandatory Blu-ray 3D files and folders."""
    print("\n--- [1/4] Verifying BDMV file structure ---")
    all_ok = True

    required_paths = [
        ("BDMV/index.bdmv", os.path.isfile),
        ("BDMV/MovieObject.bdmv", os.path.isfile),
        ("BDMV/CLIPINF/00000.clpi", os.path.isfile),
        ("BDMV/PLAYLIST/00000.mpls", os.path.isfile),
        ("BDMV/STREAM/00000.m2ts", os.path.isfile),
        ("CERTIFICATE", os.path.isdir),
        ("BDMV/BACKUP/index.bdmv", os.path.isfile),
        ("BDMV/BACKUP/MovieObject.bdmv", os.path.isfile),
        ("BDMV/BACKUP/CLIPINF/00000.clpi", os.path.isfile),
        ("BDMV/BACKUP/PLAYLIST/00000.mpls", os.path.isfile),
    ]

    for rel_path, check_func in required_paths:
        full_path = os.path.join(bdmv_root_path, *rel_path.split('/'))
        if check_func(full_path):
            print(f"  [✓] Found: {rel_path}")
        else:
            print(f"  [✗] MISSING: {rel_path}")
            all_ok = False
    
    return all_ok

def _check_m2ts_stream(m2ts_path, properties):
    """Uses ffprobe to verify the properties of the main M2TS video stream."""
    print("\n--- [2/4] Verifying M2TS video stream properties ---")
    if not os.path.exists(m2ts_path):
        print(f"  [✗] CRITICAL: Main stream file not found at {m2ts_path}")
        return False

    try:
        ffprobe_cmd = [
            'ffprobe', '-v', 'error', '-show_streams', '-of', 'json', m2ts_path
        ]
        result = subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True, encoding='utf-8')
        streams = json.loads(result.stdout).get('streams', [])
        
        video_streams = [s for s in streams if s.get('codec_type') == 'video']

        all_ok = True
        video_info = None

        # A valid 3D Blu-ray stream will be reported by ffprobe as either:
        # 1. A single stream with a "Stereo High" profile.
        # 2. Two separate video streams (one AVC base, one MVC dependent).
        if len(video_streams) == 1:
            video_info = video_streams[0]
            profile = video_info.get('profile', '')
            if profile == 'Stereo High':
                print(f"  [✓] Found a single video stream with 'Stereo High' profile (Correct for 3D).")
            else:
                print(f"  [!] WARNING: Found 1 video stream, but its profile is '{profile}', not 'Stereo High'. This might be incorrect.")
                all_ok = False
        elif len(video_streams) == 2:
            print(f"  [✓] Found two video streams (Base + Dependent View) (Correct for 3D).")
            video_info = video_streams[0] # Validate the base view
        else:
            print(f"  [✗] FAILURE: Expected 1 or 2 video streams, but found {len(video_streams)}.")
            return False

        # Check codec and profile
        codec = video_info.get('codec_name', '')
        if codec == 'h264':
            print(f"  [✓] Base view codec is correct: H.264")
        else:
            print(f"  [✗] FAILURE: Codec is '{codec}', not 'h264'.")
            all_ok = False

        # Check frame rate
        expected_fps = properties.get('fps_string', '24000/1001')
        fps = video_info.get('r_frame_rate', '')
        if fps == expected_fps:
            print(f"  [✓] Frame rate is correct: {fps}")
        else:
            print(f"  [✗] FAILURE: Frame rate is '{fps}', expected '{expected_fps}'.")
            all_ok = False

        return all_ok

    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"  [✗] ERROR: Could not run ffprobe to verify M2TS stream: {e}", file=sys.stderr)
        return False

def _check_timing_jumps(m2ts_path, properties):
    """Uses ffprobe to detect significant jumps in DTS timestamps."""
    print("\n--- [3/4] Verifying stream timing for jumps/errors ---")
    if not os.path.exists(m2ts_path):
        print(f"  [✗] CRITICAL: Main stream file not found at {m2ts_path}")
        return False

    try:
        # This command is designed to be fast and output only DTS timestamps
        ffprobe_cmd = [
            'ffprobe', '-hide_banner', '-select_streams', 'v:0',
            '-show_frames', '-show_entries', 'frame=pkt_dts_time',
            '-of', 'compact=p=0:nk=1', m2ts_path
        ]
        result = subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True, encoding='utf-8')

        lines = result.stdout.strip().split('\n')
        timestamps = [float(t) for t in lines if t and t != 'N/A']
        
        if len(timestamps) < 2:
            print("  [!] WARNING: Not enough frames to analyze timing.")
            return True

        fps_float = properties.get('fps_float')
        if not fps_float or fps_float == 0:
            print("  [!] WARNING: Could not determine expected FPS for timing check. Skipping.")
            return True # Don't fail the validation if we can't check

        expected_delta = 1 / fps_float
        # Allow a 5% tolerance for floating point inaccuracies
        tolerance = expected_delta * 0.10 # Use a 10% tolerance to be more forgiving
        
        jumps_found = 0
        for i in range(1, len(timestamps)):
            delta = timestamps[i] - timestamps[i-1]
            if abs(delta - expected_delta) > tolerance:
                # The line below is commented out to prevent flooding the console. We only show the final count.
                # print(f"  [!] JUMP DETECTED at frame {i}: DTS changed from {timestamps[i-1]:.4f} to {timestamps[i]:.4f} (delta: {delta:.4f}s, expected: {expected_delta:.4f}s)")
                jumps_found += 1

        if jumps_found == 0:
            print(f"  [✓] No significant timing jumps detected across {len(timestamps)} frames.")
            return True
        else:
            print(f"  [✗] FAILURE: Found {jumps_found} timing jump(s). The stream may be corrupt.")
            return False

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"  [✗] ERROR: Could not run ffprobe to check for timing jumps: {e}", file=sys.stderr)
        return False

def _check_mpls_file(mpls_path):
    """Checks the MPLS file header for the correct magic number."""
    print("\n--- [4/5] Verifying MPLS playlist file ---")
    if not os.path.exists(mpls_path):
        print(f"  [✗] CRITICAL: MPLS file not found at {mpls_path}")
        return False
    
    try:
        with open(mpls_path, 'rb') as f:
            magic = f.read(4)
            if magic == b'MPLS':
                version = f.read(4).decode(errors='ignore')
                print(f"  [✓] MPLS file header is valid (Magic: 'MPLS', Version: {version}).")
                return True
            else:
                print(f"  [✗] FAILURE: Invalid MPLS file header. Expected 'MPLS', but found {magic!r}.")
                return False
    except IOError as e:
        print(f"  [✗] ERROR: Could not read MPLS file: {e}", file=sys.stderr)
        return False

def _check_frame_count(m2ts_path, expected_frames):
    """Uses ffprobe to count the frames in the final M2TS stream."""
    print("\n--- [5/5] Verifying total frame count ---")
    if not os.path.exists(m2ts_path):
        print(f"  [✗] CRITICAL: Main stream file not found at {m2ts_path}")
        return False

    try:
        ffprobe_cmd = [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-count_frames', '-show_entries', 'stream=nb_read_frames',
            '-of', 'default=noprint_wrappers=1:nokey=1', m2ts_path
        ]
        result = subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True, encoding='utf-8')
        actual_frames = int(result.stdout.strip())

        # Allow a small tolerance (e.g., 2 frames) for minor discrepancies
        if abs(actual_frames - expected_frames) <= 2:
            print(f"  [✓] Frame count is correct (Expected: {expected_frames}, Found: {actual_frames}).")
            return True
        else:
            print(f"  [✗] FAILURE: Frame count mismatch (Expected: {expected_frames}, Found: {actual_frames}).")
            return False

    except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
        print(f"  [✗] ERROR: Could not run ffprobe to count frames: {e}", file=sys.stderr)
        return False

def validate_bdmv_structure(bdmv_root_path, properties):
    """
    Runs a series of checks to validate the generated Blu-ray folder structure.

    Args:
        bdmv_root_path (str): The path to the root folder containing the BDMV directory.

    Returns:
        bool: True if all critical checks pass, False otherwise.
    """
    if not os.path.isdir(bdmv_root_path):
        print(f"ERROR: Validation failed. Output path '{bdmv_root_path}' is not a valid directory.", file=sys.stderr)
        return False

    m2ts_path = os.path.join(bdmv_root_path, "BDMV", "STREAM", "00000.m2ts")
    mpls_path = os.path.join(bdmv_root_path, "BDMV", "PLAYLIST", "00000.mpls")
    expected_frames = properties.get('total_frames', 0)

    # Run all checks and collect results
    structure_ok = _check_file_structure(bdmv_root_path)
    stream_ok = _check_m2ts_stream(m2ts_path, properties)
    timing_ok = _check_timing_jumps(m2ts_path, properties)
    mpls_ok = _check_mpls_file(mpls_path)
    frames_ok = _check_frame_count(m2ts_path, expected_frames)

    return structure_ok and stream_ok and timing_ok and mpls_ok and frames_ok