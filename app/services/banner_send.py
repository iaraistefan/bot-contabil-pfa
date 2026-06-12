"""
app/services/banner_send.py — trimitere unificată a bannerelor în Telegram.

Pattern validat (Declarația Unică, Raport, …): banner FOTO sus (hero) + textul
existent dedesubt, cu fallback pe 3 niveluri ca ecranul să NU pice NICIODATĂ:
  1. `build_banner` crapă       → rămâne mesajul text vechi (`edit_message_text`).
  2. delete mesaj vechi crapă   → trimitem foto+text ca mesaje NOI.
  3. send foto/text crapă       → doar textul.
Toate cele 3 niveluri logează cu `logger.exception` (stack complet — fără eșec orb).
"""
import logging

logger = logging.getLogger(__name__)


async def send_banner_or_text(
    query, context, *, screen, data, text, caption,
    reply_markup=None, parse_mode="Markdown",
):
    """Înlocuiește mesajul text (din callback) cu banner foto + text dedesubt.

    Butoanele (`reply_markup`) rămân pe mesajul TEXT (jos, accesibile). `caption`-ul
    foto = text simplu (fără Markdown). Pe orice eroare → fallback la text + log.
    """
    chat_id = query.message.chat_id

    # Nivel 1: build. Crapă → mesaj text INTACT (nimic încă șters).
    try:
        from app.contai_banners import build_banner
        png = build_banner(screen, data)
    except Exception:
        logger.exception(f"banner[{screen}] build a eșuat → fallback text")
        await query.edit_message_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
        return

    # Nivel 2: delete mesaj vechi. Crapă (mesaj vechi/șters) → trimitem ca mesaje NOI.
    try:
        await query.message.delete()
    except Exception:
        logger.exception(f"banner[{screen}] delete mesaj vechi a eșuat → trimit ca mesaje noi")

    # Nivel 3: foto + text. Crapă → doar text.
    try:
        await context.bot.send_photo(chat_id=chat_id, photo=png, caption=caption)
        await context.bot.send_message(
            chat_id=chat_id, text=text, parse_mode=parse_mode, reply_markup=reply_markup,
        )
    except Exception:
        logger.exception(f"banner[{screen}] send foto/text a eșuat → doar text")
        await context.bot.send_message(
            chat_id=chat_id, text=text, parse_mode=parse_mode, reply_markup=reply_markup,
        )


async def reply_banner_or_text(
    message, context, *, screen, data, text, caption,
    reply_markup=None, parse_mode="Markdown",
):
    """Variantă pentru cale de COMANDĂ (`update.message`, mesaj NOU — fără callback).

    Spre deosebire de `send_banner_or_text`: NU există mesaj de șters/editat, deci
    doar 2 niveluri de fallback (build / send). Butoanele (`reply_markup`) rămân pe
    mesajul TEXT. Reutilizabilă pe orice ecran lansat din comandă.
    """
    chat_id = message.chat_id

    # Nivel 1: build. Crapă → textul vechi (reply_text), nimic trimis.
    try:
        from app.contai_banners import build_banner
        png = build_banner(screen, data)
    except Exception:
        logger.exception(f"banner[{screen}] build a eșuat → fallback text")
        await message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
        return

    # Nivel 2: foto + text. Crapă → doar text.
    try:
        await context.bot.send_photo(chat_id=chat_id, photo=png, caption=caption)
        await context.bot.send_message(
            chat_id=chat_id, text=text, parse_mode=parse_mode, reply_markup=reply_markup,
        )
    except Exception:
        logger.exception(f"banner[{screen}] send foto/text a eșuat → doar text")
        await message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)


async def send_banner_photo(context, chat_id, *, screen, data, caption) -> bool:
    """Trimite DOAR banner-ul hero (foto), ADITIV — pentru ecrane unde livrabilul e
    altceva (ex. document Excel la Registru). Defensiv: orice eroare (build/send) →
    `logger.exception` + SARE bannerul (restul fluxului continuă neatins).
    Întoarce True dacă bannerul a plecat, False altfel.
    """
    try:
        from app.contai_banners import build_banner
        png = build_banner(screen, data)
        await context.bot.send_photo(chat_id=chat_id, photo=png, caption=caption)
        return True
    except Exception:
        logger.exception(f"banner[{screen}] photo a eșuat → sar bannerul (restul continuă)")
        return False
