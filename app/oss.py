import re
from urllib.parse import urlsplit, urlunsplit

import boto3
from botocore.config import Config
from .config import settings

AUDIO_EXTS = ('.mp3','.m4a','.amr','.aac','.wav','.ogg','.opus','.3gp','.flac','.wma')
REGIONAL_OSS_HOST = re.compile(r'(?:s3\.)?(oss-[a-z]{2}(?:-[a-z0-9]+)+)\.aliyuncs\.com')


def _service_endpoint(*, public: bool = False) -> str:
    endpoint = urlsplit(settings.oss_endpoint.strip())
    host = endpoint.hostname
    if (endpoint.scheme not in ('http', 'https') or not host or endpoint.username is not None
            or endpoint.path not in ('', '/') or endpoint.query or endpoint.fragment):
        raise ValueError('OSS_ENDPOINT must be an HTTP(S) service endpoint without credentials or a path')
    if host.startswith(f'{settings.oss_bucket.lower()}.'):
        raise ValueError('OSS_ENDPOINT must be the service endpoint without the OSS_BUCKET prefix')

    regional_host = REGIONAL_OSS_HOST.fullmatch(host)
    if regional_host:
        service = regional_host[1]
        if public:
            service = service.removesuffix('-internal')
        host = f's3.{service}.aliyuncs.com'
        if endpoint.port is not None:
            host = f'{host}:{endpoint.port}'
    else:
        host = endpoint.netloc
    return urlunsplit((endpoint.scheme, host, '', '', ''))


def client(*, public: bool = False):
    if not settings.oss_access_key_id or not settings.oss_access_key_secret:
        raise RuntimeError('OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET not configured')
    return boto3.client(
        's3',
        endpoint_url=_service_endpoint(public=public),
        aws_access_key_id=settings.oss_access_key_id,
        aws_secret_access_key=settings.oss_access_key_secret,
        config=Config(
            # Alibaba Cloud documents S3 Signature V2 for boto3 compatibility.
            signature_version='s3',
            s3={'addressing_style': 'virtual'},
            retries={'max_attempts': 5},
        ),
    )

def iter_audio_objects():
    s3 = client()
    paginator = s3.get_paginator('list_objects_v2')
    kwargs = {'Bucket': settings.oss_bucket, 'Prefix': settings.oss_prefix}
    if settings.oss_start_after:
        kwargs['StartAfter'] = settings.oss_start_after
    for page in paginator.paginate(**kwargs):
        for obj in page.get('Contents', []):
            key = obj['Key']
            if key.lower().endswith(AUDIO_EXTS) and obj.get('Size', 0) > 0:
                yield {'key': key, 'size': obj['Size'], 'etag': obj.get('ETag','').strip('"'), 'last_modified': obj.get('LastModified')}

def download_object(key: str, destination: str):
    client().download_file(settings.oss_bucket, key, destination)


def presigned_audio_url(key: str, expires: int = 300):
    return client(public=True).generate_presigned_url(
        'get_object', Params={'Bucket': settings.oss_bucket, 'Key': key}, ExpiresIn=expires,
    )
