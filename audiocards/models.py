from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import math
from typing import Literal
from . import SAMPLE_RATE, SCHEDULER_VERSION

Kind = Literal['INTRO', 'RECALL_1', 'RECALL_2', 'REVIEW']


def frames(seconds: float) -> int:
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError('Durata non valida.')
    return round(seconds * SAMPLE_RATE)


@dataclass(frozen=True)
class Card:
    card_id: str
    question_original: str
    answer_original: str
    question_spoken: str
    answer_spoken: str
    question_lang: str = 'it'
    answer_lang: str = 'it'
    source_order: int = 0
    content_version: int = 1

    def __post_init__(self):
        if not self.card_id or self.source_order < 0:
            raise ValueError('Identificatore o ordine scheda non valido.')
        for text in (self.question_original, self.answer_original,
                     self.question_spoken, self.answer_spoken):
            if not isinstance(text, str) or not text.strip():
                raise ValueError('Domanda e risposta non possono essere vuote.')
            if len(text) > 16000:
                raise ValueError('Un singolo campo supera 16.000 caratteri: dividerlo.')
            if '\x00' in text:
                raise ValueError('Carattere NUL non ammesso nel testo.')
        if self.question_lang not in ('it', 'en') or self.answer_lang not in ('it', 'en'):
            raise ValueError('Lingue supportate: italiano e inglese.')


@dataclass(frozen=True)
class Config:
    mode: str = 'learn'
    target_minutes: int = 20
    speed: float = 1.0
    pause_factor: float = 1.3
    pause_min: float = 4.0
    pause_max: float = 35.0
    first_delay: float = 180.0
    second_delay: float = 600.0
    min_separation: float = 15.0
    max_idle: float = 20.0
    intro_bridge: float = 0.3
    event_gap: float = 1.0
    fairness_every: int = 3
    fairness_max_late: float = 120.0
    seed: int = 4217
    completion_date: str = ''

    def __post_init__(self):
        if self.mode not in ('learn', 'review'):
            raise ValueError('Modalita non valida.')
        if self.target_minutes not in (10, 20, 40, 60):
            raise ValueError('Durate ammesse: 10, 20, 40, 60 minuti.')
        numeric = (self.speed, self.pause_factor, self.pause_min, self.pause_max,
                   self.first_delay, self.second_delay, self.min_separation,
                   self.max_idle, self.intro_bridge, self.event_gap, self.fairness_max_late)
        if any(not math.isfinite(x) or x < 0 for x in numeric):
            raise ValueError('Le impostazioni devono essere numeri finiti e non negativi.')
        if not .5 <= self.speed <= 2:
            raise ValueError('Velocita ammessa: da 0,5 a 2.')
        if not .1 <= self.pause_factor <= 5 or not 0 < self.pause_min <= self.pause_max <= 180:
            raise ValueError('Pause: minimo > 0, massimo >= minimo, limite 180 secondi.')
        if self.fairness_every < 1 or self.first_delay <= 0 or self.second_delay <= 0:
            raise ValueError('Configurazione dello scheduler non valida.')
        if self.completion_date:
            from datetime import date
            date.fromisoformat(self.completion_date)

    def pause_frames(self, answer_frames: int) -> int:
        return frames(min(self.pause_max, max(self.pause_min,
                           self.pause_factor * answer_frames / SAMPLE_RATE)))


@dataclass(frozen=True)
class Asset:
    asset_id: str
    path: Path
    frame_count: int
    sha256: str

    def __post_init__(self):
        if self.frame_count <= 0:
            raise ValueError('Il segmento vocale e vuoto.')

    @property
    def duration(self) -> float:
        return self.frame_count / SAMPLE_RATE


@dataclass(frozen=True)
class Event:
    event_id: str
    card_id: str
    kind: Kind
    session_id: str
    start_frame: int
    end_frame: int
    question_frames: int
    answer_frames: int
    pause_frames: int
    bridge_frames: int
    gap_frames: int
    wait_frames: int
    q_asset_id: str
    a_asset_id: str
    due_frame: int | None = None

    @property
    def question_start_frame(self) -> int:
        return self.start_frame + self.wait_frames

    @property
    def duration_frames(self) -> int:
        return self.end_frame - self.start_frame

    def to_dict(self) -> dict:
        result = asdict(self)
        result.update({
            'start_s': self.start_frame / SAMPLE_RATE,
            'end_s': self.end_frame / SAMPLE_RATE,
            'duration_s': self.duration_frames / SAMPLE_RATE,
            'question_start_s': self.question_start_frame / SAMPLE_RATE,
            'pause_s': self.pause_frames / SAMPLE_RATE,
            'transition_s': self.bridge_frames / SAMPLE_RATE,
            'gap_s': self.gap_frames / SAMPLE_RATE,
            'wait_s': self.wait_frames / SAMPLE_RATE,
            'due_s': None if self.due_frame is None else self.due_frame / SAMPLE_RATE,
            'deviation_s': None if self.due_frame is None else
                (self.question_start_frame - self.due_frame) / SAMPLE_RATE,
            'scheduler_version': SCHEDULER_VERSION,
        })
        return result


@dataclass(frozen=True)
class Session:
    session_id: str
    events: tuple[Event, ...]
    relative_day: int | None = None
    suggested_date: str | None = None
    seed: int | None = None


@dataclass(frozen=True)
class Chunk:
    session_id: str
    index: int
    events: tuple[Event, ...]

    @property
    def duration_frames(self) -> int:
        return sum(e.duration_frames for e in self.events)
