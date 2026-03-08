"""诊断脚本：直接测试阿里云 NLS Token API"""
import asyncio, sys, os
# 设置代理（开发环境需要，生产环境不设置此变量）
os.environ.setdefault("HTTPS_PROXY", "http://10.144.1.10:8080")
sys.path.insert(0, '.')
from config.settings import get_settings
from adapters.aliyun_asr import AliyunASRAdapter

s = get_settings()

async def main():
    adapter = AliyunASRAdapter(s.ALIYUN_ACCESS_KEY, s.ALIYUN_ACCESS_SECRET, s.ALIYUN_REGION)
    print(f"AppKey : {s.ALIYUN_ACCESS_KEY}")
    print(f"Secret : {s.ALIYUN_ACCESS_SECRET[:4]}...{s.ALIYUN_ACCESS_SECRET[-4:]}")
    print(f"Proxy  : {adapter._proxy}")
    print()
    try:
        token = await adapter._get_token()
        print(f"Token OK: {token[:12]}...")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nToken FAIL: {type(e).__name__}: {e}")

asyncio.run(main())
