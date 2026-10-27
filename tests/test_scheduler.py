from collections import Counter
from dataclasses import replace
import json
import pytest
from audiocards import SAMPLE_RATE
from audiocards.models import Config, frames
from audiocards.scheduler import plan_learning, plan_review
from audiocards.chunker import split_session
from conftest import dataset

@pytest.mark.parametrize('n', [1, 2, 3, 10, 100, 1000, 10000])
def test_counts_order_and_timeline(n):
    cards, assets = dataset(n)
    session = plan_learning(cards, assets, Config())
    assert len(session.events) == n*3
    seen = {}; clock = 0
    for event in session.events:
        assert event.start_frame == clock
        assert event.end_frame > event.start_frame
        assert event.duration_frames == (event.wait_frames + event.question_frames + event.answer_frames
                     + event.pause_frames + event.bridge_frames + event.gap_frames)
        if event.kind == 'INTRO':
            assert event.card_id not in seen
            assert event.pause_frames == 0 and event.bridge_frames == frames(.3)
            seen[event.card_id] = 0
        else:
            assert event.card_id in seen
            seen[event.card_id] += 1
            assert event.kind == f'RECALL_{seen[event.card_id]}'
            assert event.bridge_frames == 0
        clock = event.end_frame
    assert set(seen.values()) == {2}
    assert [e.card_id for e in session.events if e.kind == 'INTRO'] == [c.card_id for c in cards]

@pytest.mark.parametrize('seconds,pause', [(2,4),(5,6.5),(10,13),(20,26),(40,35),(90,35)])
def test_pause_formula(seconds, pause):
    assert Config().pause_frames(frames(seconds)) == frames(pause)

@pytest.mark.parametrize('n', [1,2,10,100,1000])
@pytest.mark.parametrize('minutes', [10,20,40,60])
def test_chunking_lossless(n, minutes):
    cards, assets = dataset(n)
    session = plan_learning(cards, assets, Config(target_minutes=minutes))
    chunks = split_session(session, minutes*60)
    flattened = [e for c in chunks for e in c.events]
    assert flattened == list(session.events)
    assert json.dumps([e.to_dict() for e in flattened], sort_keys=True) == json.dumps([e.to_dict() for e in session.events], sort_keys=True)
    assert sum(c.duration_frames for c in chunks) == session.events[-1].end_frame
    assert [c.index for c in chunks] == list(range(1,len(chunks)+1))


def test_long_event_not_cut():
    cards, assets = dataset(1)
    q,a = assets[cards[0].card_id]
    assets[cards[0].card_id] = (q, replace(a, frame_count=frames(1400)))
    session = plan_learning(cards, assets, Config())
    chunks = split_session(session, 1200)
    assert len(chunks) == 3
    assert all(len(c.events) == 1 for c in chunks)
    assert chunks[0].duration_frames > frames(1200)

@pytest.mark.parametrize('seed', range(20))
def test_deterministic_and_finite_under_different_durations(seed):
    cards, assets = dataset(135, seed)
    first = plan_learning(cards, assets, Config())
    second = plan_learning(cards, assets, Config())
    assert first == second
    assert len(first.events) == 405


def test_earliest_due_priority_and_fairness_bound():
    cards, assets = dataset(100, 6)
    events = plan_learning(cards, assets, Config()).events
    pending = {}; streak = 0
    for event in events:
        overdue = {k:v for k,v in pending.items() if v <= event.start_frame}
        if event.kind == 'INTRO' and overdue:
            assert streak >= 3
            assert event.start_frame-min(overdue.values()) <= frames(120)
        if event.kind != 'INTRO':
            if overdue:
                assert pending[event.card_id] == min(overdue.values())
            pending.pop(event.card_id)
        if event.kind == 'INTRO':
            pending[event.card_id] = event.end_frame+frames(180); streak = 0
        elif event.kind == 'RECALL_1':
            pending[event.card_id] = event.end_frame+frames(600); streak += 1
        else: streak += 1
    assert not pending


def test_small_set_wait_bounded_and_recorded():
    cards, assets = dataset(1)
    events = plan_learning(cards, assets, Config()).events
    assert all(e.wait_frames <= frames(20) for e in events)
    assert all(e.to_dict()['deviation_s'] < 0 for e in events[1:])
    assert sum(e.wait_frames for e in events) == frames(30)

@pytest.mark.parametrize('n', [1,2,10,100])
def test_review_once_each_card_per_day_and_seed(n):
    cards, assets = dataset(n)
    config = Config(mode='review', completion_date='2026-10-27')
    sessions = plan_review(cards, assets, config)
    assert [s.relative_day for s in sessions] == [1,3,7,14]
    assert [s.suggested_date for s in sessions] == ['2026-10-28','2026-10-30','2026-11-03','2026-11-10']
    previous = None
    for s in sessions:
        assert len(s.events) == n
        assert set(e.kind for e in s.events) == {'REVIEW'}
        order = [e.card_id for e in s.events]
        assert set(order) == {c.card_id for c in cards}
        if n > 1 and previous is not None: assert order != previous
        previous = order
        assert s.events[0].start_frame == 0
    assert sessions == plan_review(cards, assets, config)


def test_no_invented_dates():
    cards, assets = dataset(2)
    assert all(s.suggested_date is None for s in plan_review(cards, assets, Config(mode='review')))


def test_no_cross_session_chunks():
    cards, assets = dataset(1)
    s1, s2, *_ = plan_review(cards, assets, Config(mode='review'))
    wrong = replace(s1, events=s1.events+s2.events)
    with pytest.raises(ValueError): split_session(wrong, 1200)


def test_duration_selection_does_not_change_schedule():
    cards, assets = dataset(100)
    assert plan_learning(cards, assets, Config(target_minutes=10)) == plan_learning(cards, assets, Config(target_minutes=60))


def test_empty_or_duplicate_ids_rejected():
    with pytest.raises(ValueError): plan_learning([], {}, Config())
    cards, assets = dataset(1)
    with pytest.raises(ValueError): plan_learning(cards*2, assets, Config())
