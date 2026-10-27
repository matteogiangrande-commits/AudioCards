from __future__ import annotations
from dataclasses import dataclass, field
import csv
import hashlib
import io
import re
from collections import Counter
from .models import Card
from .normalizer import detect_language, spoken_text

MAX_INPUT = 2_000_000
MAX_CARDS = 10000

@dataclass
class ParseResult:
    cards: list[Card] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    card_warnings: dict[str, list[str]] = field(default_factory=dict)
    format: str = ''


def _pipe_fields(line: str) -> list[str]:
    # Only escape a pipe or another backslash. Preserve LaTeX, paths and apostrophes.
    cells, chars = [], []
    quoted = False
    i = 0
    while i < len(line):
        c = line[i]
        if c == '\\' and i + 1 < len(line) and line[i+1] in ('|', '\\'):
            chars.append(line[i+1]); i += 2; continue
        if c == '"':
            if quoted and i + 1 < len(line) and line[i+1] == '"':
                chars.append('"'); i += 2; continue
            if quoted:
                quoted = False; i += 1; continue
            if not ''.join(chars).strip():
                quoted = True; i += 1; continue
        if c == '|' and not quoted:
            cells.append(''.join(chars).strip()); chars = []
        else:
            chars.append(c)
        i += 1
    if quoted:
        raise ValueError('Virgolette non chiuse.')
    cells.append(''.join(chars).strip())
    return cells


def parse_cards(text: str, format: str = 'auto', language: str = 'auto') -> ParseResult:
    result = ParseResult()
    if language not in ('auto', 'it', 'en'):
        result.errors.append('Lingua non valida.'); return result
    if len(text) > MAX_INPUT:
        result.errors.append('Testo troppo grande (limite 2 milioni di caratteri).'); return result
    text = text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    lines = [(i+1, v) for i, v in enumerate(text.splitlines()) if v.strip()]
    if not lines:
        result.errors.append('Incollare almeno una domanda e una risposta.'); return result
    if format == 'auto':
        first = lines[0][1].strip()
        if re.match(r'^Q\s*:', first, re.I):
            format = 'qa'
        elif '\t' in first:
            format = 'tsv'
        elif re.match(r'^\s*"?question"?\s*,\s*"?answer"?\s*$', first, re.I):
            format = 'csv'
        else:
            format = 'pipe'
    result.format = format
    rows: list[tuple[int, list[str]]] = []
    if format in ('csv', 'tsv'):
        reader = csv.reader(io.StringIO(text), delimiter=',' if format == 'csv' else '\t', strict=True)
        try:
            for row in reader:
                if row and any(cell.strip() for cell in row):
                    rows.append((reader.line_num, row))
        except csv.Error:
            result.errors.append(f'Riga {reader.line_num}: struttura CSV/TSV non valida.')
        if rows and [c.strip().casefold() for c in rows[0][1]] in (
                ['question', 'answer'], ['domanda', 'risposta']):
            rows.pop(0)
    elif format == 'pipe':
        for line_no, line in lines:
            try:
                rows.append((line_no, _pipe_fields(line)))
            except ValueError as e:
                result.errors.append(f'Riga {line_no}: {e}')
    elif format == 'qa':
        current: list[str] | None = None
        start = 0
        answer_seen = False
        for line_no, line in lines:
            m = re.match(r'^\s*([QA])\s*:\s*(.*)$', line, re.I)
            if m and m[1].upper() == 'Q':
                if current is not None:
                    rows.append((start, current if answer_seen else current[:1]))
                current, start, answer_seen = [m[2], ''], line_no, False
            elif m and m[1].upper() == 'A':
                if current is None or answer_seen:
                    result.errors.append(f'Riga {line_no}: risposta senza domanda o risposta duplicata.')
                else:
                    current[1], answer_seen = m[2], True
            elif current is None:
                result.errors.append(f'Riga {line_no}: manca il prefisso Q:.')
            else:
                k = 1 if answer_seen else 0
                current[k] += '\n' + line
        if current is not None:
            rows.append((start, current if answer_seen else current[:1]))
    else:
        result.errors.append('Formato non supportato.'); return result
    if len(rows) > MAX_CARDS:
        result.errors.append(f'Troppe schede: massimo {MAX_CARDS}.'); return result
    occurrences: Counter = Counter()
    question_answers: dict[str, str] = {}
    for line_no, row in rows:
        if len(row) != 2:
            result.errors.append(f'Riga {line_no}: servono esattamente due campi, domanda e risposta.'); continue
        q, a = (x.strip() for x in row)
        if not q or not a:
            result.errors.append(f'Riga {line_no}: domanda o risposta vuota.'); continue
        digest = hashlib.sha256((q + '\x00' + a).encode('utf-8')).hexdigest()[:20]
        occurrences[digest] += 1
        card_id = f'{digest}-{occurrences[digest]}'
        warnings: list[str] = []
        if occurrences[digest] > 1:
            warnings.append('Duplicato esatto: mantenuto, non rimosso automaticamente.')
        if q in question_answers and question_answers[q] != a:
            warnings.append('Domanda identica con risposta differente: verificare.')
        question_answers[q] = a
        ql, certain_q = detect_language(q)
        al, certain_a = detect_language(a, ql)
        if language != 'auto':
            ql = al = language
            certain_q = certain_a = True
        if not certain_q or not certain_a:
            warnings.append('Lingua di un testo breve non certa: verificare IT/EN.')
        qs, qw = spoken_text(q, ql); ans, aw = spoken_text(a, al)
        warnings.extend(qw + aw)
        try:
            card = Card(card_id, q, a, qs, ans, ql, al, len(result.cards))
        except ValueError as e:
            result.errors.append(f'Riga {line_no}: {e}'); continue
        result.cards.append(card)
        if warnings:
            result.card_warnings[card_id] = list(dict.fromkeys(warnings))
            result.warnings.extend(f'Scheda {card.source_order+1}: {w}' for w in dict.fromkeys(warnings))
    if not result.cards and not result.errors:
        result.errors.append('Nessuna coppia domanda/risposta presente.')
    return result
