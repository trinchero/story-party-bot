from pathlib import Path
import pytest
from numbers_parser import Document
from narrative_bot.importer import InvalidWorkbook, parse_numbers

DEMO = Path(__file__).resolve().parents[1] / 'examples' / 'TEST_BOT_Telegram_2_personajes_historia_independiente.numbers'


def test_native_story():
    content = parse_numbers(DEMO.read_bytes())
    assert [r['Código'] for r in content['Personajes']] == ['VERA', 'BRUNO']
    assert len(content['Mensajes']) == 7
    assert [(m['Orden'], m['recipients']) for m in content['Mensajes'] if m['Fase'] == 1] == [(1, ['TODOS'])]


@pytest.mark.parametrize('sheet,row,col,value,expected', [
    ('Personajes', 2, 0, 'VERA', 'código único'),
    ('Mensajes', 1, 2, 'INES', 'códigos existentes'),
    ('Mensajes', 1, 4, '', 'completa Texto'),
    ('Mensajes', 1, 1, 2, 'sin saltos'),
    ('Fases', 1, 0, 1.5, 'entero positivo'),
    ('Guia', 0, 0, 'Wrong', 'columnas'),
])
def test_numbers_validation(tmp_path, sheet, row, col, value, expected):
    doc = Document(DEMO)
    doc.sheets[sheet].tables[0].write(row, col, value)
    path = tmp_path / 'invalid.numbers'
    doc.save(path)
    with pytest.raises(InvalidWorkbook, match=expected) as exc:
        parse_numbers(path.read_bytes())
    assert f'{sheet}, fila ' in str(exc.value)


def test_reject_multiple_tables(tmp_path):
    doc = Document(DEMO)
    doc.sheets['Mensajes'].add_table('Extra')
    path = tmp_path / 'multiple.numbers'
    doc.save(path)
    with pytest.raises(InvalidWorkbook, match='una sola tabla'):
        parse_numbers(path.read_bytes())


def test_numbers_invalid_archive_and_size():
    for data in [b'broken', b'x' * 5_000_001]:
        with pytest.raises(InvalidWorkbook, match='Archivo, fila 1'):
            parse_numbers(data)
