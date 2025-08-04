import subprocess
import sys
import os
import shutil
from utils.file_selector import select_source_file, select_output_directory, select_output_iso, ask_yes_no
from utils.video_analyzer import analyze_video
from utils.track_selector import select_tracks
from utils.encoder import process_with_nvenc
from utils.muxer import create_bluray_structure

def run_dependency_check():
    """
    Runs the dependency check script.
    The program will exit if the check fails or the script is not found.
    """
    checker_script_path = os.path.join(os.path.dirname(__file__), 'utils', 'check_dependencies.py')

    print("--- Running Dependency Check ---")
    try:
        # Run the checker script using the same Python interpreter.
        # 'check=True' will raise a CalledProcessError if the script returns a non-zero exit code.
        subprocess.run([sys.executable, checker_script_path], check=True)
        print("--- Dependency Check Passed ---\n")
    except FileNotFoundError:
        print(f"ERROR: Dependency check script not found at '{checker_script_path}'")
        sys.exit(1)
    except subprocess.CalledProcessError:
        print("\n--- Dependency Check Failed. Aborting execution. ---")
        sys.exit(1)

# --- Main application logic starts here ---
run_dependency_check()

print("--- Source File Selection ---")
# The function will prompt the user via the dialog
source_file = select_source_file()

# If no file is selected (dialog is canceled), exit the program.
if not source_file:
    print("No source file selected. Aborting.")
    sys.exit(1)

print(f"Successfully selected source file: {source_file}")

# Analyze the selected video file
video_properties = analyze_video(source_file)

if not video_properties:
    print("Could not analyze the video file. Aborting.", file=sys.stderr)
    sys.exit(1)

# Display the results
print("\n--- Video Properties Summary ---")
print(f"  {'Resolution (full frame):':<28}{video_properties['total_width']}x{video_properties['total_height']}")
if video_properties['has_black_bars']:
    print(f"  {'Resolution (active video):':<28}{video_properties['active_width']}x{video_properties['active_height']}")
    print(f"  {'Black Bars:':<28}Top={video_properties['top_bar_height']}px, Bottom={video_properties['bottom_bar_height']}px")
else:
    print(f"  {'Black Bars:':<28}Not detected")
print(f"  {'Detected 3D Format:':<28}{video_properties['sbs_type']}")
print(f"  {'Frame Rate:':<28}{video_properties.get('fps_float', 0.0):.3f} FPS ({video_properties.get('fps_string', 'N/A')})")
print(f"  {'Duration:':<28}{video_properties.get('duration_formatted', 'N/A')}")
print(f"  {'Total Frames:':<28}{video_properties.get('total_frames_display', 'N/A')}")
print(f"  {'Active Area Aspect Ratio:':<28}{video_properties['active_area_aspect_ratio']}")
print(f"  {'Audio Streams Found:':<28}{len(video_properties.get('audio_streams', []))}")
print(f"  {'Subtitle Streams Found:':<28}{len(video_properties.get('subtitle_streams', []))}")

# --- Optional Track Selection ---
# Allow the user to select which tracks to keep
video_properties = select_tracks(video_properties)

# --- User Confirmation Step ---
analysis_summary = (
    "The video analysis is complete. Please review the details in the console.\n\n"
    f"A {video_properties['sbs_type']} video will be converted to a Blu-ray 3D structure.\n"
    f"Active video area is {video_properties['active_width']}x{video_properties['active_height']}.\n"
    f"You have selected {len(video_properties.get('audio_streams', []))} audio and {len(video_properties.get('subtitle_streams', []))} subtitle tracks to include.\n\n"
    "Press 'Yes' to continue or 'No' to abort."
)

confirmed = ask_yes_no(
    title="Confirm Analysis",
    message=analysis_summary
)
if not confirmed:
    print("Aborting as requested by user.")
    sys.exit(0)
else:
    print("Confirmation received. Continuing with the process...")

# --- Step 1: Encoding ---

# Ask for a temporary working directory
print("\nA dialog will now open to select a TEMPORARY working directory for encoded files...")
work_dir = select_output_directory()
if not work_dir:
    print("No working directory selected. Aborting.")
    sys.exit(1)
print(f"Temporary files will be saved to: {work_dir}")

# --- Check for existing encoded files to potentially skip encoding ---
video_3d_mkv_path = os.path.join(work_dir, 'video_3d.mkv')
skip_encoding = False
files_exist_and_are_valid = (
    os.path.exists(video_3d_mkv_path) and os.path.getsize(video_3d_mkv_path) > 0
)

if files_exist_and_are_valid:
    print("\n[i] Found existing, valid encoded 3D MKV stream in the temporary directory.")
    use_existing = ask_yes_no(
        title="Existing Files Found",
        message="Found a pre-encoded 3D MKV stream. Do you want to skip the encoding step and use this file?"
    )
    if use_existing:
        print("--- Skipping Step 1: Encoding. Using existing files. ---")
        skip_encoding = True
    else:
        print("--- Proceeding with re-encoding as requested. ---")
elif os.path.exists(video_3d_mkv_path):
    # This case handles when files exist but are empty (e.g., from a failed run)
    print("\n[!] Found existing but potentially corrupt (empty) encoded files. Forcing re-encoding.")

if not skip_encoding:
    # Run the encoder
    process_with_nvenc(source_file, video_properties, work_dir)

# --- Step 2: Muxing ---

# Ask for final output ISO path
print("\nA dialog will now open to select the FINAL output location and name for the Blu-ray ISO file...")
output_iso_path = select_output_iso()
if not output_iso_path:
    print("No output file selected. Aborting.")
    sys.exit(1)
print(f"Final Blu-ray ISO will be saved as: {output_iso_path}")

# Run the muxer
create_bluray_structure(video_properties, source_file, work_dir, output_iso_path)

print("\n--- Process Complete! ---")
print(f"The Blu-ray 3D ISO has been successfully created at:\n{output_iso_path}")

# --- Final Cleanup Step ---
cleanup = ask_yes_no(
    title="Cleanup Temporary Files?",
    message=f"The process is complete. Do you want to delete the temporary working directory?\n\nDirectory: {work_dir}"
)

if cleanup:
    try:
        shutil.rmtree(work_dir)
        print(f"\nSuccessfully removed temporary directory: {work_dir}")
    except OSError as e:
        print(f"\nError removing temporary directory: {e}", file=sys.stderr)
        print("You may need to remove it manually.")