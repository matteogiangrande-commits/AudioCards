from __future__ import annotations
from .models import Session, Chunk, frames


def split_session(session: Session, target_seconds: float) -> list[Chunk]:
    """O(N), preserve exact order, choose closest whole-event boundary."""
    target = frames(target_seconds)
    if target <= 0:
        raise ValueError('La durata target deve essere positiva.')
    result = []; current = []; length = 0
    for event in session.events:
        if event.session_id != session.session_id:
            raise ValueError('Non unire sessioni di ripasso diverse.')
        proposed = length + event.duration_frames
        if current and proposed > target and abs(length-target) <= abs(proposed-target):
            result.append(Chunk(session.session_id, len(result)+1, tuple(current)))
            current = []; length = 0
        current.append(event); length += event.duration_frames
        if length >= target:
            result.append(Chunk(session.session_id, len(result)+1, tuple(current)))
            current = []; length = 0
    if current:
        result.append(Chunk(session.session_id, len(result)+1, tuple(current)))
    return result
