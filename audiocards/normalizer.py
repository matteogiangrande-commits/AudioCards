"""Conservative transformations; never infer a missing answer or date format."""
from __future__ import annotations
import re
import unicodedata
from datetime import date

IT = set('che cosa quale quali chi quando dove perche come il lo la gli le un una uno di del della delle dei e sono significa si nella nel con non oppure'.split())
EN = set('what which who when where why how the a an is are was were does do did of in and means with not or to explain define'.split())
MONTH_IT = ('gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre').split()
MONTH_EN = ('January February March April May June July August September October November December').split()


def detect_language(text: str, fallback: str = 'it') -> tuple[str, bool]:
    tokens = re.findall(r'[^\W\d_]+', text.casefold(), re.UNICODE)
    it = sum(t in IT for t in tokens)
    en = sum(t in EN for t in tokens)
    if it > en:
        return 'it', True
    if en > it:
        return 'en', True
    return fallback, False


def spoken_text(original: str, language: str) -> tuple[str, list[str]]:
    text = unicodedata.normalize('NFC', original).strip()
    warnings: list[str] = []
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', text):
        warnings.append('Caratteri di controllo rimossi dalla sola versione vocale.')
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    text = re.sub(r'\s+', ' ', text)
    def iso_date(m):
        try:
            d = date.fromisoformat(m.group())
        except ValueError:
            warnings.append('Data ISO non valida: controllare la pronuncia.')
            return m.group()
        if language == 'it':
            return f'{d.day} {MONTH_IT[d.month-1]} {d.year}'
        return f'{MONTH_EN[d.month-1]} {d.day}, {d.year}'
    text = re.sub(r'(?<!\w)\d{4}-\d{2}-\d{2}(?!\w)', iso_date, text)
    if re.search(r'\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b', text):
        warnings.append('Data con separatori ambigua: controllare il campo da pronunciare.')
    if any(x in text for x in ('\u2192', '\u2200', '\u2203', '\\frac', '\\sum', '$', '\u222b')):
        warnings.append('Formula o simbolo: inserire una lettura esplicita nel campo vocale.')
    if '\u00b2' in text or '\u00b3' in text:
        text = text.replace('\u00b2', ' al quadrato' if language == 'it' else ' squared')
        text = text.replace('\u00b3', ' al cubo' if language == 'it' else ' cubed')
        warnings.append('Potenza espansa: verificare i nomi delle variabili con Anteprima.')
    if '=' in text or any(x in text for x in ('+', '\u2212', '\u00d7', '\u00f7')):
        warnings.append('Espressione matematica: verificare la pronuncia; non viene interpretata.')
    if re.search(r'\b[A-Z]{2,}\b', text):
        warnings.append('Sigla: verificare se leggere le lettere o la parola.')
    return text, list(dict.fromkeys(warnings))
