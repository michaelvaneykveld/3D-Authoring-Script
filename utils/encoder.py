import sys
import subprocess
import os
import json
from datetime import datetime
import shlex
import hashlib
import shutil

def _verify_stream_with_ffprobe(stream_path, eye_name, is_dependent_view=False):
    """
    Verifies the encoded stream.
    For the base (AVC) view, it uses ffprobe for a full compliance check.
    For the dependent (MVC) view, it only checks for existence and size,
    as ffprobe cannot correctly parse raw MVC streams.
    Returns True on success, False on failure.
    """
    print(f"\n--- Verifying {eye_name} stream ---")

    if not os.path.exists(stream_path) or os.path.getsize(stream_path) == 0:
        print(f"  [✗] ERROR: Stream file '{os.path.basename(stream_path)}' does not exist or is empty.", file=sys.stderr)
        return False

    # For the dependent MVC stream, a simple existence and size check is sufficient and correct.
    # ffprobe cannot correctly parse raw MVC streams, so a full check would always fail.
    if is_dependent_view:
        print(f"  [✓] Verification successful for: {os.path.basename(stream_path)}")
        print("    - Note:           Full compliance check is skipped as ffprobe cannot parse raw MVC streams.")
        print("    - Verification:   File exists and is not empty.")
        return True

    try:
        # Use subprocess.run which is designed for this "run and wait" pattern
        # and accepts the capture_output, text, and check arguments.
        result = subprocess.run(
            [
                'ffprobe', '-v', 'error',
                '-show_streams',
                '-of', 'json',
                stream_path
            ],
            capture_output=True, text=True, check=True, encoding='utf-8'
        )
        stream_info = json.loads(result.stdout).get('streams', [{}])[0]
        
        print(f"  [✓] Verification successful for: {os.path.basename(stream_path)}")
        
        level_val = stream_info.get('level', 0)
        level_str = f"{level_val / 10.0:.1f}" if isinstance(level_val, int) else str(level_val)

        print(f"    - Codec:          {stream_info.get('codec_name', 'N/A')}")
        print(f"    - Profile:        {stream_info.get('profile', 'N/A')}")
        print(f"    - Level:          {level_str}")
        print(f"    - Resolution:     {stream_info.get('width', 'N/A')}x{stream_info.get('height', 'N/A')}")
        print(f"    - SAR:            {stream_info.get('sample_aspect_ratio', 'N/A')}")
        print(f"    - Pixel Format:   {stream_info.get('pix_fmt', 'N/A')}")
        print(f"    - Ref Frames:     {stream_info.get('refs', 'N/A')}")
        has_b_frames = stream_info.get('has_b_frames', -1)
        b_frame_status = 'No' if has_b_frames == 0 else 'Yes' if has_b_frames > 0 else 'Unknown'
        print(f"    - B-Frames Used:  {b_frame_status}")
        
        is_compliant = True
        if stream_info.get('profile') != 'High':
            print("    [✗] FAILURE: Profile is not 'High'.")
            is_compliant = False
        if level_val != 41:
            print("    [✗] FAILURE: Level is not 4.1 (41).")
            is_compliant = False
        if stream_info.get('sample_aspect_ratio') != '1:1':
            print("    [✗] FAILURE: SAR is not '1:1'.")
            is_compliant = False
        if stream_info.get('pix_fmt') != 'yuv420p':
            print("    [✗] FAILURE: Pixel format is not 'yuv420p'.")
            is_compliant = False
        if int(stream_info.get('refs', 99)) > 4:
            print(f"    [✗] FAILURE: Reference frames ({stream_info.get('refs')}) > 4. This is not Blu-ray compliant.")
            is_compliant = False
        if has_b_frames != 0:
            print("    [✗] FAILURE: B-frames detected. This is the likely cause of B-pyramid issues and is not allowed for our strict compliance.")
            is_compliant = False

        if not is_compliant:
            print("\n  [✗] CRITICAL: Stream is not Blu-ray 3D compliant based on the analysis above.")
            return False
        else:
            print("\n  [✓] Stream passes all Blu-ray 3D compliance checks.")
            return True

    except subprocess.CalledProcessError as e:
        print(f"  [✗] ERROR: ffprobe verification failed for {os.path.basename(stream_path)}.", file=sys.stderr)
        print(f"      ffprobe output:\n{e.stderr or e.stdout}", file=sys.stderr)
        return False

