import subprocess
import time
import typing

from just_ff import FFmpegCommandBuilder, FFmpegQueueRunner, FFmpegJob


# from your_module import FFmpegQueueRunner # If defined in a separate file

# --- Define Callbacks ---
def handle_job_start(idx, job: FFmpegJob):
    print(f"\n[QUEUE] Job {idx} START: ID='{job.job_id}', Context='{job.context}'")
    print(f"  Command: {job.builder.build()}")


def handle_job_progress(idx, job: FFmpegJob, percent: float):
    # Basic progress bar
    bar_length = 20
    filled_length = int(round(bar_length * percent / 100))
    bar = '█' * filled_length + '-' * (bar_length - filled_length)
    print(f"\r[QUEUE] Job {idx} PROGRESS: [{bar}] {percent:.1f}% ({job.job_id})", end="")
    if percent == 100.0:
        print()  # Newline after 100%


def handle_job_process_created(idx, job: FFmpegJob, process: subprocess.Popen):
    print(f"\n[QUEUE] Job {idx} PID: {process.pid} ({job.job_id})")


def handle_job_complete(idx, job: FFmpegJob):
    print(f"\n[QUEUE] Job {idx} COMPLETE: ID='{job.job_id}', Status='{job.status}'")
    if job.status == "failed":
        print(f"  Error: {job.result}")
        # print(f"  Stderr: {job.result.stderr if hasattr(job.result, 'stderr') else 'N/A'}")


def handle_queue_start(runner: FFmpegQueueRunner):
    print("\n[QUEUE] === QUEUE PROCESSING STARTED ===")


def handle_queue_complete(runner: FFmpegQueueRunner, processed_jobs: typing.List[FFmpegJob]):
    print("\n[QUEUE] === QUEUE PROCESSING FINISHED ===")
    success_count = 0
    failed_count = 0
    cancelled_count = 0
    for job in processed_jobs:
        if job.status == "completed":
            success_count += 1
        elif job.status == "failed":
            failed_count += 1
        elif job.status == "cancelled":
            cancelled_count += 1
    print(f"Summary: {success_count} Succeeded, {failed_count} Failed, {cancelled_count} Cancelled.")


# --- Main Execution ---
if __name__ == "__main__":
    queue_runner = FFmpegQueueRunner(
        on_job_start=handle_job_start,
        on_job_progress=handle_job_progress,
        on_job_process_created=handle_job_process_created,
        on_job_complete=handle_job_complete,
        on_queue_start=handle_queue_start,
        on_queue_complete=handle_queue_complete,
    )

    # Job 1: Success (e.g., create a short color video)
    builder1 = FFmpegCommandBuilder(overwrite=True)
    builder1.add_output("output_job1_blue.mp4")
    builder1.add_filter_complex("color=c=blue:s=128x72:d=2[out]")  # 2 seconds
    builder1.map_stream("[out]", "v:0").set_codec("v:0", "libx264")
    queue_runner.add_job(builder1, duration_sec=2.0, job_id="BlueVideo", context="Test Video 1")

    # Job 2: Failure (e.g., invalid option or codec)
    builder2 = FFmpegCommandBuilder(overwrite=True)
    builder2.add_output("output_job2_fail.mp4")
    builder2.add_input("non_existent_input.mp4")  # This will fail ffprobe/ffmpeg
    builder2.map_stream("0:v", "v:0")  # Map will fail if input fails
    queue_runner.add_job(builder2, duration_sec=1.0, job_id="FailingJob", context="Test Failure")

    # Job 3: Success (another short video)
    builder3 = FFmpegCommandBuilder(overwrite=True)
    builder3.add_output("output_job3_green.mp4")
    builder3.add_filter_complex("color=c=green:s=128x72:d=3[out]")  # 3 seconds
    builder3.map_stream("[out]", "v:0").set_codec("v:0", "libx264")
    queue_runner.add_job(builder3, duration_sec=3.0, job_id="GreenVideo", context="Test Video 2")

    # Job 4: To be cancelled (long duration)
    builder4 = FFmpegCommandBuilder(overwrite=True)
    builder4.add_output("output_job4_red_long.mp4")
    builder4.add_filter_complex("color=c=red:s=128x72:d=60[out]")  # 60 seconds
    builder4.map_stream("[out]", "v:0").set_codec("v:0", "libx264").add_output_option("-preset", "ultrafast")
    queue_runner.add_job(builder4, duration_sec=60.0, job_id="LongRedVideo", context="Test Cancellation")

    # --- Scenario 1: Run with stop_on_error=True ---
    print("\n--- Running queue with stop_on_error=True ---")
    # queue_runner.run_queue(stop_on_error=True)

    # --- Scenario 2: Run with stop_on_error=False ---
    # print("\n--- Running queue with stop_on_error=False ---")
    # Re-add jobs if they were consumed in previous run
    # queue_runner.clear_pending_jobs() # Clear if any left from a cancelled run
    # ... (re-add jobs if needed or use a fresh runner instance)
    # queue_runner.run_queue(stop_on_error=False)

    # --- Scenario 3: Test Cancellation ---
    # This needs to run the queue in a thread to allow main thread to call cancel
    import threading


    def run_queue_in_thread(runner):
        runner.run_queue(stop_on_error=False)  # Let it try to run all


    print("\n--- Running queue with cancellation test ---")
    # Ensure jobs are in the queue (they are if Scenarios 1&2 were commented out)

    queue_thread = threading.Thread(target=run_queue_in_thread, args=(queue_runner,))
    queue_thread.start()

    # Wait for a bit, then try to cancel
    time.sleep(1.0)  # Let the first job (BlueVideo) likely complete or be near completion
    print(
        "\n>>> Main Thread: Requesting cancel of current job (should be FailingJob or GreenVideo if Blue finished fast)")
    # queue_runner.cancel_current_job()

    time.sleep(4.0)  # Let GreenVideo run a bit (if it started)
    if queue_runner.is_running and queue_runner.active_job and queue_runner.active_job.job_id == "LongRedVideo":
        print("\n>>> Main Thread: LongRedVideo is active. Requesting cancel of current job (LongRedVideo).")
        queue_runner.cancel_current_job()

    time.sleep(1.0)  # Give it a moment to process cancellation for LongRedVideo
    if queue_runner.is_running:
        print("\n>>> Main Thread: Queue still seems to be running. Requesting cancel of entire queue.")
        queue_runner.cancel_queue()

    queue_thread.join(timeout=70)  # Wait for queue thread to finish (max 70s)
    if queue_thread.is_alive():
        print("Error: Queue thread did not finish in time.")

    print("\nFinal processed jobs report:")
    for job_report in queue_runner.get_processed_jobs():
        print(f"  - {job_report.job_id}: {job_report.status} "
              f"(Result/Error: {str(job_report.result)[:100]}{'...' if len(str(job_report.result)) > 100 else ''})")
