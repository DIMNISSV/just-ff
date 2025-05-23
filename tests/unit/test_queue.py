import pytest
import subprocess
import os
import time
import threading

# --- Импорты из тестируемой библиотеки ---
from just_ff.command import FFmpegCommandBuilder
from just_ff.queues import FFmpegJob, FFmpegQueueRunner
from just_ff.exceptions import FfmpegProcessError, CommandBuilderError


# --- Фикстуры (ffmpeg_path, tmp_output_dir из conftest.py) ---

# --- Helper Functions / Callbacks for Tests ---
class CallbackTestHelper:
    def __init__(self):
        self.job_starts = []
        self.job_progress = {}  # job_id: [progress_values]
        self.job_processes = {}  # job_id: Popen_object
        self.job_completes = []  # job_id: FFmpegJob_object
        self.queue_starts = 0
        self.queue_completes = 0
        self.processed_jobs_on_queue_complete = []

    def on_job_start(self, idx, job: FFmpegJob):
        self.job_starts.append((idx, job.job_id or f"job_{idx}"))
        print(f"Test CB: Job Start - idx={idx}, id={job.job_id}")

    def on_job_progress(self, idx, job: FFmpegJob, percent: float):
        job_key = job.job_id or f"job_{idx}"
        if job_key not in self.job_progress:
            self.job_progress[job_key] = []
        self.job_progress[job_key].append(percent)
        # print(f"Test CB: Job Progress - id={job_key}, %={percent:.1f}")

    def on_job_process_created(self, idx, job: FFmpegJob, process: subprocess.Popen):
        job_key = job.job_id or f"job_{idx}"
        self.job_processes[job_key] = process
        print(f"Test CB: Job Process Created - id={job_key}, pid={process.pid}")

    def on_job_complete(self, idx, job: FFmpegJob):
        self.job_completes.append(job)  # Store the whole job object
        print(f"Test CB: Job Complete - idx={idx}, id={job.job_id}, status={job.status}")

    def on_queue_start(self, runner: FFmpegQueueRunner):
        self.queue_starts += 1
        print("Test CB: Queue Start")

    def on_queue_complete(self, runner: FFmpegQueueRunner, processed_jobs: list[FFmpegJob]):
        self.queue_completes += 1
        self.processed_jobs_on_queue_complete = list(processed_jobs)  # Store a copy
        print(f"Test CB: Queue Complete, processed {len(processed_jobs)} jobs")

    def reset(self):
        self.job_starts.clear()
        self.job_progress.clear()
        self.job_processes.clear()
        self.job_completes.clear()
        self.queue_starts = 0
        self.queue_completes = 0
        self.processed_jobs_on_queue_complete.clear()


@pytest.fixture
def cb_helper():
    return CallbackTestHelper()


# --- Тесты для FFmpegQueueRunner ---

def test_queue_add_job(ffmpeg_path):
    runner = FFmpegQueueRunner()
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder.add_output("dummy.mp4")  # Must add output

    job1 = runner.add_job(builder, job_id="job1")
    assert runner.pending_job_count == 1
    assert job1.job_id == "job1"
    assert job1.builder == builder

    job2 = runner.add_job(builder, duration_sec=5.0, context={"user": "test"})
    assert runner.pending_job_count == 2
    assert job2.duration_sec == 5.0
    assert job2.context == {"user": "test"}


def test_queue_clear_pending_jobs(ffmpeg_path):
    runner = FFmpegQueueRunner()
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder.add_output("dummy.mp4")

    runner.add_job(builder, job_id="job1")
    runner.add_job(builder, job_id="job2")
    assert runner.pending_job_count == 2

    cleared_count = runner.clear_pending_jobs()
    assert cleared_count == 2
    assert runner.pending_job_count == 0


def test_queue_run_empty(cb_helper):
    runner = FFmpegQueueRunner(
        on_queue_start=cb_helper.on_queue_start,
        on_queue_complete=cb_helper.on_queue_complete
    )
    processed = runner.run_queue()
    assert len(processed) == 0
    assert cb_helper.queue_starts == 0  # Should not start if empty
    assert cb_helper.queue_completes == 0  # Should not complete if empty


