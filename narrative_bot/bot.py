"""Telegram-only interface. Every admin entry point checks numeric identity."""
import asyncio
import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from .delivery import send_next
from .store import RuleError

LABELS = {'pending': 'pendiente', 'sent': 'aceptada por Telegram', 'failed': 'error',
          'uncertain': 'incierta', 'sending': 'en curso', 'skipped': 'saltado',
          'completed': 'completado', 'acknowledged': 'resuelta por el anfitrión de la casa'}


class Interface:
    def __init__(self, store, admin_id):
        self.store, self.admin_id = store, admin_id
        self.lock = asyncio.Lock()

    def allowed(self, update):
        return bool(update.effective_user and update.effective_chat
                    and update.effective_user.id == self.admin_id
                    and update.effective_chat.type == 'private')

    def keyboard(self, buttons):
        return InlineKeyboardMarkup([[InlineKeyboardButton(label[:100], callback_data=self.store.button(action, payload))]
                                     for label, action, payload in buttons])

    async def say(self, update, text, buttons=()):
        # Small plain-text chunks also handle arbitrarily long private admin notes.
        while text:
            chunk, text = text[:1800], text[1800:]
            await update.effective_message.reply_text(chunk, reply_markup=self.keyboard(buttons) if not text and buttons else None)

    async def start(self, update, context):
        if update.effective_chat.type != 'private':
            return
        async with self.lock:
            if self.allowed(update):
                await self.say(update, 'Hola, anfitrión de la casa. Abre el panel para preparar o dirigir la partida.',
                               [('Abrir control', 'control', '')])
            else:
                created = self.store.register(update.effective_user.id, update.effective_user.full_name)
                text = ('¡Bienvenido! El anfitrión de la casa puede asignarte un personaje.' if created
                        else 'Ya estás registrado. No necesitas volver a unirte.')
                await self.say(update, text + ' Espera aquí tus mensajes privados.\n'
                               f'Tu ID de Telegram: {update.effective_user.id}')

    async def control(self, update, context):
        if not self.allowed(update):
            if update.effective_chat.type == 'private':
                await self.say(update, 'Esta función es solo para el anfitrión de la casa.')
            return
        async with self.lock:
            await self.control_view(update)

    async def leave(self, update, context):
        if update.effective_chat.type != 'private':
            return
        async with self.lock:
            try:
                with self.store.transaction():
                    self.store.leave(update.effective_user.id)
            except RuleError as exc:
                return await self.say(update, str(exc))
            await self.say(update, 'Has salido de la lista de personas disponibles. El historial se conserva. Envía /start para volver. Tu rol de anfitrión, si lo tienes, no cambia.')

    def message_details(self, m):
        text = f"{m['position']}. {m['title']} → {m['recipients']} — {LABELS[m['status']]}"
        for d in self.store.deliveries(m['id']):
            if d['status'] != 'sent':
                text += f"\n  {d['code']}: {LABELS[d['status']]}"
                if d['error']:
                    text += f" ({d['error']})"
        return text

    async def control_view(self, update):
        g = self.store.game()
        if not g:
            await self.draft_view(update)
            return
        phase = g['phase']
        content = self.store.content()
        phase_name = content['Fases'][phase-1]['Título'] if phase else 'Preparación y fichas'
        r = self.store.report()
        text = (f"Partida #{g['id']}: {g['title']}\nFase {phase}: {phase_name}\n"
                f"Estado: {'finalizada' if g['status'] == 'finished' else 'en preparación' if not phase else 'activa'}\n"
                f"Mensajes completados: {r['completed']}/{r['messages']} · Saltados: {r['skipped']}\n"
                f"Entregas aceptadas por Telegram: {r['sent']}/{r['deliveries']}\n"
                f"Entregas resueltas por el anfitrión de la casa sin confirmación Telegram: {r['acknowledged']}\n"
                '«Enviado» no significa leído. Las fichas se cuentan aparte, en fase 0.\n')
        if phase:
            text += '\nNotas privadas de fase: ' + content['Fases'][phase-1]['Notas admin'] + '\n'
        for m in self.store.messages():
            text += '\n' + self.message_details(m) + '\n'
        buttons = [('Jugadores', 'players', ''), ('Guía privada', 'guide', ''), ('Historial de fases', 'history', '')]
        if g['status'] != 'finished':
            buttons.append(('Interrumpir y reiniciar partida', 'restart_confirm', ''))
            if not g['cards']:
                buttons.append(('Autorizar fichas privadas', 'cards_confirm', ''))
                buttons.append(('Descartar preparación…', 'cancel_preparation_confirm', ''))
            m = self.store.next_message()
            if m:
                buttons.extend([('Vista previa del próximo', 'preview', str(m['id'])),
                                ('Enviar próximo', 'send', str(m['id'])),
                                ('Reintentar pendientes', 'retry', str(m['id'])),
                                ('Saltar mensaje…', 'skip_confirm', str(m['id']))])
                uncertain = [d for d in self.store.deliveries(m['id']) if d['status'] == 'uncertain']
                for d in uncertain[:15]:
                    buttons.append((f"Resolver entrega incierta: {d['code']}", 'resolve_confirm', str(d['id'])))
            if g['cards']:
                label = 'Finalizar partida…' if phase == len(content['Fases']) else 'Iniciar fase siguiente…'
                buttons.append((label, 'advance_confirm', ''))
        else:
            text += '\nEl responsable técnico prepara las nuevas historias.'
            buttons.append(('Reiniciar partida', 'restart_confirm', ''))
        await self.say(update, text, buttons)
        if g['status'] == 'finished':
            await self.draft_view(update)

    async def upload(self, update, context):
        # Files sent in Telegram are never downloaded or imported.
        if update.effective_chat.type == 'private':
            await self.say(update, 'Los archivos Numbers los prepara el responsable técnico fuera de Telegram. Usa /control si eres el anfitrión de la casa.')

    async def draft_view(self, update):
        drafts = self.store.rows('SELECT * FROM drafts ORDER BY rowid DESC LIMIT 1')
        if not drafts:
            await self.say(update, 'El responsable técnico debe importar la historia. Cuando esté lista, abre /control.')
            return
        draft = drafts[0]
        content = json.loads(draft['content'])
        await self.say(update, f"Historia preparada por el responsable técnico: {draft['title']}\n"
                       f"Personajes: {len(content['Personajes'])}\nFases: {len(content['Fases'])}\n"
                       f"Mensajes: {len(content['Mensajes'])}\n"
                       + ', '.join(r['Código'] for r in content['Personajes'])
                       + '\nLa guía y las notas son privadas. Confirmar prepara la partida; no envía mensajes.',
                       [('Confirmar partida', 'import', draft['id']), ('Rechazar preparación', 'cancel_import', draft['id'])])

    async def players_view(self, update, offset=0):
        g = self.store.game()
        assigned = {r['code']: r for r in self.store.assignments()}
        characters = self.store.content()['Personajes']
        text = 'Jugadores y personajes:\n' + '\n'.join(
            f"{r['Código']} — {r['Nombre']}: " + (assigned[r['Código']]['name'] if r['Código'] in assigned else 'sin asignar')
            for r in characters)
        buttons = []
        if not g['cards'] and g['status'] == 'preparing':
            for i, r in enumerate(characters[offset:offset+15], offset):
                code = r['Código']
                buttons.append((f"{'Liberar' if code in assigned else 'Asignar'} {code}",
                                'unassign' if code in assigned else 'choose_player', str(i)))
            if offset + 15 < len(characters):
                buttons.append(('Más personajes', 'players', str(offset+15)))
        else:
            text += '\nAsignaciones bloqueadas.'
        buttons.append(('Volver al control', 'control', ''))
        await self.say(update, text, buttons)

    async def choose_player(self, update, index, offset=0):
        players = self.store.rows('SELECT * FROM players WHERE id NOT IN (SELECT player FROM withdrawn_players) AND id NOT IN (SELECT player FROM assignments WHERE game=?) ORDER BY id LIMIT 16 OFFSET ?',
                                 (self.store.game()['id'], offset))
        buttons = [(f"{r['name']} · {r['id']}", 'assign', f"{index}:{r['id']}") for r in players[:15]]
        if len(players) > 15:
            buttons.append(('Más jugadores', 'choose_player', f'{index}:{offset+15}'))
        buttons.append(('Volver', 'players', ''))
        await self.say(update, 'Elige al jugador. Si no aparece, debe enviar /start al bot.', buttons)

    async def callback(self, update, context):
        query = update.callback_query
        if not self.allowed(update):
            await query.answer('Solo el anfitrión de la casa puede usar estos botones.', show_alert=True)
            return
        await query.answer()
        async with self.lock:
            try:
                with self.store.transaction():
                    action, payload = self.store.consume(query.data)
                await self.dispatch(update, context, action, payload)
            except (RuleError, ValueError) as exc:
                await self.say(update, str(exc) if isinstance(exc, RuleError) else 'Acción inválida. Abre /control.')

    async def dispatch(self, update, context, action, payload):
        s = self.store
        if action == 'control':
            return await self.control_view(update)
        if action == 'players':
            return await self.players_view(update, int(payload or 0))
        if action == 'choose_player':
            values = payload.split(':')
            return await self.choose_player(update, int(values[0]), int(values[1]) if len(values) > 1 else 0)
        if action == 'guide':
            return await self.say(update, '\n\n'.join(r['Campo'] + ': ' + r['Contenido'] for r in s.content()['Guia']), [('Volver', 'control', '')])
        if action == 'history':
            for phase in range(s.game()['phase'] + 1):
                await self.say(update, f'Fase {phase}\n' + '\n'.join(self.message_details(m) for m in s.messages(phase)))
            return await self.control_view(update)
        if action == 'preview':
            m = s.next_message()
            if not m or m['id'] != int(payload):
                raise RuleError('Este mensaje ya no es el próximo.')
            notes = next((r['Notas admin'] for r in s.content()['Mensajes']
                          if r['Fase'] == m['phase'] and r['Orden'] == m['position']), '')
            return await self.say(update, f"Vista previa privada · {m['title']}\nPara: {m['recipients']}\n\n{m['body']}\n\nNotas admin: {notes}",
                                  [('Enviar este mensaje', 'send', payload), ('Volver', 'control', '')])
        if action == 'restart_confirm':
            question = ('¿Empezar otra partida con la misma historia?\n' if s.game()['status'] == 'finished'
                        else '¿Interrumpir esta partida y empezar otra con la misma historia?\n')
            text = (question +
                    'Todos los personajes quedarán libres. Los jugadores seguirán registrados. '
                    'Tendrás que asignarlos y autorizar las fichas de nuevo.\n'
                    'No se enviará ningún mensaje. Los mensajes ya recibidos permanecerán en las chats. '
                    'La partida anterior y sus entregas se conservarán en el registro.\n')
            incomplete = s.incomplete()
            if incomplete:
                text += '\nSe marcarán como saltados estos mensajes incompletos:\n'
                text += '\n'.join(self.message_details(m) for m in incomplete)
            label = 'Sí, reiniciar' if s.game()['status'] == 'finished' else 'Sí, interrumpir y reiniciar'
            return await self.say(update, text, [(label, 'restart', ''),
                                                 ('Cancelar', 'control', '')])
        if action == 'cards_confirm':
            return await self.say(update, '¿Autorizas las fichas privadas? Se bloquearán las asignaciones. Después usa «Enviar próximo» para entregar cada ficha.',
                                  [('Sí, autorizar fichas', 'cards', ''), ('Cancelar', 'control', '')])
        if action == 'cancel_preparation_confirm':
            return await self.say(update, '¿Descartar esta preparación? Se conservará en el historial. El responsable técnico podrá importar otra historia.',
                                  [('Sí, descartar preparación', 'cancel_preparation', ''), ('Volver', 'control', '')])
        if action == 'skip_confirm':
            m = s.next_message()
            if not m or m['id'] != int(payload):
                raise RuleError('El mensaje ya no es el próximo.')
            return await self.say(update, '¿Saltar este mensaje? Se conservarán las entregas y sus errores:\n' + self.message_details(m),
                                  [('Sí, saltar mensaje', 'skip', payload), ('Cancelar', 'control', '')])
        if action == 'advance_confirm':
            incomplete = s.incomplete()
            text = '¿Cerrar esta fase e iniciar la siguiente (o finalizar si es la última)? No se enviará ningún mensaje.\n'
            text += ('Los mensajes incompletos quedarán registrados como saltados:\n' + '\n'.join(self.message_details(m) for m in incomplete)) if incomplete else 'No hay envíos incompletos.'
            return await self.say(update, text, [('Sí, cerrar y continuar', 'advance', ''), ('Cancelar', 'control', '')])
        if action == 'resolve_confirm':
            return await self.say(update, 'Telegram no confirmó esta entrega. Consulta al jugador antes de decidir.\n'
                                  '«Dar por resuelta» permite continuar, sin contar una aceptación Telegram.\n'
                                  '«Permitir reintento» puede duplicar el mensaje si ya llegó; después pulsa Reintentar pendientes.',
                                  [('Dar por resuelta sin reenviar', 'resolve_ack', payload),
                                   ('Permitir reintento (posible duplicado)', 'resolve_retry', payload), ('Cancelar', 'control', '')])
        if action in ('send', 'retry'):
            await send_next(s, context.bot, int(payload), retry=action == 'retry')
        else:
            with s.operation(), s.transaction():
                if action == 'import':
                    s.new_game(payload)
                elif action == 'cancel_import':
                    s.db.execute('DELETE FROM drafts WHERE id=?', (payload,))
                elif action == 'assign':
                    index, uid = map(int, payload.split(':'))
                    if uid == self.admin_id:
                        raise RuleError('El anfitrión de la casa es el organizador, no un personaje.')
                    s.assign(s.content()['Personajes'][index]['Código'], uid)
                elif action == 'unassign':
                    s.unassign(s.content()['Personajes'][int(payload)]['Código'])
                elif action == 'cards':
                    s.authorize_cards()
                elif action == 'restart':
                    s.restart()
                elif action == 'cancel_preparation':
                    s.cancel_preparation()
                elif action == 'advance':
                    s.advance(confirmed=True)
                elif action == 'skip':
                    s.skip(int(payload))
                elif action in ('resolve_ack', 'resolve_retry'):
                    s.resolve(int(payload), retry=action == 'resolve_retry')
                else:
                    raise RuleError('Acción desconocida. Abre /control.')
        await self.control_view(update)


def build_application(token, admin_id, store):
    ui = Interface(store, admin_id)
    app = Application.builder().token(token).concurrent_updates(False).build()
    # A single handler accepts both /start and deep-link payloads (/start join).
    app.add_handler(CommandHandler('start', ui.start))
    app.add_handler(CommandHandler('leave', ui.leave))
    app.add_handler(CommandHandler('control', ui.control))
    app.add_handler(CallbackQueryHandler(ui.callback))
    app.add_handler(MessageHandler(filters.Document.ALL, ui.upload))

    async def error_handler(update, context):
        # Deliberately omit exception repr, request URL, Numbers content and user data.
        import logging
        logging.getLogger(__name__).error('Error de operación: %s', type(context.error).__name__)
        if update and ui.allowed(update):
            try:
                await ui.say(update, 'La operación se interrumpió. Abre /control para comprobar el estado antes de continuar.')
            except Exception:
                pass

    app.add_error_handler(error_handler)
    return app
