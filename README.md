# AI 智能催收质检平台 MVP 1.0

本项目对接现有 Auto.js 录音上传 APK，不修改 APK。它按 APK 当前 OSS 对象 Key 读取录音：

`{deviceId}/{YYYY-MM-DD}/{filename}`

默认 Bucket/Region：`lak-audio` / `ap-southeast-1`。代码来源：用户提供的 `call-recording-feishu-v2`，其中 `buildOssKey(file)` 返回 `deviceId + "/" + fmtDate(file.mtime) + "/" + file.name`。

## 当前包含
- OSS 分页扫描、对象去重、录音下载
- faster-whisper 自动语言检测（Sinhala / English / Tamil / Chinese 由 Whisper 自动检测）
- 逐段时间戳转录
- 规则初筛与可选 DeepSeek 语义质检。配置 `DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL` 和 `DEEPSEEK_API_KEY` 后，新任务会发送转录文字进行分析。
- 评分、风险队列、人工复核、OSS 短时签名 URL 录音播放、失败任务手动重试
- Web 看板、录音列表、转录详情、员工-设备绑定、CSV 导出
- MySQL 持久化、数据库轮询任务队列，Docker Compose 部署

## 重要边界
1. 本版不做可靠的说话人分离。Whisper 段落 speaker 标记为 UNKNOWN；需要后续增加 pyannote/其他 diarization 模型并用双声道/真实通话样本验证。
2. 规则库只是可配置起点，Sinhala/Tamil 违规表达覆盖率未经业务验证。必须由当地合规人员提供政策并审核。
3. LLM 未配置时只运行规则初筛，不会伪装成完整语义理解。配置 LLM 后才启用模型分析。
4. AI 分数/违规不能单独作为员工处罚或法律结论；所有高风险和低置信度项需人工复核。
5. Whisper 多语言支持不代表四种语言识别准确率已经验收。应分别准备经授权、脱敏的 Sinhala/English/Tamil/Mandarin 样本测试。
6. 当前管理后台使用 HTTP Basic Auth，必须放在 HTTPS 反向代理后，强密码、限制访问来源。录音播放通过 5 分钟 OSS 签名 URL 返回。

## 部署前提
- Linux x86_64，Docker Engine + Docker Compose Plugin
- NVIDIA T4，驱动已安装；`nvidia-smi` 正常
- NVIDIA Container Toolkit 已安装，`docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` 能看到 T4
- OSS RAM 用户仅授予 `lak-audio` Bucket 的 List/Get 权限

## 部署
```bash
unzip ai-collection-qc-mvp.zip
cd ai-collection-qc
cp .env.example .env
nano .env
# 必须填写密码和 OSS RAM Key。启用语义质检时再填写 DeepSeek 配置。

docker compose build
# 先验证 GPU 容器可见性
docker compose run --rm worker python3 -c "import ctranslate2; print('CUDA devices:', ctranslate2.get_cuda_device_count())"
# 启动
docker compose up -d
# 查看状态
docker compose ps
docker compose logs -f worker
curl http://127.0.0.1:8080/healthz
```

本机检查 `curl http://127.0.0.1:8080/healthz`。端口默认只绑定 127.0.0.1，不能直接从公网访问；正式使用按 `deploy/nginx.conf.example` 配置 Nginx + HTTPS，再通过域名登录。正式使用前按 `deploy/nginx.conf.example` 配置 Nginx + HTTPS，并限制 8080 管理端口公网访问。

## 第一次验证建议
1. 在 OSS 建一个专用测试前缀，例如 `qc-test/`，或将 `OSS_PREFIX` 设置成一个仅含 1-2 条已授权测试录音的目录。
2. 若测试对象仍保持 APK 原始 Key，则 `OSS_PREFIX` 留空；可先用专用测试 Bucket 更安全。
3. `docker compose logs -f worker` 应看到 Discovered / Completed。
4. 看板应出现 COMPLETED，点“查看”确认语言、时间戳、转录文本和质检 JSON。
5. 四种语言各准备至少 20-50 段有人工参考文本的录音，计算 WER/CER，逐一评估后再决定 small/medium/large-v3。

## OSS 对象路径兼容
APK 源码中：
```javascript
function buildOssKey(file) {
  return deviceId + "/" + fmtDate(file.mtime) + "/" + file.name;
}
```
本项目从 key 的第一级提取 device_id，最后一级提取文件名；支持分页扫描，不依赖 SLS 日志。

## 常见问题
- `CUDA devices: 0`：检查宿主机驱动、NVIDIA Container Toolkit、Docker GPU runtime。
- CUDA/cuDNN 加载失败：worker 会退回 CPU int8，速度会明显下降；检查容器内 CUDA/cuDNN 兼容。
- OSS 403：RAM 用户需要 `oss:ListObjects`/`oss:GetObject` 对目标 Bucket/前缀授权；确认 endpoint 与 Bucket 所在地域一致。
- 无新录音：确认 OSS_PREFIX、Bucket、对象后缀；APK 当前上传路径是 deviceId/date/filename。
- 语言误判：不要硬编码一种语言；先自动检测，复核 `detected_language`，再根据语料评测模型。
- 处理旧录音：默认扫描整个 Bucket。首次上线建议先配置测试前缀，避免一启动就批量处理历史数据。

## 后续生产化待办
- 增加 OSS 事件通知代替全量轮询、死信队列与任务租约
- 增加 pyannote 说话人分离并验证客服/客户声道映射
- 员工登录、RBAC、租户隔离、审计日志、密码哈希、MFA
- 录音在线播放使用短时签名 URL；当前后台不提供录音播放链接
- 规则管理 CRUD、政策版本、抽检与人工复核工作流
- 敏感信息脱敏、保留期/删除策略、数据加密和备份恢复演练
- 单条录音重跑、失败重试次数上限、告警和 GPU 并发队列
