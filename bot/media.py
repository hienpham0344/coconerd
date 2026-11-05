"""Capture Discord metadata without fetching links or interpreting attachments."""


def attachment_payloads(message) -> list[dict]:
    return [
        {
            "id": str(item.id),
            "filename": item.filename,
            "url": item.url,
            "content_type": item.content_type,
            "size": item.size,
            "spoiler": item.is_spoiler(),
        }
        for item in getattr(message, "attachments", ())
    ]
