"""Conservative pacing from observed read latency, without a synthetic load test."""

from dataclasses import dataclass


@dataclass
class ReadPacing:
    samples: int = 0
    total: float = 0.0
    latency: float = 0.0

    @property
    def period(self) -> float:
        return max(0.2, self.latency * 5)

    @property
    def rate(self) -> float:
        return 1 / self.period

    def observe(self, elapsed: float) -> float:
        """Idle time after this read. Back off immediately and recover gradually."""
        elapsed = max(0.0, elapsed)
        self.samples += 1
        self.total += elapsed
        self.latency = max(elapsed, self.latency * 0.9)
        return max(0.0, self.period - elapsed)
