import sys
import subprocess
import os
import json
from datetime import datetime
import shlex
import hashlib
from bitstring import ConstBitStream
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

def _verify_sps_pps_presence(path):
    """
    Uses ffprobe to verify that the stream contains both SPS and PPS NAL units,
    which are essential for decodability.
    """
    print("\n--- Verifying presence of SPS/PPS NAL units using ffprobe ---")
    try:
        # This command will output packet information, including NAL unit types.
        ffprobe_cmd = [
            'ffprobe', '-v', 'error', '-show_packets',
            '-select_streams', 'v:0', path
        ]
        result = subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True, encoding='utf-8')
        
        output_text = result.stdout

        # Check if the output contains lines indicating SPS (type 7) and PPS (type 8) NAL units.
        sps_found = "nal_unit_type=7" in output_text
        pps_found = "nal_unit_type=8" in output_text

        if sps_found and pps_found:
            print("  [✓] SUCCESS: Both SPS and PPS NAL units were found in the stream.")
            return True
        else:
            if not sps_found:
                print("  [✗] FAILURE: SPS (Sequence Parameter Set) NAL unit not found.", file=sys.stderr)
            if not pps_found:
                print("  [✗] FAILURE: PPS (Picture Parameter Set) NAL unit not found.", file=sys.stderr)
            print("      The stream may be incomplete or corrupt.", file=sys.stderr)
            return False

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"  [✗] ERROR: Could not run ffprobe to check for NAL units: {e}", file=sys.stderr)
        if isinstance(e, subprocess.CalledProcessError):
            print(f"      ffprobe stderr: {e.stderr}", file=sys.stderr)
        return False

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

def _verify_plausible_bitrate(file_path, properties):
    """
    Performs a sanity check on the final stream's average bitrate.
    A very low bitrate can indicate that the MVC dependent view was not encoded.
    """
    print("\n--- Verifying plausible bitrate of final stream ---")
    try:
        file_size_bytes = os.path.getsize(file_path)
        duration_sec = properties.get('duration_seconds')

        if not duration_sec or duration_sec == 0:
            print("  [!] WARNING: Could not determine video duration. Skipping bitrate check.")
            return True

        bitrate_mbps = (file_size_bytes * 8) / (duration_sec * 1_000_000)
        
        # A typical 3D Blu-ray stream should have a healthy bitrate.
        # A very low value (e.g., < 15 Mbps) for a CQP 22 encode is suspicious
        # and may indicate that only the base view was encoded.
        MIN_BITRATE_MBPS = 15.0

        print(f"  [i] Calculated average bitrate: {bitrate_mbps:.2f} Mbps")

        if bitrate_mbps < MIN_BITRATE_MBPS:
            print(f"  [!] WARNING: Average bitrate is below {MIN_BITRATE_MBPS} Mbps. This might indicate an issue with the 3D encode.")
        else:
            print("  [✓] Bitrate seems plausible for a 3D Blu-ray stream.")
        return True
    except (IOError, KeyError) as e:
        print(f"  [✗] ERROR: Could not perform bitrate verification: {e}", file=sys.stderr)
        return False

