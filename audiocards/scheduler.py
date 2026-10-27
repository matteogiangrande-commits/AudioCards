"""DARS, operating on exact PCM sample counts, not estimated reading times."""
from __future__ import annotations
import heapq
import random
from datetime import date, timedelta
from .models import Card, Asset, Event, Session, Config, frames

Assets = dict[str, tuple[Asset, Asset]]


def _validate(cards: list[Card], assets: Assets):
    if not cards:
        raise ValueError('Nessuna scheda da programmare.')
    if len({c.card_id for c in cards}) != len(cards):
        raise ValueError('Gli identificatori delle schede devono essere unici.')
    if any(c.card_id not in assets for c in cards):
        raise ValueError('Mancano segmenti vocali per una o piu schede.')


def _event(card: Card, pair: tuple[Asset, Asset], cfg: Config, kind: str,
           session: str, clock: int, due: int | None = None, wait: int = 0) -> Event:
    q, a = pair
    pause = 0 if kind == 'INTRO' else cfg.pause_frames(a.frame_count)
    bridge = frames(cfg.intro_bridge) if kind == 'INTRO' else 0
    gap = frames(cfg.event_gap)
    total = wait + q.frame_count + a.frame_count + pause + bridge + gap
    return Event(f'{session}:{card.card_id}:{kind}', card.card_id, kind, session,
                 clock, clock+total, q.frame_count, a.frame_count, pause, bridge,
                 gap, wait, q.asset_id, a.asset_id, due)


def plan_learning(cards: list[Card], assets: Assets, cfg: Config) -> Session:
    _validate(cards, assets)
    cards = sorted(cards, key=lambda c: (c.source_order, c.card_id))
    by_id = {c.card_id: c for c in cards}
    # due, recall number, stable order, id, previous end
    pending: list[tuple[int, int, int, str, int]] = []
    output: list[Event] = []
    clock = next_intro = streak = 0
    while next_intro < len(cards) or pending:
        overdue = bool(pending and pending[0][0] <= clock)
        may_introduce = next_intro < len(cards)
        fair = (overdue and may_introduce and streak >= cfg.fairness_every
                and clock - pending[0][0] <= frames(cfg.fairness_max_late))
        if may_introduce and (not overdue or fair):
            card = cards[next_intro]; next_intro += 1
            event = _event(card, assets[card.card_id], cfg, 'INTRO', 'Apprendimento', clock)
            heapq.heappush(pending, (event.end_frame+frames(cfg.first_delay), 1,
                                    card.source_order, card.card_id, event.end_frame))
            streak = 0
        else:
            due, number, order, card_id, previous_end = heapq.heappop(pending)
            wait = 0
            if due > clock:
                # Never pad a file up to a nominal pedagogic deadline.
                missing = max(0, frames(cfg.min_separation) - (clock - previous_end))
                wait = min(missing, frames(cfg.max_idle), due-clock)
            event = _event(by_id[card_id], assets[card_id], cfg,
                           f'RECALL_{number}', 'Apprendimento', clock, due, wait)
            if number == 1:
                heapq.heappush(pending, (event.end_frame+frames(cfg.second_delay), 2,
                                        order, card_id, event.end_frame))
            streak += 1
        output.append(event)
        clock = event.end_frame
        if len(output) > 3 * len(cards):
            raise RuntimeError('Violazione del limite di eventi dello scheduler.')
    return Session('Apprendimento', tuple(output))


def plan_review(cards: list[Card], assets: Assets, cfg: Config) -> list[Session]:
    _validate(cards, assets)
    ordered = sorted(cards, key=lambda c: (c.source_order, c.card_id))
    previous: list[str] = []
    sessions = []
    for offset in (1, 3, 7, 14):
        session_id = f'Ripasso_G+{offset:02d}'
        order = ordered.copy()
        seed = cfg.seed + offset * 104729
        random.Random(seed).shuffle(order)
        if len(order) > 1 and [c.card_id for c in order] == previous:
            order = order[1:] + order[:1]
        previous = [c.card_id for c in order]
        clock = 0; events = []
        for card in order:
            event = _event(card, assets[card.card_id], cfg, 'REVIEW', session_id, clock)
            events.append(event); clock = event.end_frame
        suggested = ((date.fromisoformat(cfg.completion_date) + timedelta(days=offset)).isoformat()
                     if cfg.completion_date else None)
        sessions.append(Session(session_id, tuple(events), offset, suggested, seed))
    return sessions
