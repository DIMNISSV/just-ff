import subprocess
import typing
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from just_ff.command import FFmpegCommandBuilder
from just_ff.exceptions import FfmpegProcessError, FfmpegWrapperError, CommandBuilderError

if typing.TYPE_CHECKING:
    # Это для type hinting, чтобы избежать циклического импорта, если понадобится
    pass


@dataclass
class FFmpegJob:
    """Represents a single FFmpeg job in the queue."""
    builder: FFmpegCommandBuilder
    duration_sec: typing.Optional[float] = None
    job_id: typing.Optional[str] = None
    context: typing.Any = None  # User-defined context

    # Internal state, not meant to be set directly by user
    status: str = field(default="pending", init=False)  # pending, preparing, running, completed, failed, cancelled
    result: typing.Any = field(default=None, init=False)  # True on success, Exception on failure
    error_message: typing.Optional[str] = field(default=None, init=False)  # Store specific error message
    _internal_process: typing.Optional[subprocess.Popen] = field(default=None, init=False, repr=False)

    def __str__(self):
        return (f"FFmpegJob(id={self.job_id or 'N/A'}, status={self.status}, "
                f"command_preview='{self.builder.build()[:70]}...')")


class FFmpegQueueRunner:
    """
    Manages and runs a queue of FFmpeg jobs sequentially.
    """

    def __init__(
            self,
            # --- Job specific callbacks ---
            on_job_start: typing.Optional[typing.Callable[[int, FFmpegJob], None]] = None,
            on_job_progress: typing.Optional[typing.Callable[[int, FFmpegJob, float], None]] = None,
            on_job_process_created: typing.Optional[typing.Callable[[int, FFmpegJob, subprocess.Popen], None]] = None,
            on_job_complete: typing.Optional[typing.Callable[[int, FFmpegJob], None]] = None,
            # --- Queue specific callbacks ---
            on_queue_start: typing.Optional[typing.Callable[['FFmpegQueueRunner'], None]] = None,
            on_queue_complete: typing.Optional[
                typing.Callable[['FFmpegQueueRunner', typing.List[FFmpegJob]], None]] = None,
    ):
        self._pending_queue: deque[FFmpegJob] = deque()
        self._processed_jobs: typing.List[FFmpegJob] = []  # Stores all jobs attempted in the last run_queue call

        self._active_job: typing.Optional[FFmpegJob] = None
        self._current_job_index_in_run: int = -1  # Index of the job within the current run_queue call

        self._is_running: bool = False
        self._stop_on_error: bool = True

        self._cancel_current_job_requested: bool = False
        self._cancel_queue_requested: bool = False

        # Callbacks
        self.on_job_start = on_job_start
        self.on_job_progress = on_job_progress
        self.on_job_process_created = on_job_process_created
        self.on_job_complete = on_job_complete
        self.on_queue_start = on_queue_start
        self.on_queue_complete = on_queue_complete

    def add_job(
            self,
            builder: FFmpegCommandBuilder,
            duration_sec: typing.Optional[float] = None,
            job_id: typing.Optional[str] = None,
            context: typing.Any = None,
    ) -> FFmpegJob:
        """Adds a new FFmpeg job to the pending queue."""
        if self._is_running:
            # Potentially, could add to a temporary holding queue or raise error
            print("Warning: Adding job while queue is running. Job will be processed in the next run.")
            # Or raise RuntimeError("Cannot add jobs while the queue is running.")

        if not isinstance(builder, FFmpegCommandBuilder):
            raise TypeError("builder must be an instance of FFmpegCommandBuilder")

        job = FFmpegJob(builder=builder, duration_sec=duration_sec, job_id=job_id, context=context)
        self._pending_queue.append(job)
        print(f"Added job: {job}")
        return job

    def run_queue(self, stop_on_error: bool = True) -> None | list[Any] | list[FFmpegJob]:
        """
        Runs all jobs in the pending queue sequentially. This is a blocking operation.

        Args:
            stop_on_error: If True, the queue stops processing further jobs
                           if one job fails. If False, it continues.

        Returns:
            A list of all FFmpegJob objects that were processed or attempted
            during this run, with their final statuses.
        """
        if self._is_running:
            raise RuntimeError("Queue is already running.")
        if not self._pending_queue:
            print("Queue is empty. Nothing to run.")
            return []

        self._is_running = True
        self._stop_on_error = stop_on_error
        self._cancel_current_job_requested = False
        self._cancel_queue_requested = False
        self._processed_jobs.clear()
        self._current_job_index_in_run = 0

        initial_job_count = len(self._pending_queue)
        print(f"Starting queue with {initial_job_count} job(s). Stop on error: {self._stop_on_error}")

        if self.on_queue_start:
            try:
                self.on_queue_start(self)
            except Exception as cb_err:
                print(f"Warning: on_queue_start callback failed: {cb_err}")

        while self._pending_queue:
            if self._cancel_queue_requested:
                print("Queue run cancelled by user request.")
                break

            job = self._pending_queue.popleft()
            self._active_job = job
            self._processed_jobs.append(job)

            # Reset per-job cancellation flag
            self._cancel_current_job_requested = False

            job.status = "preparing"  # Set status before callbacks
            if self.on_job_start:
                try:
                    self.on_job_start(self._current_job_index_in_run, job)
                except Exception as cb_err:
                    print(f"Warning: on_job_start callback for job '{job.job_id}' failed: {cb_err}")

            job_succeeded = False
            try:
                job.status = "running"
                print(f"Running job {self._current_job_index_in_run + 1}/{initial_job_count}: {job}")

                # --- Define per-job progress and process callbacks ---
                def _job_progress_callback(percentage: float):
                    if self.on_job_progress:
                        try:
                            self.on_job_progress(self._current_job_index_in_run, job, percentage)
                        except Exception as cb_err:
                            print(f"Warning: on_job_progress callback for job '{job.job_id}' failed: {cb_err}")

                    # Check for cancellation signals
                    if self._cancel_current_job_requested or self._cancel_queue_requested:
                        if job._internal_process and job._internal_process.poll() is None:
                            print(f"Terminating process for job '{job.job_id}' due to cancellation request.")
                            try:
                                job._internal_process.terminate()
                                # job._internal_process.wait(timeout=5) # Optionally wait
                            except Exception as e:
                                print(f"Error terminating process for job '{job.job_id}': {e}")
                        # This will likely lead to FfmpegProcessError in builder.run()

                def _job_process_callback(process: subprocess.Popen):
                    job._internal_process = process
                    if self.on_job_process_created:
                        try:
                            self.on_job_process_created(self._current_job_index_in_run, job, process)
                        except Exception as cb_err:
                            print(f"Warning: on_job_process_created for job '{job.job_id}' failed: {cb_err}")

                # --- Execute the command ---
                job.builder.run(
                    duration_sec=job.duration_sec,
                    progress_callback=_job_progress_callback,
                    process_callback=_job_process_callback,
                    check=True  # Let it raise FfmpegProcessError on non-zero exit
                )
                job_succeeded = True
                job.status = "completed"
                job.result = True

            except FfmpegProcessError as e:
                job.status = "failed"
                job.result = e
                job.error_message = str(e)
                print(
                    f"Job '{job.job_id}' (idx {self._current_job_index_in_run}) failed: {e.exit_code} - {e.stderr[:200]}...")
                if self._stop_on_error:
                    self._cancel_queue_requested = True  # Signal to stop further jobs
            except (CommandBuilderError, FfmpegWrapperError) as e:
                job.status = "failed"
                job.result = e
                job.error_message = str(e)
                print(f"Job '{job.job_id}' (idx {self._current_job_index_in_run}) encountered a wrapper error: {e}")
                if self._stop_on_error:
                    self._cancel_queue_requested = True
            except Exception as e:  # Catch-all for unexpected issues
                job.status = "failed"
                job.result = e
                job.error_message = str(e)
                print(f"Job '{job.job_id}' (idx {self._current_job_index_in_run}) encountered an unexpected error: {e}")
                if self._stop_on_error:
                    self._cancel_queue_requested = True
            finally:
                if job._internal_process and job._internal_process.poll() is None:
                    # If process is still running after run() call (e.g. due to external termination/exception)
                    print(f"Job '{job.job_id}' ended but process was still running. Attempting cleanup.")
                    try:
                        job._internal_process.kill()  # More forceful if terminate didn't work
                    except:
                        pass
                job._internal_process = None  # Clear process object

                if (self._cancel_current_job_requested or self._cancel_queue_requested) and job.status not in ["failed",
                                                                                                               "completed"]:
                    job.status = "cancelled"  # Mark as cancelled if it was stopped by request
                    job.error_message = job.error_message or "Job cancelled by user."

                if self.on_job_complete:
                    try:
                        self.on_job_complete(self._current_job_index_in_run, job)
                    except Exception as cb_err:
                        print(f"Warning: on_job_complete callback for job '{job.job_id}' failed: {cb_err}")

                self._active_job = None
                self._current_job_index_in_run += 1

        # Handle any remaining jobs in _pending_queue if queue was cancelled
        while self._pending_queue:
            job = self._pending_queue.popleft()
            job.status = "cancelled"  # Or "skipped"
            job.error_message = "Queue processing was cancelled before this job started."
            self._processed_jobs.append(job)
            if self.on_job_start:  # Could call on_job_start then immediately on_job_complete with cancelled status
                try:
                    self.on_job_start(self._current_job_index_in_run, job)
                except:
                    pass
            if self.on_job_complete:
                try:
                    self.on_job_complete(self._current_job_index_in_run, job)
                except:
                    pass
            self._current_job_index_in_run += 1

        self._is_running = False
        print(f"Queue processing finished. Processed {len(self._processed_jobs)} job(s).")

        if self.on_queue_complete:
            try:
                self.on_queue_complete(self, self._processed_jobs)
            except Exception as cb_err:
                print(f"Warning: on_queue_complete callback failed: {cb_err}")

        return list(self._processed_jobs)  # Return a copy

    def cancel_current_job(self) -> bool:
        """
        Requests cancellation of the currently active FFmpeg job.
        The job will be terminated, and its status marked as 'cancelled' or 'failed'.
        This does not stop the queue from processing subsequent jobs unless
        cancel_queue() is also called or stop_on_error is True and cancellation causes an error.
        """
        if not self._is_running or not self._active_job:
            print("Cannot cancel current job: Queue is not running or no job is active.")
            return False

        print(f"Requesting cancellation for current job: {self._active_job.job_id or 'N/A'}")
        self._cancel_current_job_requested = True

        # The actual termination happens in the _job_progress_callback
        # or if the Popen object is directly terminated here.
        # For robustness, rely on the flag being checked by the progress callback.
        if self._active_job._internal_process and self._active_job._internal_process.poll() is None:
            try:
                print(f"Attempting immediate termination of process for job '{self._active_job.job_id}'")
                self._active_job._internal_process.terminate()
                return True
            except Exception as e:
                print(f"Error during immediate termination attempt for job '{self._active_job.job_id}': {e}")
                return False  # Termination attempt failed, but flag is set.
        return True  # Flag set

    def cancel_queue(self) -> None:
        """
        Requests cancellation of the current job and all subsequent pending jobs in the queue.
        """
        if not self._is_running:
            print("Cannot cancel queue: Queue is not running.")
            return

        print("Requesting cancellation of the entire queue.")
        self._cancel_queue_requested = True
        if self._active_job:  # If a job is currently running, also request its cancellation
            self.cancel_current_job()

    def clear_pending_jobs(self) -> int:
        """Removes all jobs from the pending queue. Cannot be called if queue is running."""
        if self._is_running:
            raise RuntimeError("Cannot clear pending jobs while the queue is running.")
        count = len(self._pending_queue)
        self._pending_queue.clear()
        print(f"Cleared {count} pending job(s).")
        return count

    def get_pending_jobs(self) -> typing.List[FFmpegJob]:
        """Returns a list of jobs currently in the pending queue."""
        return list(self._pending_queue)

    def get_processed_jobs(self) -> typing.List[FFmpegJob]:
        """
        Returns a list of all jobs that were processed or attempted in the
        most recent call to run_queue().
        """
        return list(self._processed_jobs)  # Return a copy

    @property
    def is_running(self) -> bool:
        """True if the queue is currently processing jobs, False otherwise."""
        return self._is_running

    @property
    def active_job(self) -> typing.Optional[FFmpegJob]:
        """The job currently being processed, or None."""
        return self._active_job

    @property
    def pending_job_count(self) -> int:
        """Number of jobs waiting in the queue."""
        return len(self._pending_queue)