def _verify_sei_nal_units(path):
    """
    Scans the stream for SEI NAL units to confirm timing info is present.
    This is a strong indicator that VuiNalHrd and PicTimingSEI were enabled.
    """
    print("\n--- Verifying for SEI NAL units in combined stream ---")
    try:
        stream = ConstBitStream(filename=path)
        
        # Find all NAL start codes (0x000001)
        nal_unit_starts = stream.findall('0x000001', bytealigned=True)
        
        sei_units_found = 0
        for start_pos in nal_unit_starts:
            # Position the stream right after the start code
            stream.pos = start_pos + 24 # 24 bits for the start code
            
            # Read the NAL header (1 byte)
            if stream.pos + 8 > stream.len:
                continue # Not enough data
            
            nal_header = stream.read(8)
            # forbidden_zero_bit (1), nal_ref_idc (2), nal_unit_type (5)
            nal_unit_type = nal_header.uint & 0x1F
            
            if nal_unit_type == 6: # SEI (Supplemental enhancement information)
                sei_units_found += 1
        
        if sei_units_found > 0:
            print(f"  [✓] SUCCESS: Found {sei_units_found} SEI NAL units in the stream.")
            return True
        else:
            print("  [!] WARNING: No SEI NAL units found. The stream may lack timing information needed for muxing.")
            return True # Non-fatal warning

    except Exception as e: # Catch potential bitstring errors or file errors
        print(f"  [✗] ERROR: Could not perform SEI NAL unit check: {e}", file=sys.stderr)
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
    base_chunk_files = [] # For the left eye (AVC)
    dep_chunk_files = []  # For the right eye (MVC)

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
        base_chunk_264 = os.path.join(output_dir, f'temp_chunk_{i}_base.264')
        dep_chunk_264 = os.path.join(output_dir, f'temp_chunk_{i}_dep.264')
        base_chunk_files.append(base_chunk_264)
        dep_chunk_files.append(dep_chunk_264)
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
                '-o:mvc', base_chunk_264, dep_chunk_264,
                '-viewoutput', # Explicitly create separate files for base and dependent views
                '-w', '1920', '-h', '1080', 
                # Use decimal representation for framerate to ensure consistency
                # between the encoder and the muxer, preventing conflicts.
                '-f', f"{fps_float:.3f}",
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

            # --- Verify chunk creation ---
            if not os.path.exists(base_chunk_264) or os.path.getsize(base_chunk_264) == 0:
                print(f"  [✗] FATAL: FRIMEncode failed to create a valid output chunk for chunk {i+1}.", file=sys.stderr)
                print(f"      Expected file: {base_chunk_264}", file=sys.stderr)
                raise IOError("FRIMEncode chunk creation failed.")
            if not os.path.exists(dep_chunk_264) or os.path.getsize(dep_chunk_264) == 0:
                print(f"  [✗] FATAL: FRIMEncode failed to create a valid dependent view chunk for chunk {i+1}.", file=sys.stderr)
                print(f"      Expected file: {dep_chunk_264}", file=sys.stderr)
                raise IOError("FRIMEncode dependent view chunk creation failed.")

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
    print("\n--- Concatenating all chunks into final base and dependent streams ---")
    final_base_path = os.path.join(output_dir, 'left_eye.264')
    _concatenate_chunks(base_chunk_files, final_base_path)
    final_dep_path = os.path.join(output_dir, 'right_eye.264')
    _concatenate_chunks(dep_chunk_files, final_dep_path)

    # --- Final Verification ---
    # Verify that the essential SPS and PPS NAL units are present.
    if not _verify_sps_pps_presence(final_base_path):
        print("Aborting due to missing essential NAL units (SPS/PPS).", file=sys.stderr)
        sys.exit(1)

    # A critical check to ensure the encoder actually produced an MVC stream.
    if not _contains_mvc_nal_units(final_dep_path):
        print("Aborting due to MVC NAL unit verification failure.", file=sys.stderr)
        sys.exit(1)

    # Perform a bitrate sanity check as a heuristic for output size.
    if not _verify_plausible_bitrate(final_base_path, properties):
        # This is not a fatal error, but we should note it.
        print("  [!] Bitrate verification step failed to execute.", file=sys.stderr)

    # Check for SEI NAL units as an indicator of timing information
    if not _verify_sei_nal_units(final_base_path):
        # This is not a fatal error, but we should note it.
        print("  [!] SEI NAL unit verification step failed to execute.", file=sys.stderr)

    # Verify the base view stream with ffprobe and do a simple existence check on the dependent view.
    if not _verify_stream_with_ffprobe(final_base_path, "left eye (base view)"):
        print("Aborting due to stream verification failure.", file=sys.stderr)
        sys.exit(1)
    _verify_stream_with_ffprobe(final_dep_path, "right eye (dependent view)", is_dependent_view=True)

    print("\n--- 3D streams created successfully! ---")
    print(f"You can find the final .264 files in: {output_dir}")
    print("\nEncoding complete. Proceeding to muxing stage...")