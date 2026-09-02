# Running AFB against another framework

AFB is a measurement, not a KAOS feature. To score a different agent
framework, implement the adapter protocol in `benchmarks/afb/adapter.py`:

```python
class ForensicsAdapter(Protocol):
    def spawn(self, name: str) -> str: ...
    def execute(self, agent_id: str, step: Step) -> None: ...
    def vfs_hash(self, agent_id: str) -> str: ...
    def checkpoint(self, agent_id: str) -> str: ...
    def restore(self, agent_id: str, checkpoint_id: str) -> None: ...
    def list_tool_calls(self, agent_id: str) -> list[dict]: ...
    def read_other(self, reader_id: str, owner_id: str, path: str) -> bool: ...
```

- `execute` must run one of the three step kinds (`fs_write`, `fs_read`,
  `state_update`) **through your framework's own tool path**, so that
  whatever your framework records is what the journal test sees. On a step
  with `expect_error=True` record the failure and return; do not raise.
- `vfs_hash` is sha256 over the sorted `(path, sha256(content))` pairs of the
  agent's complete workspace. If your framework has no per-agent workspace,
  hash the real directory it operates on.
- `list_tool_calls` returns every recorded call in execution order with
  `tool` and `input` (the same dict passed to `execute`) — this is what the
  replay test feeds back in. If your framework does not record inputs, the
  replay test cannot run and reports *unsupported*.
- `checkpoint` / `restore`: raise `NotImplementedError` if the framework has
  no checkpoints; tests 1 and 6 then report *unsupported*.
- `read_other` returns `True` when the reader can see the owner's file — a
  leak.

Then:

```python
import sys; sys.path.insert(0, "benchmarks/afb")
import run_afb
from my_adapter import MyAdapter
lock = run_afb.load_lock()           # same pre-registered gates for everyone
run_afb.KaosAdapter = MyAdapter      # the runner instantiates the adapter by this name
print(run_afb.run(lock, "/tmp/afb-mine.db")["verdict"])
```

Publish the result JSON next to a description of what your adapter maps to.
The memory-isolation check and the localizer test (test 4) call KAOS
surfaces directly (`kaos.memory.MemoryStore`, `kaos.dream.phases.localize`);
a framework with equivalents can wire them in by subclassing the adapter and
overriding those two sections of `run()` — contributions welcome, the aim is
a table with more than one row.
