import pytest
from audiocards.parser import parse_cards
from audiocards.normalizer import spoken_text, detect_language
from audiocards.models import Card, Config

@pytest.mark.parametrize('format,text', [
    ('pipe', 'Domanda? | Risposta'), ('auto', 'Domanda? | Risposta'),
    ('tsv', 'Domanda?\tRisposta'), ('auto', 'Domanda?\tRisposta'),
    ('qa', 'Q: Domanda?\nA: Risposta'), ('auto', 'Q: Domanda?\nA: Risposta'),
    ('csv', 'question,answer\nDomanda?,Risposta'),
    ('auto', 'question,answer\nDomanda?,Risposta')])
def test_supported_formats(format, text):
    result = parse_cards(text, format)
    assert not result.errors
    assert len(result.cards) == 1
    assert result.cards[0].question_original == 'Domanda?'
    assert result.cards[0].answer_original == 'Risposta'

@pytest.mark.parametrize('text', ['', ' ', 'one field only', 'Q |', '| A', 'Q | A | extra', 'Q: a', 'Q: a\nA: b\nA: c'])
def test_invalid_input_is_not_silently_accepted(text):
    assert parse_cards(text).errors


def test_multiple_pipes_explicit_escaping():
    r = parse_cards(r'What does A\|B mean? | Keep the \frac and C:\temp text.')
    assert not r.errors
    assert r.cards[0].question_original == 'What does A|B mean?'
    assert r.cards[0].answer_original == r'Keep the \frac and C:\temp text.'


def test_quoted_pipes_and_quotes():
    r = parse_cards('"Q | quoted?" | "A ""quoted"" answer"')
    assert not r.errors
    assert r.cards[0].question_original == 'Q | quoted?'
    assert r.cards[0].answer_original == 'A "quoted" answer'


def test_ordinary_quotes_not_eaten():
    r = parse_cards('Che significa "ciao"? | Un saluto')
    assert r.cards[0].question_original == 'Che significa "ciao"?'


def test_qa_multiline():
    r = parse_cards('Q: Q1?\ncontinued\nA: A1\ncontinued answer\n\nQ: Q2?\nA: A2')
    assert not r.errors
    assert len(r.cards) == 2
    assert r.cards[0].answer_original == 'A1\ncontinued answer'


def test_csv_quoted_comma_multiline():
    r = parse_cards('question,answer\n"Q, question?","A, with comma\nand line"')
    assert not r.errors
    assert r.cards[0].answer_original == 'A, with comma\nand line'


def test_bom_and_blank_rows():
    assert len(parse_cards('\ufeffQ | A\r\n\r\nQ2 | A2\r\n').cards) == 2


def test_duplicates_retained_unique_and_conflicts_reported():
    r = parse_cards('Q | A\nQ | A\nQ | B')
    assert len(r.cards) == 3
    assert len({c.card_id for c in r.cards}) == 3
    assert any('Duplicato esatto' in s for s in r.warnings)
    assert any('differente' in s for s in r.warnings)


def test_stable_id_not_affected_by_insert():
    old = parse_cards('Q | A').cards[0]
    new = parse_cards('Other | Other answer\nQ | A').cards[1]
    assert old.card_id == new.card_id


def test_english_answer_inherits_question_when_ambiguous():
    r = parse_cards('What is the example name? | Ottawa')
    assert r.cards[0].question_lang == 'en'
    assert r.cards[0].answer_lang == 'en'


def test_explicit_language():
    r = parse_cards('An ambiguous name | London', language='it')
    assert r.cards[0].question_lang == r.cards[0].answer_lang == 'it'


def test_preserves_original_formula_unicode():
    r = parse_cards('Quale formula? | x\u00b2 + y\u00b2 = z\u00b2')
    assert r.cards[0].answer_original == 'x\u00b2 + y\u00b2 = z\u00b2'
    assert 'al quadrato' in r.cards[0].answer_spoken
    assert r.warnings


def test_ambiguous_date_not_reinterpreted():
    text, warnings = spoken_text('03/04/2026', 'en')
    assert text == '03/04/2026' and warnings


def test_iso_date_is_unambiguous():
    text, _ = spoken_text('2026-10-27', 'it')
    assert text == '27 ottobre 2026'
    text, _ = spoken_text('2026-10-27', 'en')
    assert text == 'October 27, 2026'


def test_bad_iso_date_warns():
    text, warnings = spoken_text('2026-02-31', 'it')
    assert text == '2026-02-31' and warnings


def test_latex_and_logic_not_invented():
    text, warnings = spoken_text(r'A \u2192 B and \frac{a}{b}', 'en')
    assert r'\frac{a}{b}' in text and warnings


def test_text_limits():
    assert parse_cards('Q | '+'x'*16001).errors
    assert parse_cards('x'*2000001).errors
    assert parse_cards('Q | A\n'*10001).errors

@pytest.mark.parametrize('change', [
    {'speed': 0}, {'speed': float('nan')}, {'pause_min': 10, 'pause_max': 4},
    {'pause_factor': 0}, {'target_minutes': 21}, {'mode': 'bad'},
    {'completion_date': '2026-02-31'}, {'fairness_every': 0}, {'event_gap': -1}])
def test_config_validation(change):
    with pytest.raises(ValueError): Config(**change)


def test_long_speech_split_preserves_word_sequence():
    from audiocards.tts_provider import speech_chunks
    original = ('Una frase piuttosto lunga. Un secondo esempio contiene molte parole. ')*40
    parts = speech_chunks(original)
    assert all(0 < len(p) <= 600 for p in parts)
    assert ' '.join(' '.join(parts).split()) == ' '.join(original.split())
    with pytest.raises(ValueError): speech_chunks('x'*601)
