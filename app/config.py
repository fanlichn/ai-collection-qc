from pydantic_settings import BaseSettings, SettingsConfigDict

COMPARISON_MODEL = 'Qwen/Qwen3-ASR-1.7B'

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    app_name: str = 'AI Collection QA'
    admin_user: str = 'admin'
    admin_password: str = 'change-me-now'
    secret_key: str = 'replace-with-a-long-random-secret'
    database_url: str = 'mysql+pymysql://qc:qc_password@mysql:3306/collection_qc?charset=utf8mb4'
    oss_endpoint: str = 'https://oss-ap-southeast-1.aliyuncs.com'
    oss_bucket: str = 'lak-audio'
    oss_access_key_id: str = ''
    oss_access_key_secret: str = ''
    oss_prefix: str = ''
    oss_scan_interval: int = 60
    oss_start_after: str = ''
    audio_tmp_dir: str = '/data/audio'
    whisper_model: str = 'small'
    whisper_device: str = 'cuda'
    whisper_compute_type: str = 'float16'
    whisper_beam_size: int = 5
    whisper_language: str = ''  # blank = auto detect; si/en/ta/zh supported by Whisper
    deepseek_base_url: str = 'https://api.deepseek.com'
    deepseek_api_key: str = ''
    deepseek_model: str = 'deepseek-flash'
    max_audio_mb: int = 200
    worker_poll_seconds: int = 10
    cors_origins: str = ''

settings = Settings()