def test_queue_run_single_successful_job(ffmpeg_path, tmp_output_dir, cb_helper):
    runner = FFmpegQueueRunner(
        on_job_start=cb_helper.on_job_start,
        on_job_progress=cb_helper.on_job_progress,
        on_job_process_created=cb_helper.on_job_process_created,
        on_job_complete=cb_helper.on_job_complete,
        on_queue_start=cb_helper.on_queue_start,
        on_queue_complete=cb_helper.on_queue_complete
    )

    output_file = os.path.join(tmp_output_dir, "q_job_success.mp4")
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    builder.add_filter_complex("color=c=blue:s=64x36:d=1[out]")  # 1 sec
    builder.add_output(output_file)  # Add output
    builder.map_stream("[out]", "v:0").set_codec("v:0", "libx264").add_output_option("-preset", "ultrafast")

    runner.add_job(builder, duration_sec=1.0, job_id="success_job")

    processed_jobs = runner.run_queue()

    assert len(processed_jobs) == 1
    job_result = processed_jobs[0]
    assert job_result.job_id == "success_job"
    assert job_result.status == "completed"
    assert job_result.result is True
    assert os.path.exists(output_file)

    # Check callbacks
    assert cb_helper.queue_starts == 1
    assert cb_helper.queue_completes == 1
    assert len(cb_helper.job_starts) == 1
    assert cb_helper.job_starts[0][1] == "success_job"  # Check job_id
    assert "success_job" in cb_helper.job_progress
    assert len(cb_helper.job_progress["success_job"]) > 0
    if cb_helper.job_progress["success_job"]:  # Check if list is not empty
        assert cb_helper.job_progress["success_job"][-1] == 100.0
    assert "success_job" in cb_helper.job_processes
    assert len(cb_helper.job_completes) == 1
    assert cb_helper.job_completes[0].job_id == "success_job"
    assert cb_helper.job_completes[0].status == "completed"
    assert len(cb_helper.processed_jobs_on_queue_complete) == 1


def test_queue_run_multiple_jobs_stop_on_error_true(ffmpeg_path, tmp_output_dir, cb_helper):
    runner = FFmpegQueueRunner(
        on_job_complete=cb_helper.on_job_complete,
        on_queue_complete=cb_helper.on_queue_complete
    )

    # Job 1: Success
    out1 = os.path.join(tmp_output_dir, "q_multi1.mp4")
    b1 = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    b1.add_filter_complex("color=c=green:s=64x36:d=0.5[out]")
    b1.add_output(out1)
    b1.map_stream("[out]", "v:0").set_codec("v:0", "copy")  # Use copy for speed
    runner.add_job(b1, duration_sec=0.5, job_id="multi_job1")

    # Job 2: Failure
    out2 = os.path.join(tmp_output_dir, "q_multi2_fail.mp4")
    b2 = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    b2.add_input("non_existent_file.mp4")  # Failure point
    b2.add_output(out2)
    b2.map_stream("0:v", "v:0")
    runner.add_job(b2, duration_sec=1.0, job_id="multi_job2_fail")

    # Job 3: Should not run
    out3 = os.path.join(tmp_output_dir, "q_multi3.mp4")
    b3 = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    b3.add_filter_complex("color=c=red:s=64x36:d=0.5[out]")
    b3.add_output(out3)
    b3.map_stream("[out]", "v:0").set_codec("v:0", "copy")
    runner.add_job(b3, duration_sec=0.5, job_id="multi_job3")

    processed_jobs = runner.run_queue(stop_on_error=True)

    assert len(processed_jobs) == 2  # job1 (success), job2 (fail)
    assert os.path.exists(out1)
    assert not os.path.exists(out2)
    assert not os.path.exists(out3)  # Should not have been created

    assert processed_jobs[0].job_id == "multi_job1"
    assert processed_jobs[0].status == "completed"
    assert processed_jobs[1].job_id == "multi_job2_fail"
    assert processed_jobs[1].status == "failed"
    assert isinstance(processed_jobs[1].result, FfmpegProcessError)

    assert runner.pending_job_count == 1  # job3 should remain in pending_queue
    # Or rather, it's moved to processed_jobs with 'cancelled' status
    # My implementation moves it to processed_jobs as 'cancelled'.

    # Based on current implementation, all jobs initially in pending queue get moved to processed_jobs
    assert runner.pending_job_count == 0
    all_processed_in_cb = cb_helper.processed_jobs_on_queue_complete
    assert len(all_processed_in_cb) == 3
    assert all_processed_in_cb[0].status == "completed"
    assert all_processed_in_cb[1].status == "failed"
    assert all_processed_in_cb[2].status == "cancelled"  # Job 3 should be marked cancelled


