from io import BytesIO

import pytest
from openpyxl import load_workbook

from narrative_bot.importer import InvalidWorkbook, parse_excel
from conftest import DEMO


def modified(sheet, cell, value):
    wb = load_workbook(DEMO)
    wb[sheet][cell] = value
    out = BytesIO()
    wb.save(out)
    wb.close()
    return out.getvalue()


def test_actual_demo(content):
    assert len(content['Personajes']) == 3
    assert len(content['Fases']) == 3
    assert len(content['Mensajes']) == 14
    assert sum(r['recipients'] == ['TODOS'] for r in content['Mensajes']) == 5


@pytest.mark.parametrize('sheet,cell,value,expected', [
    ('Personajes', 'A3', 'MARCO', 'código único'),
    ('Personajes', 'A2', 'TODOS', 'distinto de TODOS'),
    ('Personajes', 'D2', None, 'completa Ficha privada'),
    ('Personajes', 'A1', 'Code', 'columnas'),
    ('Mensajes', 'C2', 'FANTASMA', 'códigos existentes'),
    ('Mensajes', 'C2', 'TODOS,MARCO', 'TODOS solo'),
    ('Mensajes', 'C2', 'MARCO,MARCO', 'sin repetir'),
    ('Mensajes', 'E2', None, 'completa Texto'),
    ('Mensajes', 'E2', '=1+1', 'fórmula'),
    ('Mensajes', 'E2', '😀' * 2001, '4000'),
    ('Mensajes', 'A2', 9, 'fase existente'),
    ('Mensajes', 'B3', 1, 'sin saltos ni duplicados'),
    ('Mensajes', 'B3', 9, 'sin saltos ni duplicados'),
    ('Mensajes', 'B3', 1.5, 'entero positivo'),
    ('Fases', 'A3', 7, 'sin saltos ni duplicados'),
])
def test_validation_locations(sheet, cell, value, expected):
    with pytest.raises(InvalidWorkbook) as error:
        parse_excel(modified(sheet, cell, value))
    assert sheet + ', fila ' in str(error.value)
    assert expected in str(error.value)


def test_multiple_recipients():
    c = parse_excel(modified('Mensajes', 'C2', 'MARCO, CLARA'))
    assert c['Mensajes'][0]['recipients'] == ['MARCO', 'CLARA']


def test_invalid_file():
    with pytest.raises(InvalidWorkbook, match='Archivo, fila 1'):
        parse_excel(b'not an excel')
