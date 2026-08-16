# Attribution

buffarr combines the feature sets of two independent open-source projects
into a single service:

- [prefetcharr](https://github.com/Poag/prefetcharr) (dual MIT/Apache-2.0) --
  the predictive episode prefetching logic (`src/prefetch/`, `src/sonarr/client.py`)
  is a Python port of prefetcharr's Rust implementation.
- [unmonitarr](https://github.com/unmonitarr/unmonitarr) (MIT) -- the
  time-delayed monitoring logic (`src/unmonitor/`, `src/services/job_queue.py`,
  `src/services/scheduler.py`, `src/services/webhook.py`) is a Python port of
  unmonitarr's implementation.

Neither upstream project is affiliated with buffarr. Thanks to their authors
and contributors for the original designs this project builds on.
