"""Job transitions and callback policy shared by inline and Qt execution."""

import traceback

from core.jobs import CancelToken, JobState


class JobLifecycle:
    """Calling-thread bookkeeping; adapters own execution and notifications.

    Release a step before delivering its callback. Retire a finished job from
    the adapter's live registry before notifying completion: callbacks can
    cancel, supersede or submit another job re-entrantly.
    """

    def __init__(self, record, *, on_step=None, on_error=None, on_done=None,
                 on_diagnostic=None, callback_errors=None, step_sizes=None):
        self.record = record
        # With step_sizes the job counts units (channels), not steps: a step is
        # worth its size, and its progress_fn moves `done` unit by unit, so a
        # file with 30 channels reads 12/30 rather than 0/1 (#469).
        self.step_sizes = list(step_sizes) if step_sizes is not None else None
        self._reported = {}     # step index -> units already counted
        if self.step_sizes is not None:
            record.total = sum(self.step_sizes)
        self.cancel_token = CancelToken()
        self.superseded = False
        self.in_flight = 0
        self.on_step = on_step
        self.on_error = on_error
        self.on_done = on_done
        self.on_diagnostic = on_diagnostic
        self.callback_errors = callback_errors

    @property
    def stopped_state(self):
        return JobState.SUPERSEDED if self.superseded else JobState.CANCELLED

    def cancel(self, *, superseded=False):
        self.superseded |= superseded
        self.cancel_token.cancel()

    def start_step(self, label):
        self.record.step_label = label
        self.record.sub_done = 0
        self.record.sub_total = 0

    def report_progress(self, index, done, total):
        if not self.record.is_running or self.cancel_token.is_cancelled:
            return False
        if self.step_sizes is not None:
            done = min(done, self.step_sizes[index])
            delta = done - self._reported.get(index, 0)
            if delta <= 0:
                return False
            self._reported[index] = done
            self.record.done += delta
            return True
        if index != self.record.done:
            return False
        self.record.sub_done = done
        self.record.sub_total = total
        return True

    def release_step(self, index):
        self.in_flight -= 1
        if self.step_sizes is not None:
            self.record.done += self.step_sizes[index] - self._reported.pop(index, 0)
        else:
            self.record.done += 1
        self.record.sub_done = 0
        self.record.sub_total = 0

    def deliver_result(self, payload, index):
        if not self.cancel_token.is_cancelled:
            self._invoke(self.on_step, "result", payload, index)

    def deliver_error(self, message, index):
        if self.cancel_token.is_cancelled:
            return
        self.record.errors.append(message)
        if self.on_error is not None:
            self._invoke(self.on_error, "error", message, index)
        elif self.on_diagnostic is not None:
            self.on_diagnostic(message)

    def finish(self, state):
        """Claim terminal state once; the adapter retires before notify_done."""
        if not self.record.is_running:
            return False
        self.record.state = state
        self.start_step("")
        return True

    def notify_done(self):
        self._invoke(self.on_done, "completion", self.record)

    def _invoke(self, callback, kind, *args):
        if callback is None:
            return
        try:
            callback(*args)
        except Exception as error:
            message = f"{kind} handling failed: {error}"
            self.record.errors.append(message)
            if self.callback_errors is not None:
                self.callback_errors.append(message)
            if self.on_diagnostic is not None:
                self.on_diagnostic(f"{message}\n{traceback.format_exc()}")