def _concatenate_chunks(chunk_files, final_output_path):
    """Helper to concatenate .264 chunk files using a simple binary copy, which is more robust than ffmpeg's concat demuxer for raw streams."""
    try:
        with open(final_output_path, 'wb') as outfile:
            for chunk_file in chunk_files:
                with open(chunk_file, 'rb') as infile:
                    shutil.copyfileobj(infile, outfile)
        print(f"  [✓] All chunks concatenated successfully into {os.path.basename(final_output_path)}.")
    finally:
        # Clean up the individual chunks
        for f in chunk_files:
            if os.path.exists(f):
                os.remove(f)

def _contains_mvc_nal_units(path):
    """
    Scans a binary file for the presence of MVC-specific NAL unit headers.
    This is a strong indicator that the stream is a proper MVC-encoded 3D stream.
    """
    print("\n--- Verifying for MVC NAL units in combined stream ---")
    try:
        with open(path, 'rb') as f:
            data = f.read()
        # MVC streams use specific NAL unit types: 15 (subset SPS) and 20 (coded slice extension).
        # We search for the byte sequences for these NAL units.
        # Start code + NAL unit type 15: 00 00 01 0F
        # Start code + NAL unit type 20: 00 00 01 14
        if b'\x00\x00\x01\x0f' in data or b'\x00\x00\x01\x14' in data:
            print("  [✓] SUCCESS: MVC-specific NAL units found in the stream.")
            return True
        else:
            print("  [✗] FAILURE: No MVC-specific NAL units (type 15 or 20) found.", file=sys.stderr)
            print("      The stream is likely not a compliant stereoscopic 3D stream.", file=sys.stderr)
            return False
    except IOError as e:
        print(f"  [✗] ERROR: Could not read file to check for NAL units: {e}", file=sys.stderr)
        return False

def _verify_yuv_difference(left_yuv_path, right_yuv_path):
    """
    Verifies that the two YUV files are not identical by comparing their hashes.
    This prevents FRIMEncode from failing to create an MVC stream with identical inputs.
    """
    print("\n--- Verifying difference between Left and Right YUV chunks ---")
    try:
        hasher_left = hashlib.sha256()
        hasher_right = hashlib.sha256()

        with open(left_yuv_path, 'rb') as f_left:
            buf = f_left.read(65536)
            while len(buf) > 0:
                hasher_left.update(buf)
                buf = f_left.read(65536)
        
        with open(right_yuv_path, 'rb') as f_right:
            buf = f_right.read(65536)
            while len(buf) > 0:
                hasher_right.update(buf)
                buf = f_right.read(65536)

        if hasher_left.hexdigest() == hasher_right.hexdigest():
            print("  [✗] FATAL: Left and Right YUV chunks are identical.", file=sys.stderr)
            print("      This will cause FRIMEncode to fail creating a 3D stream. Check source video.", file=sys.stderr)
            return False
        else:
            print("  [✓] SUCCESS: Left and Right YUV chunks are different.")
            return True
    except IOError as e:
        print(f"  [✗] ERROR: Could not read YUV files for verification: {e}", file=sys.stderr)
        return False

