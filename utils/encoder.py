import sys
import subprocess
import os
import json
import shutil

def _verify_stream_with_ffprobe(stream_path, eye_name):
    """
    Verifies the encoded stream using ffprobe to check for compliance.
    Returns True on success, False on failure.
    """
    print(f"\n--- Verifying {eye_name} stream ---")
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

def create_3d_video_streams(source_file, properties, output_dir):
    """
    Creates Blu-ray 3D compliant streams by processing the video in chunks
    to keep temporary disk usage low. This uses FRIMEncode to create a true
    AVC+MVC stream, with B-pyramids disabled for compliance.
    """
    print("\n--- Starting Step 1: Creating 3D Video Streams (Chunked FRIM Mode) ---")

    # --- Configuration ---
    CHUNK_SIZE_FRAMES = 300  # Number of frames to process per chunk.

    # --- Define paths ---
    final_base_path = os.path.join(output_dir, 'left_eye.264')
    # The dependent view chunks will be handled by the muxer, not concatenated here.

    # Ensure final output file is empty before we start appending
    if os.path.exists(final_base_path):
        os.remove(final_base_path)

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
    base_concat_list_path = os.path.join(output_dir, 'base_concat_list.txt')

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
        # Dependent chunks are not added to a list for concatenation here.
        try:
            # --- Step 1: Extract YUV chunks with ffmpeg ---
            ffmpeg_cmd_left = [
                'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                '-ss', str(start_time_sec), '-i', source_file,
                '-frames:v', str(frames_in_this_chunk),
                '-vf', f"crop={crop_w}:{crop_h}:0:{crop_y},crop={eye_w}:{crop_h}:0:0,pad=1920:1080:-1:-1,setsar=1",
                '-c:v', 'rawvideo', '-pix_fmt', 'yuv420p', left_chunk_yuv
            ]
            subprocess.run(ffmpeg_cmd_left, check=True)

            ffmpeg_cmd_right = [
                'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                '-ss', str(start_time_sec), '-i', source_file,
                '-frames:v', str(frames_in_this_chunk),
                '-vf', f"crop={crop_w}:{crop_h}:0:{crop_y},crop={eye_w}:{crop_h}:{eye_w}:0,pad=1920:1080:-1:-1,setsar=1",
                '-c:v', 'rawvideo', '-pix_fmt', 'yuv420p', right_chunk_yuv
            ]
            subprocess.run(ffmpeg_cmd_right, check=True)

            # --- Step 2: Encode YUV chunks with FRIM ---
            print(f"  [1/1] Encoding chunk {i+1} with FRIM...")
            frim_cmd = [
                'FRIMEncode64',
                '-i', left_chunk_yuv, right_chunk_yuv,
                '-o:mvc', base_chunk_264, dep_chunk_264,
                '-viewoutput', # CRITICAL: Instructs FRIM to create two separate files
                '-w', '1920', '-h', '1080',
                # Use decimal representation for framerate to ensure consistency
                # between the encoder and the muxer, preventing conflicts.
                '-f', f"{fps_float:.3f}",
                '-sw',
                '-cqp', '22', '22', '22',
                '-profile', 'high',
                '-level', '4.1',
                # Set GOP distance to 1 to disable B-frames entirely. This is a more
                # forceful way to ensure B-pyramids are not used, which is the
                # root cause of the Blu-ray 3D incompatibility.
                '-gop', str(gop_length), '1', '0', 'C',
                # CRITICAL FIX: Disable FRIM's VUI/SEI generation. This creates a "cleaner"
                # stream and prevents framerate conflicts inside tsMuxeR, which will
                # be responsible for injecting its own compliant headers.
                '-VuiNalHrd', 'off',
                '-PicTimingSEI', 'off',
                '-Bpyramid', 'off', # CRITICAL: Disable B-pyramids for Blu-ray 3D compliance
            ]
            subprocess.run(frim_cmd, check=True)

        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"ERROR: Failed during processing of chunk {i+1}: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            # --- Step 4: Clean up temporary chunk files ---
            # Keep the encoded .264 chunks for the next steps.
            for f in [left_chunk_yuv, right_chunk_yuv]:
                if os.path.exists(f):
                    os.remove(f)

    # --- Step 3 (Post-Loop): Concatenate ONLY the base (left eye) chunks ---
    print("\n--- Concatenating all left eye chunks into a final stream ---")
    try:
        with open(base_concat_list_path, 'w') as f:
            for chunk_file in base_chunk_files:
                f.write(f"file '{os.path.basename(chunk_file)}'\n")

        ffmpeg_concat_base_cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'concat', '-safe', '0', '-i', base_concat_list_path,
            '-c', 'copy', final_base_path
        ]
        subprocess.run(ffmpeg_concat_base_cmd, check=True, cwd=output_dir)
        print("  [✓] All left eye chunks concatenated successfully.")
    finally:
        # Clean up the individual encoded chunks and the list file
        # The dependent chunks (_dep.264) are left for the muxer.
        for f in base_chunk_files + [base_concat_list_path]:
            if os.path.exists(f):
                os.remove(f)

    # --- Final Verification ---
    if not _verify_stream_with_ffprobe(final_base_path, "left eye (base view)"):
        print("Aborting due to stream verification failure.", file=sys.stderr)
        sys.exit(1)

    print("\n--- 3D streams created successfully! ---")
    print(f"You can find the final .264 files in: {output_dir}")
    print("\nEncoding complete. Proceeding to muxing stage...")