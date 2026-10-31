# Credits: gogeta_gg
import os
import time
from dataclasses import dataclass


@dataclass
class KeyState:
    failures: int = 0
    blocked_until: float = 0.0
    last_failure: str = ''
    last_used: float = 0.0
    last_success: float = 0.0


class ProviderKeyPool:
    """Per-provider API-key failover pool.

    Supports KEY, KEY_1, KEY_2, ... without exposing values in logs.
    Keys are cooled independently for rate limits/network/server failures.
    """
    def __init__(self, env_name: str, *, cooldown=60.0, failure_threshold=2):
        self.env_name = env_name
        self.cooldown = max(float(cooldown), 5.0)
        self.failure_threshold = max(int(failure_threshold), 1)
        self.states = {}

    def refresh(self):
        values = []
        seen = set()
        raw = str(os.getenv(self.env_name, '') or '').strip()
        if raw:
            values.append((self.env_name, raw))
            seen.add(raw)

        numbered = []
        prefix = self.env_name + '_'
        for name, value in os.environ.items():
            if not name.startswith(prefix):
                continue
            suffix = name[len(prefix):]
            if not suffix.isdigit() or not suffix or not value:
                continue
            value = str(value).strip()
            if not value or value in seen:
                continue
            numbered.append((int(suffix), name, value))
            seen.add(value)
        numbered.sort(key=lambda x: x[0])
        values.extend((name, value) for _, name, value in numbered)

        active = {name for name, _ in values}
        self.states = {name: state for name, state in self.states.items() if name in active}
        for name, _ in values:
            self.states.setdefault(name, KeyState())
        return values

    def keys(self):
        return self.refresh()

    def available(self):
        now = time.monotonic()
        values = self.refresh()
        ready = [(name, key) for name, key in values if self.states[name].blocked_until <= now]
        if ready:
            ready.sort(key=lambda item: (self.states[item[0]].failures, self.states[item[0]].last_used, item[0]))
            return ready
        # Half-open the key whose cooldown expires first.
        if values:
            values.sort(key=lambda item: self.states[item[0]].blocked_until)
            name, key = values[0]
            if self.states[name].blocked_until < now + 30:
                return [(name, key)]
        return []

    def mark_used(self, name):
        state = self.states.get(name)
        if state:
            state.last_used = time.monotonic()

    def success(self, name):
        state = self.states.get(name)
        if not state:
            return
        state.failures = 0
        state.blocked_until = 0.0
        state.last_failure = ''
        state.last_success = time.monotonic()
        state.last_used = state.last_success

    def failure(self, name, reason):
        state = self.states.get(name)
        if not state:
            return
        state.failures += 1
        state.last_failure = reason
        state.last_used = time.monotonic()
        if reason == 'auth':
            # Bad credentials should not be hammered repeatedly.
            state.blocked_until = time.monotonic() + max(self.cooldown * 10, 300)
        elif reason == 'rate_limit':
            state.blocked_until = time.monotonic() + max(self.cooldown, 30)
        elif reason in {'timeout', 'network', 'server_error'} and state.failures >= self.failure_threshold:
            state.blocked_until = time.monotonic() + self.cooldown
        elif reason == 'billing':
            state.blocked_until = time.monotonic() + max(self.cooldown * 10, 600)

    def configured_count(self):
        return len(self.refresh())
