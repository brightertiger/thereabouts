"""Memory and file-descriptor budgets for order-independent row digests."""

from dataclasses import dataclass


@dataclass
class DigestLimits:
    batch_rows: int = 1024
    chunk_rows: int = 250_000
    merge_fan_in: int = 64
    write_buffer_bytes: int = 1_048_576

    def validate(self) -> None:
        if (
            min(self.batch_rows, self.chunk_rows, self.write_buffer_bytes) <= 0
            or self.merge_fan_in < 2
        ):
            raise ValueError(
                "Digest budgets must be positive and merge_fan_in at least two"
            )
