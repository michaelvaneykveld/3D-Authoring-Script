import os
import subprocess
import shlex
import sys
import shutil
from datetime import datetime

# --- Configuration ---
TEST_DURATION_SEC = 5
TEST_FPS = "24000/1001"
TEST_RESOLUTION = "1920x1080"

LEFT_YUV = "dummy_left.yuv"
RIGHT_YUV = "dummy_right.yuv"
BASE_264 = "test_output_base.264"
DEP_264 = "test_output_dep.264"
STATS_FILE = "x264_stats.log"

def create_dummy_yuvs():
    """Generates two distinct YUV files for testing."""
    print("--- [1/3] Generating dummy YUV test files ---")
    
    # Command for the left eye (standard test pattern)
    ffmpeg_left_cmd = [
        'ffmpeg', '-y', '-f', 'lavfi', '-i', f'testsrc=duration={TEST_DURATION_SEC}:size={TEST_RESOLUTION}:rate={TEST_FPS}',
        '-pix_fmt', 'yuv420p', LEFT_YUV
    ]
    
    # Command for the right eye (a different standard test pattern to ensure difference)
    ffmpeg_right_cmd = [
        'ffmpeg', '-y', '-f', 'lavfi', '-i', f'smptebars=duration={TEST_DURATION_SEC}:size={TEST_RESOLUTION}:rate={TEST_FPS}',
        '-pix_fmt', 'yuv420p', RIGHT_YUV
    ]

    try:
        print(f"  [i] Creating '{LEFT_YUV}'...")
        subprocess.run(ffmpeg_left_cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        print(f"  [i] Creating '{RIGHT_YUV}'...")
        subprocess.run(ffmpeg_right_cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        print("  [✓] Dummy files created successfully.")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"  [✗] FATAL: Failed to create dummy files with ffmpeg: {e}", file=sys.stderr)
        return False

def run_x264_benchmark():
    """Runs a two-pass x264 encoding test to create a compliant 3D stream."""
    print("\n--- [2/3] Running x264 Benchmark ---")

    # Find the exact path to the x264 executable to avoid ambiguity.
    x264_path = shutil.which("x264")
    if not x264_path:
        # This check is already at the top level, but it's good practice
        # to have it close to where the command is used.
        print("  [✗] FATAL: Could not find 'x264' in the system PATH.", file=sys.stderr)
        return
    print(f"  [i] Using x264 executable found at: {x264_path}")

    # --- Common x264 parameters for Blu-ray 3D compliance ---
    x264_common_params = [
        '--bluray-compat', '--level', '4.1', '--preset', 'slow',
        '--crf', '22', '--vbv-maxrate', '40000', '--vbv-bufsize', '30000',
        '--open-gop', '--slices', '4', '--nal-hrd', 'vbr',
        '--sar', '1:1', '--output'
    ]

    try:
        # --- Pass 1: Encode the Base (Left) View ---
        print("\n--- Encoding Base (Left) View ---")
        x264_left_cmd = [x264_path, '--input-res', TEST_RESOLUTION, '--fps', TEST_FPS, '--pass', '1', '--stats', STATS_FILE] + x264_common_params + [BASE_264, LEFT_YUV]
        
        print(f"  [i] Executing command:\n      {shlex.join(x264_left_cmd)}")
        subprocess.run(x264_left_cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        print("  [✓] Pass 1 (Left View) completed.")

        # --- Pass 2: Encode the Dependent (Right) View ---
        print("\n--- Encoding Dependent (Right) View ---")
        x264_right_cmd = [x264_path, '--input-res', TEST_RESOLUTION, '--fps', TEST_FPS, '--pass', '2', '--stats', STATS_FILE, '--stereo-mode', 'right'] + x264_common_params + [DEP_264, RIGHT_YUV]

        print(f"  [i] Executing command:\n      {shlex.join(x264_right_cmd)}")
        subprocess.run(x264_right_cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        print("  [✓] Pass 2 (Right View) completed.")

        # --- Verification ---
        print("\n--- Verifying Output Files ---")
        base_ok = os.path.exists(BASE_264) and os.path.getsize(BASE_264) > 1000
        dep_ok = os.path.exists(DEP_264) and os.path.getsize(DEP_264) > 1000

        if base_ok:
            print(f"  [✓] Base view file '{BASE_264}' created successfully.")
        else:
            print(f"  [✗] FAILURE: Base view file '{BASE_264}' was not created or is empty.")
        
        if dep_ok:
            print(f"  [✓] Dependent view file '{DEP_264}' created successfully.")
        else:
            print(f"  [✗] FAILURE: Dependent view file '{DEP_264}' was not created or is empty.")

        if base_ok and dep_ok:
            print("\n  [✓] SUCCESS: x264 benchmark completed and produced two output streams.")

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"  [✗] FATAL: x264 command failed to execute.", file=sys.stderr)
        if isinstance(e, subprocess.CalledProcessError):
            # Combine stdout and stderr for checking and display
            full_output = (e.stdout or "") + (e.stderr or "")
            print(f"      Exit Code: {e.returncode}", file=sys.stderr)
            print(f"      Output:\n{full_output}", file=sys.stderr)
            # Add a specific, helpful hint for the most common failure mode.
            if "unknown option -- stereo-mode" in full_output:
                print("\n  [!] HINT: This error means your x264 build does not support 3D encoding.", file=sys.stderr)
                print("      Please download and install a feature-complete build (e.g., a 'kMod' version).", file=sys.stderr)

def cleanup_files():
    """Removes all generated test files."""
    print("\n--- [3/3] Cleaning up test files ---")
    files_to_remove = [LEFT_YUV, RIGHT_YUV, BASE_264, DEP_264, STATS_FILE, f"{STATS_FILE}.mbtree"]
    for f in files_to_remove:
        if os.path.exists(f):
            os.remove(f)
            print(f"  [✓] Removed {f}")

if __name__ == "__main__":
    # Verify x264 is in the PATH before starting
    if not shutil.which("x264"):
        print("[✗] FATAL: 'x264' command not found in system PATH.", file=sys.stderr)
        print("      Please install x264 and ensure it is accessible.", file=sys.stderr)
        sys.exit(1)

    if not create_dummy_yuvs():
        sys.exit(1)

    run_x264_benchmark()

    cleanup_files()