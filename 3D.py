import subprocess
import sys
import os
import shutil
import re
from utils.file_selector import select_source_file, select_output_directory, select_output_iso, ask_yes_no
from utils.video_analyzer import analyze_video
from utils.track_selector import select_tracks
from utils.encoder import create_3d_video_streams
from utils.muxer import create_bluray_structure
from utils.bdmv_validator import validate_bdmv_structure

def run_dependency_check():
    """
    Runs the dependency check script.
    The program will exit if the check fails or the script is not found.
    """
    checker_script_path = os.path.join(os.path.dirname(__file__), 'utils', 'check_dependencies.py')

    print("--- Running Dependency Check ---")
    try:
        # A simple, direct call is now sufficient. The checker script will print
        # all necessary information and exit with an error if something is wrong.
        subprocess.run(
            [sys.executable, checker_script_path],
            check=True,
            text=True,
            encoding='utf-8'
        )
        print("--- Dependency Check Passed ---\n")
    except FileNotFoundError:
        print(f"ERROR: Dependency check script not found at '{checker_script_path}'")
        sys.exit(1)
    except subprocess.CalledProcessError:
        # The checker script now prints its own detailed error messages.
        # We just need to inform the user that the script is aborting.
        print("\n--- Aborting due to missing dependencies. Please review the messages above. ---")
        sys.exit(1)

def should_skip_encoding(work_dir: str) -> bool:
    """Checks for existing, valid encoded files to determine if encoding can be skipped."""
    left_eye_path = os.path.join(work_dir, 'left_eye.264')
    dep_chunks_exist = False
    if os.path.isdir(work_dir):
        dep_chunks_exist = any(f.startswith('temp_chunk_') and f.endswith('_dep.264') for f in os.listdir(work_dir))

    files_exist_and_are_valid = (
        os.path.exists(left_eye_path) and os.path.getsize(left_eye_path) > 0 and dep_chunks_exist
    )

    if files_exist_and_are_valid:
        print("\n[i] Found existing, valid encoded 3D .264 streams in the temporary directory.")
        use_existing = ask_yes_no(
            title="Existing Files Found",
            message="Pre-encoded 3D .264 streams were found. Do you want to skip the encoding step and use these existing files?"
        )
        if use_existing:
            print("--- Skipping Step 1: Encoding. Using existing files. ---")
            return True
        else:
            print("--- Proceeding with re-encoding as requested. ---")
    elif os.path.exists(left_eye_path) or dep_chunks_exist:
        # This case handles when the file exists but is empty (e.g., from a previously failed run)
        print("\n[!] Found existing but potentially corrupt (empty) encoded files. Forcing re-encoding.")
    
    return False

def main():
    """Main function to run the 3D authoring workflow."""
    run_dependency_check()

    print("--- Source File Selection ---")
    source_file = select_source_file()
    if not source_file:
        print("No source file selected. Aborting script.")
        sys.exit(1)
    print(f"Successfully selected source file: {source_file}")

    video_properties = analyze_video(source_file)
    if not video_properties:
        print("Could not analyze the video file. Aborting.", file=sys.stderr)
        sys.exit(1)

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

    video_properties = select_tracks(video_properties)

    analysis_summary = (
        "The video analysis is complete. Please review the details in the console.\n\n"
        f"A {video_properties['sbs_type']} video will be converted to a Blu-ray 3D structure.\n"
        f"Active video area is {video_properties['active_width']}x{video_properties['active_height']}.\n"
        f"You have selected {len(video_properties.get('audio_streams', []))} audio and {len(video_properties.get('subtitle_streams', []))} subtitle tracks to include.\n\n"
        "Press 'Yes' to continue with encoding and muxing, or 'No' to abort."
    )
    if not ask_yes_no(title="Confirm Analysis", message=analysis_summary):
        print("Aborting script as requested by user.")
        sys.exit(0)
    print("Confirmation received. Continuing with the process...")

    # --- Step 1: Encoding ---
    print("\nA dialog will now open to select a TEMPORARY working directory...")
    work_dir = select_output_directory()
    if not work_dir:
        print("No working directory selected. Aborting.")
        sys.exit(1)
    print(f"Temporary files will be saved to: {work_dir}")

    # Use a try...finally block to ensure cleanup is always offered
    try:
        if not should_skip_encoding(work_dir):
            create_3d_video_streams(source_file, video_properties, work_dir)

        # --- Step 2: Muxing ---
        print("\nA dialog will now open to select the PARENT directory for the final output (e.g., 'Downloads' or 'Movies')...")
        parent_output_dir = select_output_directory(title="Select Parent Directory for Final Blu-ray")
        if not parent_output_dir:
            print("No parent directory selected. Aborting.")
            # We still want to offer cleanup, so we don't exit here.
            # The finally block will execute.
            return

        # Get a name for the project to create a dedicated subfolder, preventing permission errors.
        base_name = os.path.splitext(os.path.basename(source_file))[0]
        # Sanitize the base_name to be a valid folder name.
        # Replace spaces with underscores and remove other invalid characters.
        sanitized_base_name = re.sub(r'[\\/*?:"<>| ]', "_", base_name)
        project_name = input(f"Enter a name for the Blu-ray output folder (press Enter to use '{sanitized_base_name}'): ").strip()
        if not project_name:
            project_name = sanitized_base_name

        output_bdmv_path = os.path.join(parent_output_dir, project_name)
        print(f"Final Blu-ray folder will be created at: {output_bdmv_path}")

        create_bluray_structure(video_properties, source_file, work_dir, output_bdmv_path)

        # --- Step 3: Post-Mux Validation ---
        print("\n--- Starting Post-Mux Validation ---")
        validation_passed = validate_bdmv_structure(output_bdmv_path)

        if validation_passed:
            print("\n--- Validation Successful ---")
            print(f"The Blu-ray 3D folder structure at:\n{output_bdmv_path}\nappears to be valid and compliant.")
        else:
            print("\n--- Validation Failed ---")
            print("The generated Blu-ray structure has issues. Please review the validation log above.")

    except Exception as e:
        print(f"\n--- An unexpected error occurred: {e} ---", file=sys.stderr)
        print("The script will now proceed to the cleanup step.", file=sys.stderr)

    finally:
        # This block will run whether the try block succeeded or failed.
        # --- Final Cleanup Step ---
        if work_dir and os.path.exists(work_dir):
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

if __name__ == "__main__":
    main()