def create_3d_video_streams(source_file, properties, output_dir):
    """
    Creates Blu-ray 3D compliant streams by processing the video in chunks
    to keep temporary disk usage low. This uses FRIMEncode to create a true
    AVC+MVC stream, with B-pyramids disabled for compliance.
    """
    print("\n--- Starting Step 1: Creating 3D Video Streams (Chunked FRIM Mode) ---")

    # --- Configuration ---
    CHUNK_SIZE_FRAMES = 300  # Number of frames to process per chunk.

    # --- Define log path for this process ---
    encoder_log_path = os.path.join(output_dir, 'encoder_process.log')

    # --- Get properties ---
    total_frames = properties.get('total_frames')
    if not total_frames or total_frames < 1:
        print("ERROR: Could not determine total number of frames. Aborting chunked encoding.", file=sys.stderr)
        sys.exit(1)

    fps_float = properties.get('fps_float', 23.976)
    fps_string = properties.get('fps_string', '24000/1001')
    crop_w, crop_h, crop_y = properties['active_width'], properties['active_height'], properties['top_bar_height']
    eye_w = crop_w // 2
    gop_length = int(round(fps_float))

    # --- Main processing loop ---
    num_chunks = (total_frames + CHUNK_SIZE_FRAMES - 1) // CHUNK_SIZE_FRAMES
    base_chunk_files = []
    combined_chunk_files = []

    # Initialize the log file for this encoding session
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(encoder_log_path, 'w', encoding='utf-8') as log:
        log.write(f"--- Encoder Process Log ({timestamp}) ---\n")
        log.write(f"Source: {source_file}\n")
        log.write(f"Properties: {json.dumps(properties, indent=2)}\n")

    for i in range(num_chunks):
        start_frame = i * CHUNK_SIZE_FRAMES
        frames_in_this_chunk = min(CHUNK_SIZE_FRAMES, total_frames - start_frame)
        start_time_sec = start_frame / fps_float

        print(f"\n--- Processing Chunk {i+1}/{num_chunks} (Frames {start_frame}-{start_frame + frames_in_this_chunk - 1}) ---")

        # Define temporary file paths for this specific chunk
        left_chunk_yuv = os.path.join(output_dir, f'temp_chunk_{i}_left.yuv')
        right_chunk_yuv = os.path.join(output_dir, f'temp_chunk_{i}_right.yuv')
        combined_chunk_264 = os.path.join(output_dir, f'temp_chunk_{i}_combined.264')
        combined_chunk_files.append(combined_chunk_264)
        try:
            # --- Step 1: Extract YUV chunks with ffmpeg ---
            ffmpeg_cmd_left = [
                'ffmpeg', '-y', '-hide_banner', '-loglevel', 'info',
                '-ss', str(start_time_sec), '-i', source_file,
                '-frames:v', str(frames_in_this_chunk),
                '-vf', f"crop={crop_w}:{crop_h}:0:{crop_y},crop={eye_w}:{crop_h}:0:0,pad=1920:1080:-1:-1,setsar=1",
                '-c:v', 'rawvideo', '-pix_fmt', 'yuv420p', left_chunk_yuv
            ]
            with open(encoder_log_path, 'a', encoding='utf-8') as log:
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                command_str = shlex.join(ffmpeg_cmd_left)
                log.write(f"\n--- Chunk {i+1}/{num_chunks} - Extracting Left YUV ({timestamp}) ---\n")
                log.write(f"COMMAND: {command_str}\n\n")
                subprocess.run(ffmpeg_cmd_left, check=True, stdout=log, stderr=subprocess.STDOUT)

            ffmpeg_cmd_right = [
                'ffmpeg', '-y', '-hide_banner', '-loglevel', 'info',
                '-ss', str(start_time_sec), '-i', source_file,
                '-frames:v', str(frames_in_this_chunk),
                '-vf', f"crop={crop_w}:{crop_h}:0:{crop_y},crop={eye_w}:{crop_h}:{eye_w}:0,pad=1920:1080:-1:-1,setsar=1",
                '-c:v', 'rawvideo', '-pix_fmt', 'yuv420p', right_chunk_yuv
            ]
            with open(encoder_log_path, 'a', encoding='utf-8') as log:
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                command_str = shlex.join(ffmpeg_cmd_right)
                log.write(f"\n--- Chunk {i+1}/{num_chunks} - Extracting Right YUV ({timestamp}) ---\n")
                log.write(f"COMMAND: {command_str}\n\n")
                subprocess.run(ffmpeg_cmd_right, check=True, stdout=log, stderr=subprocess.STDOUT)

            # --- Verify YUV difference ---
            if not _verify_yuv_difference(left_chunk_yuv, right_chunk_yuv):
                raise IOError("YUV chunk verification failed: Left and Right views are identical.")

            # --- Step 2: Encode YUV chunks with FRIM ---
            print(f"  [1/1] Encoding chunk {i+1} with FRIM...")
            frim_cmd = [
                'FRIMEncode64',
                '-i', left_chunk_yuv, right_chunk_yuv,
                '-o:mvc', combined_chunk_264, # A single output file containing both views
                '-w', '1920', '-h', '1080', 
                # Use decimal representation for framerate to ensure consistency
                # between the encoder and the muxer, preventing conflicts.
                '-f', f"{fps_float:.3f}",
                '-sw',
                '-cqp', '22', '22', '22',
                '-profile', 'high',
                '-level', '4.1',
                # Let FRIMEncode handle the VUI and SEI timing information.
                # This is often more stable than letting tsMuxeR inject it later,
                # preventing the DTS timing jump errors.
                '-VuiNalHrd', 'on',
                '-PicTimingSEI', 'on',
                '-Bpyramid', 'off', # CRITICAL: Disable B-pyramids for Blu-ray 3D compliance
            ]
            frim_output = ""
            with open(encoder_log_path, 'a', encoding='utf-8') as log:
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                command_str = shlex.join(frim_cmd)
                log.write(f"\n--- Chunk {i+1}/{num_chunks} - Encoding with FRIM ({timestamp}) ---\n")
                log.write(f"COMMAND: {command_str}\n\n")
                # Capture output to check for MVC mode, while also logging it
                process = subprocess.run(frim_cmd, check=True, capture_output=True, text=True, encoding='utf-8')
                log.write(process.stdout)
                log.write(process.stderr)
                frim_output = process.stdout + process.stderr
            
            # --- Check for warnings and dropped frames in FRIM output ---
            warnings = [line for line in frim_output.splitlines() if "WARNING:" in line]
            if warnings:
                print("  [!] WARNINGS found in FRIMEncode output:")
                for warning in warnings:
                    print(f"      - {warning.strip()}")

            frame_issues = [line for line in frim_output.splitlines() if "dropped frame" in line or "duplicate frame" in line]
            if frame_issues:
                print("  [!] Dropped/Duplicate frames reported by FRIMEncode:")
                for issue in frame_issues:
                    print(f"      - {issue.strip()}")

            if "Encoder MVC" not in frim_output:
                print("  [✗] FATAL: FRIMEncode did not report entering MVC mode. The output is not 3D.", file=sys.stderr)
                raise IOError("FRIMEncode failed to create an MVC stream.")

            # --- Verify chunk creation ---
            if not os.path.exists(combined_chunk_264) or os.path.getsize(combined_chunk_264) == 0:
                print(f"  [✗] FATAL: FRIMEncode failed to create a valid output chunk for chunk {i+1}.", file=sys.stderr)
                print(f"      Expected file: {combined_chunk_264}", file=sys.stderr)
                raise IOError("FRIMEncode chunk creation failed.")

        except (subprocess.CalledProcessError, FileNotFoundError, IOError) as e:
            # Provide a more specific error message for non-zero exit codes
            if isinstance(e, subprocess.CalledProcessError):
                print(f"ERROR: A critical error occurred during encoding (exit code {e.returncode}).", file=sys.stderr)
            else:
                print(f"ERROR: Failed during processing of chunk {i+1}: {e}", file=sys.stderr)
            print(f"      Check the detailed encoder log for the full output: {encoder_log_path}", file=sys.stderr)
            sys.exit(1)
        finally:
            # --- Step 4: Clean up temporary chunk files ---
            # Keep the encoded .264 chunks for the next steps.
            for f in [left_chunk_yuv, right_chunk_yuv]:
                if os.path.exists(f):
                    os.remove(f)
    
    # --- Step 3 (Post-Loop): Concatenate chunks into final streams ---
    print("\n--- Concatenating all chunks into a final combined 3D stream ---")
    final_combined_path = os.path.join(output_dir, 'video_3d.264')
    _concatenate_chunks(combined_chunk_files, final_combined_path)

    # --- Final Verification ---
    # A critical check to ensure the encoder actually produced an MVC stream.
    if not _contains_mvc_nal_units(final_combined_path):
        print("Aborting due to MVC NAL unit verification failure.", file=sys.stderr)
        sys.exit(1)

    # The most reliable verification for the combined stream is tsMuxeR itself.
    # We will simply verify the base view properties within the combined stream.
    if not _verify_stream_with_ffprobe(final_combined_path, "combined 3D stream (base view properties)"):
        print("Aborting due to stream verification failure.", file=sys.stderr)
        sys.exit(1)

    print("\n--- 3D streams created successfully! ---")
    print(f"You can find the final combined .264 file in: {output_dir}")
    print("\nEncoding complete. Proceeding to muxing stage...")