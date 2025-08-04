import sys
import subprocess
import os

def process_with_nvenc(source_file, properties, output_dir):
    """
    Asks for encoding quality and then encodes the video to a single MKV file
    containing two perfectly synchronized video streams (left and right eye).
    """
    print("\n--- Starting Step 1: High-Speed NVENC Encoding ---")

    # --- Quality Selection ---
    quality_level = None
    while quality_level is None:
        print("\n--- Select Encoding Quality ---")
        print("NVENC Constant Quality (CQ) determines the output. A lower number means better quality.")
        user_input = input("Enter the desired CQ value and press Enter (default: 22): ")
        if not user_input:
            quality_level = 22
            print(f"  [i] No input, using default value {quality_level}.")
            break
        try:
            value = int(user_input)
            if 0 <= value <= 51:
                quality_level = value
                print(f"  [✓] Quality level set to {quality_level}.")
            else:
                print(f"  [✗] ERROR: The value must be between 0 and 51.", file=sys.stderr)
        except ValueError:
            print("  [✗] ERROR: Invalid input. Please enter a whole number.", file=sys.stderr)

    # --- Build the complex ffmpeg command ---
    output_mkv_path = os.path.join(output_dir, 'video_3d.mkv')

    crop_w, crop_h, crop_y = properties['active_width'], properties['active_height'], properties['top_bar_height']
    eye_w = crop_w // 2
    gop_size = int(round(properties.get('fps_float', 24.0)))

    # This filter graph creates two named outputs: [left] and [right], ensuring they are perfectly synchronized.
    filter_graph = (
        f"crop={crop_w}:{crop_h}:0:{crop_y},"
        f"split[v1][v2];"
        f"[v1]crop={eye_w}:{crop_h}:0:0,pad=1920:1080:-1:-1[left];"
        f"[v2]crop={eye_w}:{crop_h}:{eye_w}:0,pad=1920:1080:-1:-1[right]"
    )

    # Common, strict NVENC settings for both output streams
    nvenc_params = [
        '-c:v', 'h264_nvenc', '-pix_fmt', 'yuv420p',
        '-preset', 'p7', '-rc', 'vbr', '-cq', str(quality_level),
        '-maxrate', '40M', '-bufsize', '30M',
        '-profile:v', 'high', '-level', '4.1', '-g', str(gop_size), '-bf', '3', '-b:v', '0',
        '-b_ref_mode', 'disabled', '-forced-idr', '1', '-aud', '1'
    ]

    # This command maps the two synchronized filter outputs to two video streams in a single MKV file,
    # applying the NVENC parameters to both video streams.
    ffmpeg_cmd = [
        'ffmpeg', '-y', '-i', source_file, '-filter_complex', filter_graph,
        # Map the filter outputs to the video streams
        '-map', '[left]',
        '-map', '[right]',
        # Apply the encoding parameters to all mapped video streams
        *nvenc_params,
        output_mkv_path,
        '-an', '-sn'
    ]

    try:
        print("\n[1/1] Encoding both views into a single, synchronized 3D MKV file...")
        subprocess.run(ffmpeg_cmd, check=True)
    except subprocess.CalledProcessError:
        print(f"\nERROR during encoding.", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"\nERROR: 'ffmpeg' not found. Please ensure it is installed and in your PATH.", file=sys.stderr)
        sys.exit(1)

    print("\n--- 3D MKV encoded successfully! ---")
    print(f"You can find the temporary encoded file in: {output_dir}")
    print("\nEncoding complete. Proceeding to muxing stage...")