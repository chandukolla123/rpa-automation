"""
IMAP email reader — polls an inbox and saves invoice attachments
into the watched inbox folder for processing.
"""
import email
import logging
from datetime import datetime
from pathlib import Path

from config import config

logger = logging.getLogger(__name__)

INVOICE_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
}


class IMAPInvoiceReader:
    """
    Connects to an IMAP mailbox, downloads invoice attachments, and
    saves them to the inbox directory for the file watcher to pick up.

    Requires imapclient: `pip install imapclient`
    """

    def __init__(self):
        self.host = config.IMAP_HOST
        self.port = config.IMAP_PORT
        self.user = config.IMAP_USER
        self.password = config.IMAP_PASSWORD
        self.folder = config.IMAP_FOLDER
        self.inbox_dir = config.INBOX_DIR

    def poll(self) -> int:
        """Download new invoice attachments. Returns count saved."""
        if not self.host or not self.user:
            logger.debug("IMAP not configured, skipping email poll.")
            return 0

        try:
            from imapclient import IMAPClient
        except ImportError:
            logger.warning("imapclient not installed. Email polling disabled.")
            return 0

        saved = 0
        try:
            with IMAPClient(self.host, port=self.port, ssl=True) as client:
                client.login(self.user, self.password)
                client.select_folder(self.folder)

                uids = client.search(["UNSEEN"])
                logger.info("Found %d unseen emails.", len(uids))

                for uid in uids:
                    data = client.fetch([uid], ["RFC822"])
                    raw = data[uid][b"RFC822"]
                    msg = email.message_from_bytes(raw)
                    saved += self._save_attachments(msg, uid)
                    client.set_flags([uid], [r"\Seen"])

        except Exception as exc:
            logger.error("IMAP poll error: %s", exc)

        return saved

    def _save_attachments(self, msg: email.message.Message, uid: int) -> int:
        saved = 0
        for part in msg.walk():
            content_type = part.get_content_type()
            filename = part.get_filename()

            if not filename:
                continue
            if content_type not in INVOICE_MIME_TYPES:
                continue

            payload = part.get_payload(decode=True)
            if not payload:
                continue

            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            safe_name = f"email_{uid}_{ts}_{filename}"
            dest = self.inbox_dir / safe_name
            dest.write_bytes(payload)
            logger.info("Saved email attachment: %s", safe_name)
            saved += 1

        return saved
