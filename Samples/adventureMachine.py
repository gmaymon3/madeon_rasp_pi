import os
import subprocess
import threading
import time
import readchar  # Captures instant keypresses safely across threads

# Configuration
FIFO_PATH = "/tmp/audio_stream.wav"
next_input = None
input_lock = threading.Lock()

def list_files(wav_files):
    print("\n🎵 Available WAV files:")
    # We restrict mapping to keys 1-9 for instant single-keypress mapping
    max_display = min(len(wav_files), 9)
    for idx in range(max_display):
        print(f"    [{idx + 1}] {wav_files[idx]}")
    print("-" * 55)
    print("🎹 INSTRUCTIONS: Just press keys [1-9] directly on your keyboard.")
    print("   No Enter key needed! Press 'q' to exit safely.")
    print("-" * 55)

def input_thread_func(wav_files):
    global next_input
    max_selectable = min(len(wav_files), 9)
    
    while True:
        try:
            # Instantly reads a single keypress without waiting for Enter
            key = readchar.readkey()
            
            if key.lower() == 'q':
                print("\n👋 Quit signal received. Exiting...")
                os._exit(0) # Immediate clean exit for all threads
                
            if key.isdigit():
                num = int(key)
                idx = num - 1
                
                if 0 <= idx < max_selectable:
                    with input_lock:
                        next_input = wav_files[idx]
                    print(f"\n⏳ Queued: [{num}] {wav_files[idx]} (Will shift on next loop finish)")
                else:
                    print(f"\n❌ Choice [{num}] is out of bounds.")
        except (KeyboardInterrupt, EOFError):
            break

def main():
    global next_input
    
    # 1. Gather and sort WAV files
    wav_files = sorted([f for f in os.listdir('.') if f.lower().endswith('.wav')])
    if not wav_files:
        print("❌ No .wav files found in the current directory.")
        return

    list_files(wav_files)
    
    # 2. Setup initial files cleanly before launching player
    while True:
        try:
            selection = input("Select initial TWO files to loop (e.g., 1 3): ").split()
            if len(selection) == 2:
                idx1 = int(selection[0]) - 1
                idx2 = int(selection[1]) - 1
                if 0 <= idx1 < len(wav_files) and 0 <= idx2 < len(wav_files):
                    file1 = wav_files[idx1]
                    file2 = wav_files[idx2]
                    break
            print(f"❌ Enter two space-separated numbers between 1 and {len(wav_files)}.")
        except ValueError:
            print("❌ Invalid entry. Use numbers only.")

    # 3. Clean and prepare FIFO pipe
    if os.path.exists(FIFO_PATH):
        os.remove(FIFO_PATH)
    os.mkfifo(FIFO_PATH)

    # 4. Fire up background persistent FFmpeg audio channel
    ffmpeg_playback = subprocess.Popen(
        ["ffmpeg", "-re", "-i", FIFO_PATH, "-f", "alsa", "default", "-loglevel", "quiet"],
        stdin=subprocess.PIPE
    )

    # 5. Start the non-blocking single-key listener thread
    input_thread = threading.Thread(target=input_thread_func, args=(wav_files,), daemon=True)
    input_thread.start()

    print(f"\n▶️ Playing live mix loop: '{file1}' + '{file2}'")
    
    try:
        with open(FIFO_PATH, "wb") as fifo:
            while ffmpeg_playback.poll() is None:
                mix_cmd = [
                    "ffmpeg", "-y",
                    "-i", file1, "-i", file2,
                    "-filter_complex", "amix=inputs=2:duration=longest",
                    "-f", "wav", "-"
                ]
                
                mixer_proc = subprocess.Popen(mix_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                
                while True:
                    data = mixer_proc.stdout.read(4096)
                    if not data:
                        break
                    try:
                        fifo.write(data)
                        fifo.flush()
                    except BrokenPipeError:
                        break
                
                mixer_proc.wait()

                # Shift logic on loop completion boundary
                with input_lock:
                    if next_input is not None:
                        file2 = file1
                        file1 = next_input
                        next_input = None
                        print(f"\n🔄 [Queue Shifted] Now looping: '{file1}' + '{file2}'")

    except KeyboardInterrupt:
        print("\n👋 Exiting and cleaning up...")
    finally:
        if ffmpeg_playback.poll() is None:
            ffmpeg_playback.terminate()
            ffmpeg_playback.wait()
        if os.path.exists(FIFO_PATH):
            os.remove(FIFO_PATH)

if __name__ == "__main__":
    main()
