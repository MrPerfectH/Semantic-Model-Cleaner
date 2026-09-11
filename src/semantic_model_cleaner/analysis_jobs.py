"""Bounded, cancellable read-only analysis work for the local browser UI."""
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
import threading
import uuid


class AnalysisCancelled(Exception):
    pass


class AnalysisJobs:
    def __init__(self, retain=1):
        self._lock = threading.RLock()
        self._jobs = OrderedDict()
        self._retain = max(1, retain)

    def start(self, run, publish=None):
        with self._lock:
            if any(j['status'] in {'running', 'cancelling'} for j in self._jobs.values()):
                raise ValueError('An analysis is already running. Cancel it or wait for it to finish.')
            while len(self._jobs) >= self._retain:
                self._jobs.popitem(last=False)
            identity = uuid.uuid4().hex
            job = {'id': identity, 'status': 'running', 'stage': 'Starting analysis',
                   'current': 0, 'total': None, 'started_at': datetime.now(timezone.utc).isoformat(),
                   '_cancel': threading.Event()}
            self._jobs[identity] = job

        def progress(stage, current=0, total=None):
            with self._lock:
                if job['_cancel'].is_set():
                    raise AnalysisCancelled()
                job.update(stage=stage, current=current, total=total)

        def worker():
            try:
                result = run(progress)
                with self._lock:
                    if job['_cancel'].is_set():
                        raise AnalysisCancelled()
                    if publish:
                        publish(result)
                    job.update(status='completed', stage='Complete', result=result)
            except AnalysisCancelled:
                with self._lock:
                    job.update(status='cancelled', stage='Cancelled')
            except (Exception, SystemExit) as exc:
                with self._lock:
                    job.update(status='failed', stage='Failed', error=str(exc) or 'Analysis failed')
        with self._lock:
            snapshot = {k: v for k, v in job.items() if not k.startswith('_')}
            threading.Thread(target=worker, name='smc-analysis', daemon=True).start()
            return snapshot

    @contextmanager
    def invalidate(self):
        """Serialize scope/file mutations with starts and result publication.

        Workers are cancelled cooperatively; callers never wait for their exit.
        The lock prevents a new scan starting halfway through the mutation.
        """
        with self._lock:
            for job in self._jobs.values():
                if job['status'] in {'running', 'cancelling'}:
                    job['_cancel'].set()
                    job.update(status='cancelling', stage='Scope or files changed')
            yield

    def get(self, identity, include_result=True):
        with self._lock:
            if identity not in self._jobs:
                raise KeyError('Analysis job not found or expired')
            return {k: v for k, v in self._jobs[identity].items()
                    if not k.startswith('_') and (include_result or k != 'result')}

    def cancel(self, identity):
        with self._lock:
            job = self._jobs[identity]
            if job['status'] == 'running':
                job['_cancel'].set()
                job.update(status='cancelling', stage='Cancelling after current scan step')
            return self.get(identity, include_result=False)