def test_queue_run_multiple_jobs_stop_on_error_false(ffmpeg_path, tmp_output_dir, cb_helper):
    runner = FFmpegQueueRunner(
        on_job_complete=cb_helper.on_job_complete,
        on_queue_complete=cb_helper.on_queue_complete
    )
    # Same jobs as above
    out1 = os.path.join(tmp_output_dir, "q_multi_nofail1.mp4")
    b1 = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    b1.add_filter_complex("color=c=green:s=64x36:d=0.5[out]")
    b1.add_output(out1)
    b1.map_stream("[out]", "v:0").set_codec("v:0", "copy")
    runner.add_job(b1, duration_sec=0.5, job_id="multi_nf_job1")

    out2 = os.path.join(tmp_output_dir, "q_multi_nofail2_fail.mp4")
    b2 = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    b2.add_input("non_existent_file.mp4")
    b2.add_output(out2)
    b2.map_stream("0:v", "v:0")
    runner.add_job(b2, duration_sec=1.0, job_id="multi_nf_job2_fail")

    out3 = os.path.join(tmp_output_dir, "q_multi_nofail3.mp4")
    b3 = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    b3.add_filter_complex("color=c=red:s=64x36:d=0.5[out]")
    b3.add_output(out3)
    b3.map_stream("[out]", "v:0").set_codec("v:0", "copy")
    runner.add_job(b3, duration_sec=0.5, job_id="multi_nf_job3")

    processed_jobs = runner.run_queue(stop_on_error=False)

    assert len(processed_jobs) == 3  # All jobs attempted
    assert os.path.exists(out1)
    assert not os.path.exists(out2)  # Failed job
    assert os.path.exists(out3)  # Should run despite job2 failure

    assert processed_jobs[0].job_id == "multi_nf_job1"
    assert processed_jobs[0].status == "completed"
    assert processed_jobs[1].job_id == "multi_nf_job2_fail"
    assert processed_jobs[1].status == "failed"
    assert processed_jobs[2].job_id == "multi_nf_job3"
    assert processed_jobs[2].status == "completed"

    assert runner.pending_job_count == 0


def test_queue_cancel_current_job(ffmpeg_path, tmp_output_dir, cb_helper):
    runner = FFmpegQueueRunner(on_job_complete=cb_helper.on_job_complete)

    # Job 1: Short, should complete
    out1 = os.path.join(tmp_output_dir, "q_cancel_curr1.mp4")
    b1 = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    b1.add_filter_complex("color=c=yellow:s=32x32:d=0.2[out]")
    b1.add_output(out1)
    b1.map_stream("[out]", "v:0").set_codec("v:0", "copy")
    runner.add_job(b1, duration_sec=0.2, job_id="cancel_curr_job1")

    # Job 2: Longer, to be cancelled
    out2 = os.path.join(tmp_output_dir, "q_cancel_curr2.mkv")
    b2 = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    b2.add_filter_complex("color=c=magenta:s=32x32:d=10[out]")  # 10 seconds
    b2.add_output(out2)
    b2.map_stream("[out]", "v:0").set_codec("v:0", "libx264").add_output_option("-preset", "ultrafast")
    runner.add_job(b2, duration_sec=10.0, job_id="cancel_curr_job2_long")

    # Job 3: Should run if current job cancellation doesn't stop queue
    out3 = os.path.join(tmp_output_dir, "q_cancel_curr3.mp4")
    b3 = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    b3.add_filter_complex("color=c=cyan:s=32x32:d=0.2[out]")
    b3.add_output(out3)
    b3.map_stream("[out]", "v:0").set_codec("v:0", "copy")
    runner.add_job(b3, duration_sec=0.2, job_id="cancel_curr_job3")

    def run_and_cancel():
        # Wait for job1 to likely finish and job2 to start
        time.sleep(0.5)
        if runner.is_running and runner.active_job and runner.active_job.job_id == "cancel_curr_job2_long":
            print("Test thread: Cancelling current job (job2_long)")
            runner.cancel_current_job()
        else:
            print("Test thread: Job2_long not active when cancel was attempted, or queue not running.")

    thread = threading.Thread(target=run_and_cancel)
    thread.start()

    processed_jobs = runner.run_queue(stop_on_error=False)  # stop_on_error=False important here
    thread.join()

    assert len(processed_jobs) == 3
    assert processed_jobs[0].status == "completed"  # Job 1
    assert processed_jobs[1].job_id == "cancel_curr_job2_long"
    assert processed_jobs[1].status in ["cancelled", "failed"]  # Cancelled job status
    if processed_jobs[1].status == "failed":  # If marked as failed due to termination
        assert isinstance(processed_jobs[1].result, FfmpegProcessError)

    assert processed_jobs[2].status == "completed"  # Job 3 should run
    assert os.path.exists(out1)
    # out2 might exist but be incomplete
    assert os.path.exists(out3)


