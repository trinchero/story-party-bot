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
    ('Personajes', 2, 0, 'VERA', 'Nombre único'),
    ('Mensajes', 1, 2, 'INES', 'nombres existentes'),
    ('Mensajes', 1, 3, '', 'completa Texto'),
    ('Mensajes', 1, 1, 2, 'sin saltos'),
    ('Fases', 1, 0, 1.5, 'entero positivo'),
    ('Personajes', 0, 0, 'Wrong', 'columnas'),
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


def test_minimal_model_and_no_generated_cards(tmp_path):
    from narrative_bot.store import Store
    doc = Document(DEMO)
    assert [sheet.name for sheet in doc.sheets] == ['Personajes', 'Fases', 'Mensajes']
    content = parse_numbers(DEMO.read_bytes())
    assert 'Ficha privada' not in content['Personajes'][0]
    assert content['Guia'] == []
    assert content['Mensajes'][0]['Título admin'] == 'CINE AURORA'
    store = Store(tmp_path / 'minimal.db')
    try:
        with store.transaction():
            store.new_game(store.draft('Prueba', content))
            for player, character in enumerate(content['Personajes'], 101):
                store.register(player, character['Nombre'])
                store.assign(character['Código'], player)
            store.authorize_cards(prepare_cards=False)
        assert store.messages() == []
        with store.transaction():
            store.advance()
        assert store.next_message()['body'] == content['Mensajes'][0]['Texto']
    finally:
        store.db.close()


@pytest.mark.parametrize('name', ['TODOS', 'Vera, Bruno', '  '])
def test_reject_invalid_character_name(tmp_path, name):
    doc = Document(DEMO)
    doc.sheets['Personajes'].tables[0].write(1, 0, name)
    path = tmp_path / 'invalid-name.numbers'
    doc.save(path)
    with pytest.raises(InvalidWorkbook):
        parse_numbers(path.read_bytes())


def test_names_with_accents_spaces_and_multiple_recipients(tmp_path):
    doc = Document(DEMO)
    doc.sheets['Personajes'].tables[0].write(1, 0, 'María José')
    table = doc.sheets['Mensajes'].tables[0]
    for i, row in enumerate(table.rows(values_only=True)[1:], 1):
        if row[2] == 'Vera':
            table.write(i, 2, 'maría josé, BRUNO')
    path = tmp_path / 'names.numbers'
    doc.save(path)
    content = parse_numbers(path.read_bytes())
    code = content['Personajes'][0]['Código']
    assert any(m['recipients'] == [code, 'BRUNO'] for m in content['Mensajes'])


def test_planned_person_optional_and_does_not_assign(tmp_path):
    from narrative_bot.store import Store
    doc = Document(DEMO)
    table = doc.sheets['Personajes'].tables[0]
    table.write(1, 1, 'Andrea')
    path = tmp_path / 'planned.numbers'
    doc.save(path)
    content = parse_numbers(path.read_bytes())
    assert content['Personajes'][0]['Persona prevista'] == 'Andrea'
    assert content['Personajes'][1]['Persona prevista'] == ''
    store = Store(tmp_path / 'planned.db')
    try:
        with store.transaction():
            store.new_game(store.draft('Prueba', content))
        assert store.rows('SELECT * FROM assignments') == []
    finally:
        store.db.close()
