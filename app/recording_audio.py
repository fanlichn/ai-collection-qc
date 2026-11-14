from botocore.exceptions import ClientError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Recording
from .oss import client


def resolve_audio_key(db: Session, recording: Recording) -> str:
    """Use an exact content match if the original OSS key is no longer present."""
    s3 = client()
    try:
        s3.head_object(Bucket=settings.oss_bucket, Key=recording.object_key)
        return recording.object_key
    except ClientError as exc:
        if exc.response['ResponseMetadata']['HTTPStatusCode'] != 404 or not recording.etag:
            raise
        missing = exc

    matches = db.scalars(select(Recording.object_key).where(
        Recording.id != recording.id, Recording.etag == recording.etag,
        Recording.size_bytes == recording.size_bytes,
    ).order_by(Recording.id))
    for key in matches:
        try:
            metadata = s3.head_object(Bucket=settings.oss_bucket, Key=key)
        except ClientError as exc:
            if exc.response['ResponseMetadata']['HTTPStatusCode'] != 404:
                raise
            continue
        if (metadata['ETag'].strip('"') == recording.etag
                and metadata['ContentLength'] == recording.size_bytes):
            return key
    raise missing