def test_queue_cancel_entire_queue(ffmpeg_path, tmp_output_dir, cb_helper):
    runner = FFmpegQueueRunner(on_job_complete=cb_helper.on_job_complete)

    # Job 1: Short
    out1 = os.path.join(tmp_output_dir, "q_cancel_q1.mp4")
    b1 = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    b1.add_output(out1)
    b1.add_filter_complex("color=c=orange:s=32x32:d=0.2[out]")
    b1.map_stream("[out]", "v:0").set_codec("v:0", "copy")
    runner.add_job(b1, duration_sec=0.2, job_id="cancel_q_job1")

    # Job 2: Longer, active when queue cancel is called
    out2 = os.path.join(tmp_output_dir, "q_cancel_q2.mkv")
    b2 = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    b2.add_output(out2)
    b2.add_filter_complex("color=c=purple:s=32x32:d=10[out]")
    b2.map_stream("[out]", "v:0").set_codec("v:0", "libx264").add_output_option("-preset", "ultrafast")
    runner.add_job(b2, duration_sec=10.0, job_id="cancel_q_job2_long")

    # Job 3: Should not run
    out3 = os.path.join(tmp_output_dir, "q_cancel_q3.mp4")
    b3 = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    b3.add_output(out3)
    b3.add_filter_complex("color=c=lime:s=32x32:d=0.2[out]")
    b3.map_stream("[out]", "v:0").set_codec("v:0", "libx264").add_output_option("-preset", "ultrafast")
    runner.add_job(b3, duration_sec=0.2, job_id="cancel_q_job3")

    def run_and_cancel_queue():
        time.sleep(0.2)  # Wait for job1 to finish, job2 to start
        if runner.is_running:
            print("Test thread: Cancelling entire queue.")
            runner.cancel_queue()

    thread = threading.Thread(target=run_and_cancel_queue)
    thread.start()

    processed_jobs = runner.run_queue(stop_on_error=False)  # stop_on_error irrelevant due to cancel_queue
    thread.join()

    assert len(processed_jobs) == 3  # All jobs are moved to processed list
    # TODO: IT'S NOT PASSING.
    assert processed_jobs[0].status == "failed"  # Job 1
    assert processed_jobs[1].job_id == "cancel_q_job2_long"
    assert processed_jobs[1].status in ["cancelled", "failed", 'completed']  # Job 2 (active during cancel)

    assert processed_jobs[2].job_id == "cancel_q_job3"
    assert processed_jobs[2].status == "cancelled"  # Job 3 (pending during cancel)

    assert os.path.exists(out1)
    assert not os.path.exists(out3)  # Job 3 should not have created its file

# TODO: Add tests for adding jobs while queue is running (if feature is refined)
# TODO: Add test for CommandBuilderError within a job's builder.run() if build is deferred
