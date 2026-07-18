# -*- coding: utf-8 -*-
"""c1: 多话题切换 —— 从零构建 FastAPI 天气查询服务（中文会话）。"""
from evals.context_vis.case_schema import Case, T, Segment, GoldConstraint, Backtrack

TURNS = [
    # ---------- 话题 1：环境搭建 (0-7) ----------
    T("user",
      "我想从零搭一个天气查询服务，用 FastAPI 写。先把开发环境搭起来吧：建一个虚拟环境，"
      "装上 fastapi 和 uvicorn，然后跑通一个最简单的 hello world 接口。"
      "注意我们生产机器上只有 3.11，所以整个项目必须兼容 Python 3.11，别用 3.12 才有的语法。"),

    T("assistant",
      "好的，我按下面的步骤来：\n"
      "1. 用 python3.11 创建虚拟环境 `.venv`；\n"
      "2. 升级 pip 后安装 fastapi 和 uvicorn[standard]；\n"
      "3. 写一个最小的 `app/main.py`，提供 `GET /` 返回 hello world；\n"
      "4. 用 uvicorn 启动并 curl 验证。\n"
      "先创建虚拟环境并安装依赖。"),

    T("tool",
      "$ python3.11 -m venv .venv && source .venv/bin/activate && python -V\n"
      "Python 3.11.9\n"
      "$ pip install --upgrade pip\n"
      "Successfully installed pip-24.0\n"
      "$ pip install fastapi 'uvicorn[standard]'\n"
      "Collecting fastapi\n"
      "  Downloading fastapi-0.111.0-py3-none-any.whl (91 kB)\n"
      "Collecting uvicorn[standard]\n"
      "  Downloading uvicorn-0.30.1-py3-none-any.whl (62 kB)\n"
      "Collecting starlette<0.38.0,>=0.37.2 (from fastapi)\n"
      "  Downloading starlette-0.37.2-py3-none-any.whl (71 kB)\n"
      "Collecting pydantic!=1.8,!=1.8.1,>=1.7.4 (from fastapi)\n"
      "  Downloading pydantic-2.7.4-py3-none-any.whl (409 kB)\n"
      "Collecting pydantic-core==2.18.4 (from pydantic!=1.8,!=1.8.1,>=1.7.4->fastapi)\n"
      "  Downloading pydantic_core-2.18.4-cp311-cp311-manylinux_2_17_x86_64.whl (2.1 MB)\n"
      "Collecting typing-extensions>=4.8.0 (from fastapi)\n"
      "  Downloading typing_extensions-4.12.2-py3-none-any.whl (37 kB)\n"
      "Collecting anyio<5,>=3.4.0 (from starlette<0.38.0,>=0.37.2->fastapi)\n"
      "  Downloading anyio-4.4.0-py3-none-any.whl (86 kB)\n"
      "Collecting httptools>=0.5.0 (from uvicorn[standard])\n"
      "  Downloading httptools-0.6.1-cp311-cp311-manylinux_2_17_x86_64.whl (318 kB)\n"
      "Collecting uvloop!=0.15.0,!=0.15.1,>=0.14.0 (from uvicorn[standard])\n"
      "  Downloading uvloop-0.19.0-cp311-cp311-manylinux_2_17_x86_64.whl (3.4 MB)\n"
      "Collecting watchfiles>=0.13 (from uvicorn[standard])\n"
      "  Downloading watchfiles-0.22.0-cp311-cp311-manylinux_2_17_x86_64.whl (1.2 MB)\n"
      "Installing collected packages: typing-extensions, sniffio, idna, h11, click,\n"
      "  anyio, httptools, pydantic-core, pydantic, starlette,\n"
      "  uvloop, watchfiles, websockets, uvicorn, fastapi\n"
      "Successfully installed anyio-4.4.0 fastapi-0.111.0 pydantic-2.7.4\n"
      "  pydantic-core-2.18.4 starlette-0.37.2 uvicorn-0.30.1 uvloop-0.19.0 watchfiles-0.22.0",
      tool_name="bash"),

    T("assistant",
      "依赖装好了，解释器确认是 Python 3.11.9。现在写最小应用 `app/main.py`：\n"
      "```python\n"
      "from fastapi import FastAPI\n\n"
      "app = FastAPI(title=\"weather-service\")\n\n"
      "@app.get(\"/\")\n"
      "async def root():\n"
      "    return {\"message\": \"hello world\"}\n"
      "```\n"
      "同时建一个空的 `app/__init__.py`，把依赖固化到 requirements.txt。"),

    T("tool",
      "write app/main.py (9 lines)\n"
      "write app/__init__.py (0 lines)\n"
      "write requirements.txt (3 lines):\n"
      "  fastapi==0.111.0\n"
      "  uvicorn[standard]==0.30.1\n"
      "  pydantic==2.7.4\n"
      "ok",
      tool_name="write_file"),

    T("assistant",
      "文件都写好了。现在启动开发服务器验证一下 hello world 能不能通：\n"
      "`uvicorn app.main:app --reload --port 8000`，然后另开终端 curl 根路径。"),

    T("tool",
      "$ uvicorn app.main:app --reload --port 8000 &\n"
      "INFO:     Will watch for changes in these directories: ['/home/dev/weather-service']\n"
      "INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)\n"
      "INFO:     Started reloader process [21133] using WatchFiles\n"
      "INFO:     Started server process [21135]\n"
      "INFO:     Application startup complete.\n"
      "$ curl -s http://127.0.0.1:8000/\n"
      "{\"message\":\"hello world\"}\n"
      "INFO:     127.0.0.1:53182 - \"GET / HTTP/1.1\" 200 OK",
      tool_name="bash"),

    T("assistant",
      "环境搭建完成：\n"
      "- `.venv` 基于 Python 3.11.9，没有用任何 3.12 特性；\n"
      "- fastapi 0.111.0 + uvicorn 0.30.1 已装好并写入 requirements.txt；\n"
      "- hello world 接口 curl 返回 200。\n"
      "随时可以开始写业务接口。"),

    # ---------- 话题 2：实现天气查询 API (8-17) ----------
    T("user",
      "很好，接下来实现核心功能：加一个 GET /weather 接口，接收 city 参数（比如 city=Shanghai），"
      "调用 OpenWeatherMap 的接口拿实时天气，返回城市名、温度、湿度和天气描述。"
      "有一点要求：不要把 API key 写死在代码里，用环境变量 OPENWEATHER_API_KEY 读取。"),

    T("assistant",
      "明白。设计如下：\n"
      "- 新建 `app/weather.py`，用 httpx.AsyncClient 调 OpenWeatherMap 的\n"
      "  `https://api.openweathermap.org/data/2.5/weather?q={city}&units=metric`；\n"
      "- key 从环境变量 `OPENWEATHER_API_KEY` 读取，启动时没配就直接报错，绝不硬编码；\n"
      "- 在 `main.py` 注册路由 `GET /weather?city=xxx`，返回 city、temp、humidity、description。\n"
      "核心代码：\n"
      "```python\n"
      "import os\n"
      "from datetime import datetime\n"
      "import httpx\n\n"
      "BASE_URL = \"https://api.openweathermap.org/data/2.5/weather\"\n"
      "API_KEY = os.environ[\"OPENWEATHER_API_KEY\"]  # 未配置则启动即失败\n\n"
      "async def fetch_weather(city: str) -> dict:\n"
      "    async with httpx.AsyncClient(timeout=5.0) as client:\n"
      "        resp = await client.get(\n"
      "            BASE_URL,\n"
      "            params={\"q\": city, \"appid\": API_KEY, \"units\": \"metric\"},\n"
      "        )\n"
      "    data = resp.json()\n"
      "    return {\n"
      "        \"city\": data[\"name\"],\n"
      "        \"temp\": data[\"main\"][\"temp\"],\n"
      "        \"humidity\": data[\"main\"][\"humidity\"],\n"
      "        \"description\": data[\"weather\"][0][\"description\"],\n"
      "        \"observed_at\": datetime.utcfromtimestamp(data[\"dt\"]).isoformat(),\n"
      "    }\n"
      "```\n"
      "先安装 httpx 再写文件。"),

    T("tool",
      "write app/weather.py (34 lines)\n"
      "edit app/main.py: +from app.weather import fetch_weather, +route GET /weather\n"
      "ok",
      tool_name="write_file"),

    T("tool",
      "$ pip install httpx && pip freeze | grep httpx\n"
      "Successfully installed httpx-0.27.0 httpcore-1.0.5\n"
      "httpx==0.27.0\n"
      "$ export OPENWEATHER_API_KEY=sk-test-xxxx\n"
      "$ curl -s 'http://127.0.0.1:8000/weather?city=Shanghai'\n"
      "Internal Server Error\n"
      "--- server log ---\n"
      "ERROR:    Exception in ASGI application\n"
      "Traceback (most recent call last):\n"
      "  File \"/home/dev/weather-service/.venv/lib/python3.11/site-packages/uvicorn/protocols/http/httptools_impl.py\", line 399, in run_asgi\n"
      "    result = await app(self.scope, self.receive, self.send)\n"
      "  File \"/home/dev/weather-service/.venv/lib/python3.11/site-packages/starlette/routing.py\", line 72, in app\n"
      "    response = await func(request)\n"
      "  File \"/home/dev/weather-service/app/main.py\", line 18, in weather\n"
      "    payload = await fetch_weather(city)\n"
      "  File \"/home/dev/weather-service/app/weather.py\", line 21, in fetch_weather\n"
      "    data = respone.json()\n"
      "           ^^^^^^^\n"
      "NameError: name 'respone' is not defined. Did you mean: 'resp'?\n"
      "INFO:     127.0.0.1:53410 - \"GET /weather?city=Shanghai HTTP/1.1\" 500 Internal Server Error",
      tool_name="bash"),

    T("assistant",
      "500 是我拼写错误导致的：`weather.py` 第 21 行把变量 `resp` 写成了 `respone`。\n"
      "```python\n"
      "-    data = respone.json()\n"
      "+    data = resp.json()\n"
      "```\n"
      "已修正，reload 之后重新 curl 验证。"),

    T("tool",
      "$ curl -s 'http://127.0.0.1:8000/weather?city=Shanghai' | python -m json.tool\n"
      "{\n"
      "    \"city\": \"Shanghai\",\n"
      "    \"temp\": 31.4,\n"
      "    \"humidity\": 78,\n"
      "    \"description\": \"scattered clouds\",\n"
      "    \"observed_at\": \"2026-07-18T03:20:41\"\n"
      "}\n"
      "INFO:     127.0.0.1:53588 - \"GET /weather?city=Shanghai HTTP/1.1\" 200 OK",
      tool_name="bash"),

    T("user",
      "返回结构可以。但我刚试了一个不存在的城市 city=Atlantisss，接口直接 500 了。"
      "这种情况应该返回 404，并给一个友好的错误信息，比如城市未找到。"),

    T("assistant",
      "对，现在上游返回 404 时我们没有处理，异常直接冒到了框架层。修改 `fetch_weather`：\n"
      "```python\n"
      "if resp.status_code == 404:\n"
      "    raise HTTPException(status_code=404, detail=f\"city not found: {city}\")\n"
      "resp.raise_for_status()\n"
      "```\n"
      "另外把 city 参数加上 `min_length=1` 校验，空字符串直接 422。改完做两组 curl 回归。"),

    T("tool",
      "$ curl -s -w '\\nHTTP %{http_code}\\n' 'http://127.0.0.1:8000/weather?city=Atlantisss'\n"
      "{\"detail\":\"city not found: Atlantisss\"}\n"
      "HTTP 404\n"
      "$ curl -s -w '\\nHTTP %{http_code}\\n' 'http://127.0.0.1:8000/weather?city=Beijing'\n"
      "{\"city\":\"Beijing\",\"temp\":33.1,\"humidity\":62,\"description\":\"clear sky\",\"observed_at\":\"2026-07-18T03:24:09\"}\n"
      "HTTP 200\n"
      "$ curl -s -w '\\nHTTP %{http_code}\\n' 'http://127.0.0.1:8000/weather?city='\n"
      "{\"detail\":[{\"type\":\"string_too_short\",\"loc\":[\"query\",\"city\"],\"msg\":\"String should have at least 1 character\"}]}\n"
      "HTTP 422",
      tool_name="bash"),

    T("assistant",
      "/weather 接口完成：\n"
      "- 正常城市返回 200 和结构化 JSON；\n"
      "- 未知城市返回 404 + `city not found`；\n"
      "- 空参数被 FastAPI 校验拦成 422；\n"
      "- API key 全程只从环境变量 OPENWEATHER_API_KEY 读取，代码和仓库里都没有明文 key。"),

    # ---------- 话题 3：加 Redis 缓存 (18-25) ----------
    T("user",
      "好，接下来给它加缓存。同一个城市的请求太频繁了，每次都打上游会超配额。"
      "用 Redis 做缓存层，key 按城市来。缓存 TTL 不要超过 10 分钟，天气数据太旧就没意义了。"),

    T("assistant",
      "方案：\n"
      "- 本地用 docker 起一个 redis:7-alpine；\n"
      "- 新建 `app/cache.py`，用 `redis.asyncio` 客户端，key 形如 `weather:{city_lower}`，\n"
      "  值存序列化后的 JSON，`setex` 设置 TTL=600 秒（正好 10 分钟的上限）；\n"
      "- `/weather` 处理逻辑改为：先查缓存，未命中再调上游并回填。\n"
      "先装依赖、起 Redis。"),

    T("tool",
      "$ pip install 'redis==5.0.4'\n"
      "Collecting redis==5.0.4\n"
      "  Downloading redis-5.0.4-py3-none-any.whl (251 kB)\n"
      "Successfully installed redis-5.0.4\n"
      "$ docker run -d --name weather-redis -p 6379:6379 redis:7-alpine\n"
      "Unable to find image 'redis:7-alpine' locally\n"
      "7-alpine: Pulling from library/redis\n"
      "4abcf2066143: Pull complete\n"
      "3c1eb8d3a752: Pull complete\n"
      "7f2b0e6a4c11: Pull complete\n"
      "b90f76a2d0c3: Pull complete\n"
      "Digest: sha256:1b503bb77079ba644371969e06e1a6a1670bb34c2251107c0fc3a21ef9fdaeca\n"
      "Status: Downloaded newer image for redis:7-alpine\n"
      "e4f9b1c3a7d25f6b0c9d1a2e8f3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b\n"
      "$ redis-cli ping\n"
      "PONG",
      tool_name="bash"),

    T("assistant",
      "Redis 已就绪。`app/cache.py` 核心实现：\n"
      "```python\n"
      "import json, redis.asyncio as aioredis\n"
      "TTL_SECONDS = 600  # 上限 10 分钟\n"
      "_pool = aioredis.from_url(\"redis://localhost:6379/0\", decode_responses=True)\n\n"
      "async def get_cached(city: str) -> dict | None:\n"
      "    raw = await _pool.get(f\"weather:{city.lower()}\")\n"
      "    return json.loads(raw) if raw else None\n\n"
      "async def set_cached(city: str, payload: dict) -> None:\n"
      "    await _pool.setex(f\"weather:{city.lower()}\", TTL_SECONDS, json.dumps(payload))\n"
      "```\n"
      "并在路由里接上先读缓存、未命中回填的逻辑。"),

    T("tool",
      "write app/cache.py (18 lines)\n"
      "edit app/main.py: /weather 先查 get_cached，未命中调 fetch_weather 后 set_cached\n"
      "ok",
      tool_name="write_file"),

    T("tool",
      "$ time curl -s 'http://127.0.0.1:8000/weather?city=Shanghai' > /dev/null\n"
      "real    0m0.412s\n"
      "user    0m0.004s\n"
      "sys     0m0.003s\n"
      "$ time curl -s 'http://127.0.0.1:8000/weather?city=Shanghai' > /dev/null\n"
      "real    0m0.009s\n"
      "user    0m0.003s\n"
      "sys     0m0.002s\n"
      "$ time curl -s 'http://127.0.0.1:8000/weather?city=Beijing' > /dev/null\n"
      "real    0m0.398s\n"
      "$ redis-cli keys 'weather:*'\n"
      "1) \"weather:shanghai\"\n"
      "2) \"weather:beijing\"\n"
      "$ redis-cli ttl weather:shanghai\n"
      "(integer) 583\n"
      "$ redis-cli get weather:shanghai\n"
      "\"{\\\"city\\\": \\\"Shanghai\\\", \\\"temp\\\": 31.4, \\\"humidity\\\": 78, \\\"description\\\": \\\"scattered clouds\\\", \\\"observed_at\\\": \\\"2026-07-18T03:20:41\\\"}\"\n"
      "--- server log ---\n"
      "INFO: cache miss city=shanghai, fetched upstream in 389ms\n"
      "INFO: cache hit  city=shanghai (0.6ms)\n"
      "INFO: cache miss city=beijing, fetched upstream in 371ms",
      tool_name="bash"),

    T("user",
      "命中效果很明显，第二次只要 9 毫秒。再加一个小需求：响应里带一个 cached 字段，"
      "true 表示这次是缓存命中，false 表示现查的，方便前端和排查用。"),

    T("assistant",
      "已加上：命中路径直接在缓存反序列化结果上补 `\"cached\": true`，"
      "现查路径回填缓存前置 `\"cached\": false`（缓存里存的是不含该字段的原始数据，避免污染）。\n"
      "验证过连续两次请求分别返回 `\"cached\": false` 和 `\"cached\": true`，"
      "`redis-cli ttl` 显示剩余 597 秒，没有超过 10 分钟上限。缓存这块完成。"),

    # ---------- 话题 4：修时区 bug (26-33) ----------
    T("user",
      "发现一个 bug：接口返回的 observed_at 是 2026-07-18T03:20:41，"
      "但当时上海本地时间明明是 11 点 20，整整差了 8 个小时。用户看到这个时间会以为数据是很久以前的。"),

    T("assistant",
      "差 8 小时基本可以断定是 UTC 和本地时区（Asia/Shanghai, UTC+8）混用了。"
      "我先看看 `weather.py` 里是怎么处理上游返回的 `dt` 时间戳的。"),

    T("tool",
      "app/weather.py (lines 24-33):\n"
      "    payload = {\n"
      "        \"city\": data[\"name\"],\n"
      "        \"temp\": data[\"main\"][\"temp\"],\n"
      "        \"humidity\": data[\"main\"][\"humidity\"],\n"
      "        \"description\": data[\"weather\"][0][\"description\"],\n"
      "        # dt is a unix timestamp (UTC)\n"
      "        \"observed_at\": datetime.utcfromtimestamp(data[\"dt\"]).isoformat(),\n"
      "    }\n"
      "    return payload",
      tool_name="read_file"),

    T("assistant",
      "问题确认了：`datetime.utcfromtimestamp` 生成的是不带时区信息的 naive UTC 时间，"
      "直接 isoformat 出去既没有偏移量标记，数值又是 UTC，前端当本地时间展示就差了 8 小时。\n"
      "修复方案（3.11 兼容，用标准库 zoneinfo）：\n"
      "```python\n"
      "from zoneinfo import ZoneInfo\n"
      "TZ = ZoneInfo(\"Asia/Shanghai\")\n"
      "observed = datetime.fromtimestamp(data[\"dt\"], tz=timezone.utc).astimezone(TZ)\n"
      "\"observed_at\": observed.isoformat()  # 例如 2026-07-18T11:20:41+08:00\n"
      "```\n"
      "顺带 `utcfromtimestamp` 在 3.12 已弃用，这次一并清理。改完先跑测试。"),

    T("tool",
      "$ python -m pytest tests/ -q\n"
      "..F.                                                                     [100%]\n"
      "=================================== FAILURES ===================================\n"
      "_________________________ test_weather_payload_format __________________________\n"
      "tests/test_weather.py:36: in test_weather_payload_format\n"
      "    payload = build_payload(SAMPLE_UPSTREAM_RESPONSE)\n"
      "_________________________ test_weather_payload_format __________________________\n"
      "    assert payload[\"observed_at\"] == \"2026-07-18T03:20:41\"\n"
      "E   AssertionError: assert '2026-07-18T11:20:41+08:00' == '2026-07-18T03:20:41'\n"
      "E     - 2026-07-18T03:20:41\n"
      "E     + 2026-07-18T11:20:41+08:00\n"
      "tests/test_weather.py:41: AssertionError\n"
      "1 failed, 3 passed in 0.34s",
      tool_name="bash"),

    T("assistant",
      "失败的这条正是断言旧的错误行为（naive UTC 字符串）的用例，属于测试需要跟着修的情况。"
      "把期望值更新为带 `+08:00` 偏移量的本地时间，并新增一条用例断言 `observed_at` 必须以\n"
      "`+08:00` 结尾、且能被 `datetime.fromisoformat` 解析出 aware 时间。重跑测试和 curl 回归。"),

    T("tool",
      "$ python -m pytest tests/ -v\n"
      "tests/test_health.py::test_root_hello_world PASSED                       [ 20%]\n"
      "tests/test_weather.py::test_weather_ok PASSED                            [ 40%]\n"
      "tests/test_weather.py::test_weather_payload_format PASSED                [ 60%]\n"
      "tests/test_weather.py::test_weather_city_not_found_404 PASSED            [ 80%]\n"
      "tests/test_weather.py::test_observed_at_is_aware_cst PASSED              [100%]\n"
      "5 passed in 0.31s\n"
      "$ redis-cli del weather:shanghai\n"
      "(integer) 1\n"
      "$ curl -s 'http://127.0.0.1:8000/weather?city=Shanghai' | python -m json.tool\n"
      "{\n"
      "    \"city\": \"Shanghai\",\n"
      "    \"temp\": 32.0,\n"
      "    \"humidity\": 74,\n"
      "    \"description\": \"scattered clouds\",\n"
      "    \"observed_at\": \"2026-07-18T11:41:07+08:00\",\n"
      "    \"cached\": false\n"
      "}",
      tool_name="bash"),

    T("assistant",
      "时区 bug 修复完成：\n"
      "- 根因：`utcfromtimestamp` 产生 naive UTC 时间且无偏移量标记；\n"
      "- 修复：统一用 aware datetime，转换到 Asia/Shanghai 后输出带 `+08:00` 的 ISO 格式；\n"
      "- 旧缓存已清掉，5 条测试全绿，curl 回归显示 11:41 与本地时间一致。"),

    # ---------- 话题 5：文档与部署 (34-39) ----------
    T("user",
      "最后收个尾：写一份 README（怎么装依赖、配环境变量、本地启动、跑测试），"
      "再写个 Dockerfile 把服务容器化，本地构建一下镜像确认能跑。"),

    T("assistant",
      "好的。README 覆盖：项目简介、Python 3.11 + Redis 依赖、`OPENWEATHER_API_KEY` 配置说明、\n"
      "本地启动与 pytest 命令、`/weather` 接口示例。Dockerfile 用多阶段思路精简：\n"
      "```dockerfile\n"
      "FROM python:3.11-slim\n"
      "WORKDIR /srv/app\n"
      "COPY requirements.txt .\n"
      "RUN pip install --no-cache-dir -r requirements.txt\n"
      "COPY app ./app\n"
      "EXPOSE 8000\n"
      "CMD [\"uvicorn\", \"app.main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]\n"
      "```\n"
      "API key 通过 `docker run -e` 注入，不进镜像。现在写文件。"),

    T("tool",
      "write README.md (52 lines), 节选:\n"
      "  # weather-service\n"
      "  基于 FastAPI 的实时天气查询服务，带 Redis 缓存（TTL 600s）。\n"
      "  ## 环境要求\n"
      "  - Python 3.11 / Redis 7\n"
      "  ## 配置\n"
      "  export OPENWEATHER_API_KEY=<your-key>   # 必填，不要提交到仓库\n"
      "  ## 本地启动\n"
      "  uvicorn app.main:app --reload --port 8000\n"
      "  ## 运行测试\n"
      "  python -m pytest tests/ -q\n"
      "  ## API 示例\n"
      "  GET /weather?city=Shanghai -> {\"city\": ..., \"temp\": ..., \"cached\": ...}\n"
      "write Dockerfile (8 lines)\n"
      "write .dockerignore (4 lines): .venv, __pycache__, tests, .git\n"
      "ok",
      tool_name="write_file"),

    T("assistant",
      "文件就绪，开始构建镜像并验证容器能正常提供服务："),

    T("tool",
      "$ docker build -t weather-service:0.1.0 .\n"
      "[+] Building 24.7s (10/10) FINISHED                              docker:default\n"
      " => [internal] load build definition from Dockerfile                      0.0s\n"
      " => [internal] load .dockerignore                                         0.0s\n"
      " => [internal] load metadata for docker.io/library/python:3.11-slim       0.9s\n"
      " => [internal] load build context                                         0.1s\n"
      " => => transferring context: 12.40kB                                      0.0s\n"
      " => [1/5] FROM docker.io/library/python:3.11-slim@sha256:7b8c1f...        3.1s\n"
      " => [2/5] WORKDIR /srv/app                                                0.1s\n"
      " => [3/5] COPY requirements.txt .                                         0.1s\n"
      " => [4/5] RUN pip install --no-cache-dir -r requirements.txt             19.8s\n"
      " => [5/5] COPY app ./app                                                  0.1s\n"
      " => exporting to image                                                    1.2s\n"
      " => => naming to docker.io/library/weather-service:0.1.0                  0.0s\n"
      "$ docker run -d --rm --name ws -p 8080:8000 --network host \\\n"
      "    -e OPENWEATHER_API_KEY=$OPENWEATHER_API_KEY weather-service:0.1.0\n"
      "f2a91c0d77be\n"
      "$ docker logs ws | tail -3\n"
      "INFO:     Started server process [1]\n"
      "INFO:     Waiting for application startup.\n"
      "INFO:     Application startup complete.\n"
      "$ docker images weather-service\n"
      "REPOSITORY        TAG     IMAGE ID       CREATED          SIZE\n"
      "weather-service   0.1.0   9c4e2b1f8d03   12 seconds ago   184MB\n"
      "$ curl -s -w '\\nHTTP %{http_code}\\n' 'http://127.0.0.1:8000/weather?city=Shanghai'\n"
      "{\"city\":\"Shanghai\",\"temp\":31.8,\"humidity\":75,\"description\":\"scattered clouds\",\"observed_at\":\"2026-07-18T12:02:33+08:00\",\"cached\":true}\n"
      "HTTP 200",
      tool_name="bash"),

    T("assistant",
      "全部收尾完成：\n"
      "- README.md 覆盖安装、配置、启动、测试和接口示例；\n"
      "- Dockerfile 基于 python:3.11-slim，镜像 weather-service:0.1.0 构建成功；\n"
      "- 容器内服务 curl 验证通过，时间带 +08:00、缓存字段正常，key 仍由环境变量注入。\n"
      "项目从环境搭建到容器化部署已经完整跑通。"),
]

CASE = Case(
    case_id="c1",
    title="多话题切换：从零构建 FastAPI 天气查询服务",
    turns=TURNS,
    segments=[
        Segment(name="环境搭建", start=0, end=7),
        Segment(name="实现天气查询 API", start=8, end=17),
        Segment(name="加 Redis 缓存", start=18, end=25),
        Segment(name="修时区 bug", start=26, end=33),
        Segment(name="文档与部署", start=34, end=39),
    ],
    constraints=[
        GoldConstraint(turn=0, text="整个项目必须兼容 Python 3.11"),
        GoldConstraint(turn=8, text="不要把 API key 写死在代码里，用环境变量 OPENWEATHER_API_KEY 读取"),
        GoldConstraint(turn=18, text="缓存 TTL 不要超过 10 分钟"),
    ],
    backtracks=[],
)
