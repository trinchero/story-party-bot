"""No automatic retries: a timeout cannot prove whether Telegram accepted a send."""
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError


async def send_next(store, bot, mid, retry=False):
    with store.transaction():
        message = store.claim(mid, retry)
        store.bump('send_attempt', mid)
    for delivery in store.deliveries(mid):
        if delivery['status'] not in ('pending', 'failed'):
            continue
        with store.transaction():
            store.db.execute("UPDATE deliveries SET status='sending',error=NULL WHERE id=?", (delivery['id'],))
        try:
            sent = await bot.send_message(chat_id=delivery['player'], text=message['body'], protect_content=True)
        except (Forbidden, BadRequest, RetryAfter) as exc:
            # Do not persist raw exception strings: they may contain sensitive data.
            with store.transaction():
                store.db.execute("UPDATE deliveries SET status='failed',error=? WHERE id=?", (type(exc).__name__, delivery['id']))
            return
        except (TelegramError, OSError, TimeoutError):
            with store.transaction():
                store.db.execute("UPDATE deliveries SET status='uncertain',error='Respuesta no confirmada' WHERE id=?", (delivery['id'],))
            return
        except Exception:
            with store.transaction():
                store.db.execute("UPDATE deliveries SET status='uncertain',error='Error inesperado; verificar entrega' WHERE id=?", (delivery['id'],))
            return
        with store.transaction():
            store.db.execute("UPDATE deliveries SET status='sent',telegram_id=?,error=NULL WHERE id=?", (sent.message_id, delivery['id']))
            store.refresh(mid)
