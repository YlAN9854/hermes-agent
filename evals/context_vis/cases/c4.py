"""Case c4 — 超长会话（触发分批）+ 中英混合：Jenkins → GitHub Actions CI 迁移.

用户消息中文，agent 中英混合，工具输出为长英文日志/配置。长日志由确定性
循环构造（无随机），内部有足够变化避免逐字重复行破坏引文锚定。
"""
from __future__ import annotations

from evals.context_vis.case_schema import Backtrack, Case, GoldConstraint, Segment, T

PACKAGES = [
    "packages/auth", "packages/billing", "packages/catalog", "packages/checkout",
    "packages/notifications", "packages/search", "packages/gateway", "packages/admin-ui",
    "packages/web-app", "packages/shared-utils", "packages/i18n", "packages/analytics",
]

_CASE_NAMES = [
    "renders without crashing", "handles empty input", "rejects an invalid token",
    "retries on upstream timeout", "serializes dates as ISO strings", "paginates long result sets",
    "falls back to the default locale", "propagates the correlation id", "debounces rapid updates",
    "caches the second lookup", "emits an audit event", "normalizes unicode names",
    "escapes html in user content", "honours the feature flag", "rolls back on partial failure",
    "deduplicates concurrent requests", "expires stale sessions", "validates the currency code",
]


def _ts(hour: int, minute: int, second: int) -> str:
    return f"2026-07-15T{hour:02d}:{minute:02d}:{second:02d}Z"


def _clock(start_s: int, i: int, step: int = 7) -> str:
    total = start_s + i * step
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return _ts(9 + h, m, s)


def _jenkinsfile() -> str:
    head = """// Jenkinsfile (root) — monorepo pipeline, last touched 2024-11
pipeline {
  agent { label 'linux-docker-xl' }
  options {
    timestamps()
    buildDiscarder(logRotator(numToKeepStr: '40'))
    timeout(time: 90, unit: 'MINUTES')
  }
  environment {
    PNPM_HOME = '/opt/pnpm'
    TURBO_TELEMETRY_DISABLED = '1'
    REGISTRY = 'registry.internal.corp:5000'
  }
  stages {
    stage('Install') {
      steps {
        sh 'pnpm install --frozen-lockfile'
      }
    }
    stage('Lint') {
      steps {
        sh 'pnpm run lint --filter="[origin/main...HEAD]"'
      }
    }
"""
    stages = []
    for pkg in PACKAGES:
        short = pkg.split("/")[1]
        stages.append(
            f"""    stage('Build {short}') {{
      steps {{
        sh 'pnpm --filter {pkg} run build'
        sh 'pnpm --filter {pkg} run typecheck'
      }}
      post {{ failure {{ archiveArtifacts artifacts: '{pkg}/dist/**/*.log', allowEmptyArchive: true }} }}
    }}
"""
        )
    tail = """    stage('Test (sharded)') {
      parallel {
        stage('shard-1') { steps { sh './scripts/run-tests.sh --shard 1/4' } }
        stage('shard-2') { steps { sh './scripts/run-tests.sh --shard 2/4' } }
        stage('shard-3') { steps { sh './scripts/run-tests.sh --shard 3/4' } }
        stage('shard-4') { steps { sh './scripts/run-tests.sh --shard 4/4' } }
      }
    }
    stage('Docker build') {
      when { branch 'main' }
      steps {
        sh 'docker build -t $REGISTRY/monorepo/gateway:$GIT_COMMIT -f docker/gateway.Dockerfile .'
        sh 'docker build -t $REGISTRY/monorepo/web-app:$GIT_COMMIT -f docker/web-app.Dockerfile .'
        sh 'docker push $REGISTRY/monorepo/gateway:$GIT_COMMIT'
        sh 'docker push $REGISTRY/monorepo/web-app:$GIT_COMMIT'
      }
    }
    stage('Deploy staging') {
      when { branch 'main' }
      steps {
        withCredentials([file(credentialsId: 'kubeconfig-staging', variable: 'KUBECONFIG')]) {
          sh './scripts/deploy.sh staging $GIT_COMMIT'
        }
      }
    }
    stage('Deploy production') {
      when { branch 'main' }
      steps {
        input message: 'Deploy to production?', ok: 'Ship it'
        withCredentials([file(credentialsId: 'kubeconfig-prod', variable: 'KUBECONFIG')]) {
          sh './scripts/deploy.sh production $GIT_COMMIT'
        }
      }
    }
  }
  post {
    always { junit 'reports/junit/**/*.xml' }
    failure { slackSend channel: '#ci-alerts', message: "Build failed: ${env.BUILD_URL}" }
  }
}
"""
    return head + "".join(stages) + tail


def _job_configs() -> str:
    jobs = [
        ("monorepo-pr", "Runs install/lint/build/test on every pull request", "H/2 * * * *", "polls SCM"),
        ("monorepo-main", "Full pipeline incl. docker build and staged deploy on main", None, "webhook"),
        ("nightly-e2e", "Playwright end-to-end suite against staging", "H 2 * * *", "cron"),
        ("release-tag", "Builds and publishes versioned images on git tags v*", None, "tag webhook"),
        ("dependency-audit", "pnpm audit + license scan, mails report", "H 6 * * 1", "cron"),
    ]
    parts = ["$ java -jar jenkins-cli.jar -s https://jenkins.internal.corp list-jobs\n"]
    parts.extend(f"{name}\n" for name, *_ in jobs)
    for name, desc, cron, trigger in jobs:
        parts.append(f"\n$ java -jar jenkins-cli.jar -s https://jenkins.internal.corp get-job {name}\n")
        parts.append(f"""<?xml version='1.1' encoding='UTF-8'?>
<flow-definition plugin="workflow-job@1400.v7fd111b_ff37f">
  <description>{desc}</description>
  <keepDependencies>false</keepDependencies>
  <properties>
    <org.jenkinsci.plugins.workflow.job.properties.DisableConcurrentBuildsJobProperty/>
    <hudson.model.ParametersDefinitionProperty>
      <parameterDefinitions>
        <hudson.model.StringParameterDefinition>
          <name>GIT_REF</name>
          <defaultValue>main</defaultValue>
        </hudson.model.StringParameterDefinition>
      </parameterDefinitions>
    </hudson.model.ParametersDefinitionProperty>
  </properties>
  <definition class="org.jenkinsci.plugins.workflow.cps.CpsScmFlowDefinition" plugin="workflow-cps@3906">
    <scm class="hudson.plugins.git.GitSCM" plugin="git@5.2.1">
      <userRemoteConfigs>
        <hudson.plugins.git.UserRemoteConfig>
          <url>git@git.internal.corp:platform/monorepo.git</url>
          <credentialsId>git-deploy-key</credentialsId>
        </hudson.plugins.git.UserRemoteConfig>
      </userRemoteConfigs>
    </scm>
    <scriptPath>{'Jenkinsfile' if name.startswith('monorepo') else 'ci/' + name + '.Jenkinsfile'}</scriptPath>
    <lightweight>true</lightweight>
  </definition>
  <triggers>{f'<hudson.triggers.TimerTrigger><spec>{cron}</spec></hudson.triggers.TimerTrigger>' if cron else ''}</triggers>
  <!-- trigger source: {trigger} -->
</flow-definition>
""")
    return "".join(parts)


def _plugin_list() -> str:
    plugins = [
        ("workflow-aggregator", "600.vb_57cdd26fdd7", "Pipeline"),
        ("git", "5.2.1", "Git SCM"),
        ("docker-workflow", "580.vc0c340686b_54", "Docker Pipeline"),
        ("junit", "1265.v65b_14fa_f12f0", "JUnit test reports"),
        ("slack", "684.v833089650554", "Slack notifications"),
        ("credentials-binding", "657.v2b_19db_7d6e6d", "withCredentials"),
        ("timestamper", "1.26", "Timestamps in logs"),
        ("kubernetes-cli", "1.12.1", "kubectl credential wiring"),
        ("throttle-concurrents", "2.14", "Concurrency throttling"),
        ("build-discarder", "223.vd5e2e832f9d1", "Log rotation"),
        ("pipeline-stage-view", "2.34", "Stage view UI"),
        ("email-ext", "2.105", "dependency-audit report mail"),
    ]
    lines = ["$ java -jar jenkins-cli.jar -s https://jenkins.internal.corp list-plugins\n"]
    for name, version, note in plugins:
        lines.append(f"{name:<24} {version:<24} # {note}\n")
    return "".join(lines)


_BUILD_YML_V1 = """# .github/workflows/build.yml (v1)
name: build
on:
  pull_request:
  push:
    branches: [main]
concurrency:
  group: build-${{ github.ref }}
  cancel-in-progress: true
jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      max-parallel: 4
      matrix:
        package: [auth, billing, catalog, checkout, notifications, search, gateway, admin-ui, web-app, shared-utils, i18n, analytics]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - run: pnpm install --frozen-lockfile
      - run: pnpm --filter packages/${{ matrix.package }} run build
      - run: pnpm --filter packages/${{ matrix.package }} run typecheck
"""

_BUILD_YML_V2_DIFF = """--- a/.github/workflows/build.yml
+++ b/.github/workflows/build.yml
@@ steps:
       - uses: actions/checkout@v4
+      - uses: pnpm/action-setup@v4
+        with:
+          version: 9.6.0
       - uses: actions/setup-node@v4
         with:
           node-version: 20
+          cache: 'pnpm'
+      - name: Restore turbo cache
+        uses: actions/cache@v4
+        with:
+          path: .turbo
+          key: turbo-${{ runner.os }}-${{ matrix.package }}-${{ github.sha }}
+          restore-keys: |
+            turbo-${{ runner.os }}-${{ matrix.package }}-
       - run: pnpm install --frozen-lockfile
"""


def _build_fail_log() -> str:
    lines = [
        "$ gh run watch 9182734650 --exit-status\n",
        f"[{_ts(9, 14, 2)}] build (auth)  Set up job\n",
        f"[{_ts(9, 14, 5)}] build (auth)  actions/checkout@v4 — fetched 41208 objects in 6.4s\n",
        f"[{_ts(9, 14, 12)}] build (auth)  actions/setup-node@v4 — node v20.15.1 installed\n",
        f"[{_ts(9, 14, 13)}] build (auth)  Run pnpm install --frozen-lockfile\n",
        f"[{_ts(9, 14, 13)}] build (auth)  /home/runner/work/_temp/run.sh: line 1: pnpm: command not found\n",
        f"[{_ts(9, 14, 13)}] build (auth)  ##[error]Process completed with exit code 127.\n",
    ]
    for i, pkg in enumerate(PACKAGES[1:4], start=1):
        short = pkg.split("/")[1]
        base = 14 + i
        lines += [
            f"[{_ts(9, base, 2)}] build ({short})  Set up job\n",
            f"[{_ts(9, base, 9)}] build ({short})  Run pnpm install --frozen-lockfile\n",
            f"[{_ts(9, base, 9)}] build ({short})  /home/runner/work/_temp/run.sh: line 1: pnpm: command not found\n",
            f"[{_ts(9, base, 9)}] build ({short})  ##[error]Process completed with exit code 127.\n",
        ]
    lines.append("\nX Run build (9182734650) completed with 'failure' — 12 failed matrix jobs, first error: pnpm: command not found\n")
    lines.append("annotations: 12 errors — the runner image does not ship pnpm; install it explicitly before setup-node cache resolution.\n")
    return "".join(lines)


def _build_ok_log() -> str:
    lines = ["$ gh run watch 9182770114 --exit-status\n"]
    for i, pkg in enumerate(PACKAGES):
        short = pkg.split("/")[1]
        dur = 41 + (i * 13) % 68
        cache = "MISS" if i % 5 == 0 else "HIT"
        files = 120 + (i * 37) % 400
        lines += [
            f"[{_clock(20 * 60, i * 9)}] build ({short})  pnpm install --frozen-lockfile — done in {8 + (i * 3) % 11}.{(i * 7) % 10}s (store served {1400 + i * 61} pkgs)\n",
            f"[{_clock(20 * 60, i * 9 + 2)}] build ({short})  turbo run build — cache {cache}, {files} files emitted\n",
            f"[{_clock(20 * 60, i * 9 + 5)}] build ({short})  tsc --noEmit — 0 errors\n",
            f"[{_clock(20 * 60, i * 9 + 6)}] build ({short})  Job succeeded in {dur}s\n",
        ]
    lines.append("\n✓ Run build (9182770114) completed with 'success' — 12/12 matrix jobs green, wall clock 9m41s\n")
    return "".join(lines)


def _cache_stats() -> str:
    lines = ["$ gh cache list --limit 20\n"]
    for i, pkg in enumerate(PACKAGES):
        short = pkg.split("/")[1]
        size = 18 + (i * 29) % 160
        lines.append(f"turbo-Linux-{short}-4f21ac9   {size} MB   refs/heads/ci/gha-build   {2 + i} minutes ago\n")
    lines.append("pnpm-store-Linux-9.6.0        412 MB   refs/heads/ci/gha-build   14 minutes ago\n")
    lines.append("\n$ npx turbo run build --dry=json | jq '.tasks | map(.cache.status) | group_by(.) | map({status: .[0], n: length})'\n")
    lines.append('[{"status":"HIT","n":32},{"status":"MISS","n":4}]  # 89% hit rate on the second run\n')
    return "".join(lines)


_TEST_YML = """# .github/workflows/test.yml
name: test
on:
  pull_request:
  push:
    branches: [main]
concurrency:
  group: test-${{ github.ref }}
  cancel-in-progress: true
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        shard: [1, 2, 3, 4]
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with:
          version: 9.6.0
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'pnpm'
      - run: pnpm install --frozen-lockfile
      - run: ./scripts/run-tests.sh --shard ${{ matrix.shard }}/4 --reporter jest-junit
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: junit-shard-${{ matrix.shard }}
          path: reports/junit/
"""

_FAILING_TESTS = {
    ("packages/notifications", "digestScheduler"): [
        ("batches digests across the quiet window", True),
        ("skips users in a muted thread", False),
        ("re-sends after a transient smtp error", False),
    ],
    ("packages/search", "indexRebuild"): [
        ("rebuilds the index without dropping reads", False),
    ],
}


def _test_log(rerun: bool = False) -> str:
    lines = []
    if rerun:
        lines.append("$ gh run watch 9183504821 --exit-status   # rerun after test fixes\n")
    else:
        lines.append("$ gh run watch 9183221907 --exit-status\n")
    total_pass = 0
    total_fail = 0
    suite_count = 0
    for pi, pkg in enumerate(PACKAGES):
        n_suites = 7 + (pi % 5)
        for si in range(n_suites):
            suite = f"{pkg}/src/__tests__/{['core', 'api', 'edge', 'perf', 'io', 'ui', 'store', 'hooks', 'cli', 'schema', 'routes'][si % 11]}{si}.test.ts"
            suite_count += 1
            n_cases = 6 + ((pi * 7 + si * 3) % 8)
            dur = 2 + ((pi * 11 + si * 5) % 90) / 10
            lines.append(f"PASS {suite} ({dur:.1f}s)\n")
            for ci in range(n_cases):
                name = _CASE_NAMES[(pi * 13 + si * 5 + ci) % len(_CASE_NAMES)]
                ms = 20 + (pi * 97 + si * 41 + ci * 31) % 880
                lines.append(f"  ✓ {name} ({ms} ms)\n")
                total_pass += 1
            if (pi * 7 + si) % 9 == 0:
                lines.append(f"  console.warn — deprecation: {pkg} uses the legacy config loader, migrate to loadConfigV2()\n")
    for (pkg, suite_name), cases in _FAILING_TESTS.items():
        suite = f"{pkg}/src/__tests__/{suite_name}.test.ts"
        if rerun:
            lines.append(f"PASS {suite} (4.2s)\n")
            for name, _ in cases:
                lines.append(f"  ✓ {name} (312 ms)\n")
                total_pass += 1
        else:
            lines.append(f"FAIL {suite} (11.8s)\n")
            for name, ok in cases:
                if ok:
                    lines.append(f"  ✓ {name} (290 ms)\n")
                    total_pass += 1
                else:
                    total_fail += 1
                    lines.append(f"  ✗ {name} (5011 ms)\n")
                    if "smtp" in name or "digest" in name.lower() or "muted" in name:
                        lines.append(
                            "      Expected scheduled slot 2026-07-15T18:00:00+08:00, received 2026-07-15T10:00:00Z\n"
                            "      at Object.<anonymous> (src/__tests__/digestScheduler.test.ts:88:27)\n"
                            "      hint: the suite computes 'next 6pm' from Date.now() with a hardcoded +8h offset\n"
                        )
                    else:
                        lines.append(
                            "      listen EADDRINUSE: address already in use 127.0.0.1:39400\n"
                            "      at Server.setupListenHandle [as _listen2] (node:net:1817:16)\n"
                            "      hint: the fixture binds a fixed port; shards 2 and 4 collide on the same runner\n"
                        )
    fail_suites = 0 if rerun else len(_FAILING_TESTS)
    lines.append(f"\nTest Suites: {fail_suites} failed, {suite_count + len(_FAILING_TESTS) - fail_suites} passed, {suite_count + len(_FAILING_TESTS)} total\n")
    lines.append(f"Tests:       {total_fail} failed, {total_pass} passed, {total_pass + total_fail} total\n")
    lines.append("Snapshots:   112 passed, 112 total\n")
    lines.append(f"Time:        {'6m 12s' if rerun else '14m 47s'} (4 shards, wall clock)\n")
    if not rerun:
        lines.append("\nX Run test (9183221907) completed with 'failure' — shards 2 and 4 red\n")
    else:
        lines.append("\n✓ Run test (9183504821) completed with 'success' — 4/4 shards green\n")
    return "".join(lines)


_DEPLOY_YML = """# .github/workflows/deploy.yml
name: deploy
on:
  workflow_run:
    workflows: [test]
    branches: [main]
    types: [completed]
jobs:
  staging:
    if: github.event.workflow_run.conclusion == 'success'
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - uses: actions/checkout@v4
      - name: Configure kubectl
        run: echo "$KUBECONFIG_B64" | base64 -d > $RUNNER_TEMP/kubeconfig
        env:
          KUBECONFIG_B64: ${{ secrets.KUBECONFIG_STAGING }}
      - run: ./scripts/deploy.sh staging ${{ github.event.workflow_run.head_sha }}
        env:
          KUBECONFIG: ${{ runner.temp }}/kubeconfig
  production:
    needs: staging
    runs-on: ubuntu-latest
    environment: production   # required reviewers configured on the environment
    steps:
      - uses: actions/checkout@v4
      - name: Configure kubectl
        run: echo "$KUBECONFIG_B64" | base64 -d > $RUNNER_TEMP/kubeconfig
        env:
          KUBECONFIG_B64: ${{ secrets.KUBECONFIG_PROD }}
      - run: ./scripts/deploy.sh production ${{ github.event.workflow_run.head_sha }}
        env:
          KUBECONFIG: ${{ runner.temp }}/kubeconfig
"""


def _env_setup_log() -> str:
    return """$ gh api -X PUT repos/platform/monorepo/environments/staging --input staging-env.json
{"name": "staging", "protection_rules": [], "deployment_branch_policy": {"protected_branches": true}}
$ gh api -X PUT repos/platform/monorepo/environments/production --input prod-env.json
{"name": "production", "protection_rules": [{"type": "required_reviewers", "reviewers": [{"type": "Team", "slug": "platform-leads"}]}, {"type": "wait_timer", "wait_timer": 0}], "deployment_branch_policy": {"protected_branches": true}}
$ gh secret set KUBECONFIG_STAGING --env staging < kubeconfig-staging.b64
✓ Set Actions secret KUBECONFIG_STAGING for platform/monorepo (environment: staging)
$ gh secret set KUBECONFIG_PROD --env production < kubeconfig-prod.b64
✓ Set Actions secret KUBECONFIG_PROD for platform/monorepo (environment: production)
"""


def _staging_deploy_log() -> str:
    services = ["gateway", "web-app", "worker-notifications", "worker-search"]
    lines = ["$ gh run watch 9184002376 --exit-status\n"]
    for i, svc in enumerate(services):
        lines += [
            f"[{_clock(140 * 60, i * 40)}] staging  docker pull registry.internal.corp:5000/monorepo/{svc}:8c1f27d — {320 + i * 41} MB in {9 + i * 2}.{i}s\n",
            f"[{_clock(140 * 60, i * 40 + 12)}] staging  kubectl set image deploy/{svc} {svc}=registry.internal.corp:5000/monorepo/{svc}:8c1f27d -n staging\n",
            f"[{_clock(140 * 60, i * 40 + 18)}] staging  rollout status deploy/{svc}: 1 old replicas pending termination\n",
            f"[{_clock(140 * 60, i * 40 + 34)}] staging  rollout status deploy/{svc}: successfully rolled out ({2 + i}/{2 + i} updated)\n",
            f"[{_clock(140 * 60, i * 40 + 36)}] staging  smoke: GET /healthz -> 200 in {40 + i * 17}ms\n",
        ]
    lines.append("\n✓ deploy/staging (9184002376) succeeded in 4m18s; production job is waiting on required reviewers (environment: production)\n")
    return "".join(lines)


def _canary_log() -> str:
    lines = ["$ gh workflow run deploy.yml -f target=canary -f namespace=staging-canary && gh run watch 9184188872\n"]
    steps = [
        "resolve image tags for 8c1f27d — 4 services",
        "kubectl apply -k deploy/overlays/staging-canary — 14 resources configured",
        "rollout status deploy/gateway -n staging-canary: successfully rolled out (1/1)",
        "rollout status deploy/web-app -n staging-canary: successfully rolled out (1/1)",
        "smoke suite: 26 checks, 26 passed, 0 failed (p95 214ms)",
        "approval gate: production environment — review requested from @platform-leads",
        "approval gate: approved by @ylan (platform-leads) after 3m12s",
        "canary rehearsal complete — no resources touched outside namespace staging-canary",
    ]
    for i, step in enumerate(steps):
        lines.append(f"[{_clock(160 * 60, i * 25)}] canary  {step}\n")
    lines.append("\n✓ Run deploy (9184188872) completed with 'success'\n")
    return "".join(lines)


def _timing_report() -> str:
    rows = [
        ("monorepo-pr (Jenkins)", "31m 40s", "30m 55s", "33m 02s", "31m 52s"),
        ("build+test PR (GHA)", "12m 08s", "11m 41s", "12m 30s", "12m 06s"),
        ("monorepo-main (Jenkins)", "48m 21s", "47m 05s", "49m 44s", "48m 23s"),
        ("build+test+deploy main (GHA)", "21m 17s", "20m 43s", "21m 58s", "21m 19s"),
    ]
    lines = ["$ python scripts/ci-timing.py --runs 3 --compare jenkins:ghas\n"]
    lines.append(f"{'pipeline':<32} {'run1':>8} {'run2':>8} {'run3':>8} {'mean':>8}\n")
    for name, r1, r2, r3, mean in rows:
        lines.append(f"{name:<32} {r1:>8} {r2:>8} {r3:>8} {mean:>8}\n")
    lines.append("\nnotes: GHA numbers include queue time (median 22s). Jenkins numbers exclude executor wait (median 4m 10s on busy afternoons).\n")
    return "".join(lines)


def _remote_cache_log() -> str:
    lines = ["$ gh run watch 9184550019 --exit-status   # with remote turbo cache + docker layer cache\n"]
    for i, pkg in enumerate(PACKAGES):
        short = pkg.split("/")[1]
        status = "REMOTE HIT" if i % 6 else "MISS (changed)"
        lines.append(f"[{_clock(200 * 60, i * 6)}] build ({short})  turbo: {status}, restored in {120 + (i * 53) % 700}ms\n")
    lines += [
        f"[{_clock(200 * 60, 80)}] docker  gateway.Dockerfile — 9/11 layers cached, build 74s (was 210s)\n",
        f"[{_clock(200 * 60, 160)}] docker  web-app.Dockerfile — 8/12 layers cached, build 96s (was 254s)\n",
        "\n✓ main pipeline wall clock: 16m 02s (was 21m 19s)\n",
    ]
    return "".join(lines)


_PLAN_DOC = """# CI migration plan: Jenkins → GitHub Actions

## Workflows
- build.yml — PR + main; matrix over 12 packages, max-parallel 4
- test.yml — PR + main; 4 shards, junit artifacts
- deploy.yml — main only, triggered by test success via workflow_run; staging auto, production behind environment approval
- nightly-e2e — NOT migrated in this phase (stays on Jenkins, see M4)

## Milestones
- M1 build.yml green on a feature branch
- M2 test.yml green incl. flaky fixes, junit summary parity
- M3 deploy.yml staging + approval-gated production rehearsal
- M4 two-week parallel run, then decommission Jenkins PR/main jobs; nightly-e2e migrates last

## Secrets
All deploy credentials live in GitHub Environments (staging / production) with required reviewers on production. Nothing sensitive in workflow files or repo-level secrets.

## Caching
pnpm store via actions/setup-node cache; turbo local cache keyed per package; evaluate turbo remote cache in M3.
"""

_CONTRIB_DIFF = """--- a/CONTRIBUTING.md
+++ b/CONTRIBUTING.md
@@ ## Continuous integration
-Our CI runs on Jenkins (https://jenkins.internal.corp). PR builds are triggered by SCM polling
-every 2 minutes; check the `monorepo-pr` job for your branch.
+CI runs on GitHub Actions. Every PR triggers `build` (per-package matrix) and `test` (4 shards);
+results and a junit summary appear directly on the PR checks tab.
+
+- Re-run a single failed shard from the checks tab (no full re-run needed).
+- `deploy` runs on main only: staging deploys automatically after tests pass; production
+  deployments wait for approval from @platform-leads on the `production` environment.
+- During the transition window Jenkins `monorepo-main` still mirrors main builds; it will be
+  decommissioned after the parallel-run period ends. nightly-e2e still runs on Jenkins.
@@ ## Test reports
-JUnit reports are archived on the Jenkins build page under "Test Result".
+JUnit XML is uploaded as a `junit-shard-*` artifact on each test run and summarized in the
+run's step summary. Playwright e2e reports remain on Jenkins until nightly-e2e migrates.
"""


def _turns() -> list[T]:
    t: list[T] = []
    # ---- segment 0: 现状调研 (0-10) ----
    t.append(T("user", "我们的 monorepo 现在整套 CI 都在 Jenkins 上，接下来想整体迁到 GitHub Actions。先帮我摸清现状：主 Jenkinsfile 都做了什么、上面挂了哪些 job。先说一个原则：迁移期间 Jenkins 必须保持可用，不要提前下线，两边并行跑到我们确认新 CI 稳定为止。"))
    t.append(T("assistant", "明白，parallel run until the new CI is proven stable — I'll keep every Jenkins job untouched while we build the Actions side. 我先读根目录的 Jenkinsfile，再用 jenkins-cli 列出全部 job 和它们的配置。"))
    t.append(T("tool", _jenkinsfile(), tool_name="read_file"))
    t.append(T("assistant", "主 pipeline 的结构清楚了：install → lint → **12 个包逐个串行 build+typecheck**（这是最大的时间黑洞）→ 4-shard 并行测试 → main 分支上再做 docker build、staging 部署和带人工 input 的生产部署。串行 build 意味着任何一个包排队都拖全局，这正是迁到 Actions matrix 后最先能拿到的收益。Credentials 走的是 Jenkins 的 credentialsId（kubeconfig-staging / kubeconfig-prod），迁移时要换成 Actions 的机制。"))
    t.append(T("user", "除了这条主 pipeline，Jenkins 上还挂了哪些 job？定时任务也别漏。"))
    t.append(T("assistant", "Querying the Jenkins CLI for the full job list and each job's config.xml."))
    t.append(T("tool", _job_configs(), tool_name="bash"))
    t.append(T("assistant", "一共 5 个 job：monorepo-pr（SCM 每 2 分钟轮询，太浪费了，Actions 直接用事件触发）、monorepo-main（webhook 全量流水线）、nightly-e2e（每晚 2 点 Playwright 打 staging）、release-tag（tag 触发发布镜像）、dependency-audit（每周一 6 点审计+发邮件）。其中 monorepo-pr / monorepo-main 是这次迁移的主体，release-tag 可以合并进 deploy workflow 的 tag 触发，dependency-audit 很薄可以最后顺手迁。"))
    t.append(T("user", "我们现在用了哪些 Jenkins 插件？迁的时候要找对应的替代。"))
    t.append(T("tool", _plugin_list(), tool_name="bash"))
    t.append(T("assistant", "插件面不大，都有现成替代：junit → junit artifact + step summary；slack → slack 官方 action 或保留 webhook；credentials-binding → environment secrets；throttle-concurrents → `concurrency` group；pipeline-stage-view → Actions 原生 UI。没有发现自研插件，迁移面是干净的。现状调研到此完整：1 条主流水线 + 4 个辅助 job + 12 个插件依赖。"))
    # ---- segment 1: 方案设计 (11-20) ----
    t.append(T("user", "行，出个迁移方案。workflow 怎么拆、matrix 怎么设计、secrets 怎么处理，先讲清楚再动手。"))
    t.append(T("assistant", "Proposal: three workflows plus one deferred.\n1) **build.yml** — PR+main，matrix over the 12 packages（把串行 build 变成并行），`concurrency` group 按 ref 去重；\n2) **test.yml** — 保持 4 shards 不变（脚本已经支持 --shard），junit 上传 artifact；\n3) **deploy.yml** — 只在 main，由 test 成功经 workflow_run 触发，staging 自动、production 用 environment 审批复刻现在的 input gate；\n4) nightly-e2e 单独一期，先不动。\nCache 用 pnpm store + turbo 本地缓存起步，remote cache 放到后面做优化。"))
    t.append(T("user", "secrets 这块我有硬要求：所有 secrets 必须走 GitHub Environments，禁止写进 workflow 文件，repo-level 的明文 secret 也不要用。审批人配 platform-leads。"))
    t.append(T("assistant", "Agreed — environment-scoped secrets only. 两个 environment：staging（无审批）、production（required reviewers = platform-leads team）。kubeconfig 以 base64 存 environment secret，workflow 里只引用 `${{ secrets.KUBECONFIG_* }}`，文件本身零敏感内容。这也顺带把审计边界画清楚了：谁批了哪次生产部署，environment 的 deployment log 里全有。"))
    t.append(T("user", "matrix 12 个包会不会把 runner 额度打爆？我们组织的并发是有限的。"))
    t.append(T("assistant", "Good concern. 我在 build matrix 上设 `max-parallel: 4`：12 个包分三波，单波时长 ≈ 最慢包的 build 时间（~70s），总体仍然远快于 Jenkins 的纯串行；同时 `cancel-in-progress: true` 保证同一 PR 连续 push 不会堆积浪费并发。之后看实际队列情况再调。"))
    t.append(T("tool", _PLAN_DOC, tool_name="write_file"))
    t.append(T("assistant", "方案落到 docs/ci-migration-plan.md 了，四个里程碑 M1-M4，nightly-e2e 明确标注在 M4 之后单独迁。"))
    t.append(T("user", "nightly-e2e 那个确实先别动，Playwright 那套配置比较娇气。方案里就按这个来，从 build 开始。"))
    t.append(T("assistant", "Plan locked. Starting with M1: build.yml on a feature branch `ci/gha-build`."))
    # ---- segment 2: build job (21-32) ----
    t.append(T("user", "开始迁 build job 吧。"))
    t.append(T("assistant", "Writing the first version of .github/workflows/build.yml — checkout, node 20, pnpm install, then per-package build+typecheck via the matrix."))
    t.append(T("tool", _BUILD_YML_V1, tool_name="write_file"))
    t.append(T("assistant", "Pushed to `ci/gha-build`, first run triggered. Watching it."))
    t.append(T("tool", _build_fail_log(), tool_name="bash"))
    t.append(T("assistant", "全军覆没但原因单一：runner 镜像里根本没有 pnpm（exit 127, command not found），所以 12 个 matrix job 全在 install 一步死掉。另外我注意到 v1 里 setup-node 也没启用 pnpm cache。修法：加 `pnpm/action-setup@v4` 固定 9.6.0，setup-node 开 `cache: 'pnpm'`，再补 turbo 的 actions/cache。"))
    t.append(T("tool", _BUILD_YML_V2_DIFF, tool_name="write_file"))
    t.append(T("tool", _build_ok_log(), tool_name="bash"))
    t.append(T("assistant", "Second run is green: 12/12 packages, wall clock 9m41s——对比 Jenkins 串行 build 的 ~23 分钟已经砍掉一半以上。首轮有 3 个包 turbo cache MISS 属于冷启动，后续会稳定命中。"))
    t.append(T("user", "cache 命中情况怎么样？给我看下数据。"))
    t.append(T("tool", _cache_stats(), tool_name="bash"))
    t.append(T("assistant", "第二次运行 turbo 89% hit（32/36 task），pnpm store 412MB 恢复正常。M1 达成——build.yml 可以认为稳定了。"))
    # ---- segment 3: test job (33-49) ----
    t.append(T("user", "好，build 稳了，开始迁 test job。测试要全量跑一遍，我要看到完整结果，别只跑改动包。"))
    t.append(T("assistant", "Full suite it is — test.yml with 4 shards mirroring the Jenkins parallel stage, fail-fast off so one red shard doesn't mask the rest, junit XML uploaded per shard."))
    t.append(T("tool", _TEST_YML, tool_name="write_file"))
    t.append(T("tool", _test_log(rerun=False), tool_name="bash"))
    t.append(T("assistant", "全量结果出来了：107 个 suite，3 个用例失败集中在两处——`packages/notifications` 的 digestScheduler（时区：期望 +08:00 的 18 点、拿到 UTC 10 点，测试里写死了 +8h 偏移）和 `packages/search` 的 indexRebuild（fixture 绑死 39400 端口，shard 2/4 同 runner 撞车）。这两类在 Actions runner 上必现，不是迁移引入的逻辑问题。"))
    t.append(T("user", "这几个在 Jenkins 上也偶尔挂，是老 flaky 了。这次修掉，别用 skip 糊过去。"))
    t.append(T("assistant", "看 digestScheduler 的实现和测试，确定根因后改。"))
    t.append(T("tool", "packages/notifications/src/__tests__/digestScheduler.test.ts (excerpt)\n\n  const nextSixPm = new Date(Date.now() + 8 * 3600 * 1000);   // ← hardcoded +8h, assumes runner in UTC\n  nextSixPm.setHours(18, 0, 0, 0);\n  scheduler.schedule(user, nextSixPm);\n  ...\n  expect(sent[0].slot.toISOString()).toBe(expectedSlot);\n\npackages/notifications/src/digestScheduler.ts (excerpt)\n\n  // slots are computed in the user's timezone via luxon, never from the host clock\n  const slot = DateTime.now().setZone(user.tz).set({ hour: 18, minute: 0 });\n", tool_name="read_file"))
    t.append(T("assistant", "Root cause confirmed: 实现按用户时区算 slot，测试却用宿主机时钟手搓 +8h——在 UTC runner 上必挂。修法：`jest.useFakeTimers().setSystemTime(...)` 固定基准时间，期望值用与实现相同的 luxon 计算，不再碰 Date.now。"))
    t.append(T("tool", "--- a/packages/notifications/src/__tests__/digestScheduler.test.ts\n+++ b/packages/notifications/src/__tests__/digestScheduler.test.ts\n@@\n-  const nextSixPm = new Date(Date.now() + 8 * 3600 * 1000);\n-  nextSixPm.setHours(18, 0, 0, 0);\n+  jest.useFakeTimers().setSystemTime(new Date('2026-07-15T03:00:00Z'));\n+  const nextSixPm = DateTime.fromISO('2026-07-15T18:00:00', { zone: user.tz }).toJSDate();\n   scheduler.schedule(user, nextSixPm);\n@@\n-  expect(sent[0].slot.toISOString()).toBe(expectedSlot);\n+  expect(sent[0].slot.toISOString()).toBe(DateTime.fromISO('2026-07-15T18:00:00', { zone: user.tz }).toUTC().toISO());\n", tool_name="write_file"))
    t.append(T("assistant", "search 的端口冲突同理要去掉写死的 39400：让 fixture 用 `listen(0)` 拿临时端口，从 server.address() 读实际端口传给客户端。"))
    t.append(T("tool", "--- a/packages/search/src/__tests__/indexRebuild.test.ts\n+++ b/packages/search/src/__tests__/indexRebuild.test.ts\n@@\n-  await fixture.listen(39400);\n-  const client = new SearchClient('http://127.0.0.1:39400');\n+  await fixture.listen(0);   // ephemeral port — shards can share a runner safely\n+  const { port } = fixture.server.address() as AddressInfo;\n+  const client = new SearchClient(`http://127.0.0.1:${port}`);\n", tool_name="write_file"))
    t.append(T("tool", _test_log(rerun=True), tool_name="bash"))
    t.append(T("assistant", "Rerun fully green — 4/4 shards, 3 个老 flaky 正式毕业。测试时长 6m12s（缓存热了之后），对比 Jenkins 的 shard 阶段 ~15 分钟。"))
    t.append(T("user", "测试报告能不能出成 summary？Jenkins 上有 junit 报表页，这个能力别在迁移里丢了。"))
    t.append(T("tool", "--- a/.github/workflows/test.yml\n+++ b/.github/workflows/test.yml\n@@ steps (appended)\n+      - name: Publish junit summary\n+        if: always()\n+        run: node scripts/junit-to-summary.mjs reports/junit >> \"$GITHUB_STEP_SUMMARY\"\n+  report:\n+    needs: test\n+    if: always()\n+    runs-on: ubuntu-latest\n+    steps:\n+      - uses: actions/download-artifact@v4\n+        with: { pattern: junit-shard-*, merge-multiple: true, path: reports/junit }\n+      - run: node scripts/junit-to-summary.mjs reports/junit --merged >> \"$GITHUB_STEP_SUMMARY\"\n", tool_name="write_file"))
    t.append(T("assistant", "Done — 每个 shard 出自己的 summary，另加一个 `report` job 合并四个 shard 的 junit 后输出总表（суite 数、失败数、慢测 Top10），并保留 30 天 artifact。M2 收工。"))
    # ---- segment 4: deploy job (50-61) ----
    t.append(T("user", "接下来 deploy job。先说好：生产环境部署必须保留人工审批环节，staging 可以全自动，审批人就是 platform-leads。"))
    t.append(T("assistant", "Matching the Jenkins `input` gate with an environment approval: deploy.yml 由 test 成功触发（workflow_run），staging job 自动跑，production job 挂在 `environment: production` 上等 platform-leads 批准——审批记录还能沉淀在 deployment log 里，比 Jenkins input 更可审计。"))
    t.append(T("tool", _DEPLOY_YML, tool_name="write_file"))
    t.append(T("assistant", "Workflow 写好了，现在把两个 environment 和 secrets 配上（按之前的约定全部 environment-scoped）。"))
    t.append(T("tool", _env_setup_log(), tool_name="bash"))
    t.append(T("assistant", "Environments ready: staging 无审批、production 挂 platform-leads required reviewers。跑一次 staging 部署验证。"))
    t.append(T("tool", _staging_deploy_log(), tool_name="bash"))
    t.append(T("assistant", "Staging 4 个服务全部 rolled out，冒烟 200，4m18s。production job 现在停在审批那里等 review——正好演示一下审批流。"))
    t.append(T("user", "走一遍生产演练可以，但打到 staging 集群的 canary namespace 里，别碰真生产。"))
    t.append(T("tool", _canary_log(), tool_name="bash"))
    t.append(T("assistant", "Canary rehearsal 完整走通：审批请求发给 platform-leads、你批准后才继续、全部资源都落在 staging-canary namespace，真生产零接触。审批 gate 的行为和 Jenkins input 等价，M3 完成。"))
    t.append(T("assistant", "Deploy 迁移小结：staging 自动化、production 审批复刻、secrets 全部 environment-scoped、canary 演练通过。剩下的是量化收益和收尾。"))
    # ---- segment 5: 性能对比 (62-71) ----
    t.append(T("user", "给我一份新旧 CI 的耗时对比，各跑三次取平均，我要拿去和团队同步。"))
    t.append(T("tool", _timing_report(), tool_name="bash"))
    t.append(T("assistant", "三轮平均：PR 流水线 31m52s → 12m06s（-62%），main 全流程 48m23s → 21m19s（-56%）。而且 Jenkins 数字还没算下午高峰平均 4 分钟的 executor 排队，实际体感差距更大。"))
    t.append(T("user", "build 还能再压吗？"))
    t.append(T("assistant", "两个抓手：turbo remote cache（跨 runner 共享，冷启动也能命中）和 docker buildx 的 layer cache（gateway/web-app 两个镜像每次都全量重建）。我加上再跑一轮。"))
    t.append(T("tool", "--- a/.github/workflows/build.yml\n+++ b/.github/workflows/build.yml\n@@\n+      - name: Turbo remote cache\n+        run: echo \"TURBO_API=https://turbo-cache.internal.corp\" >> \"$GITHUB_ENV\"\n@@ docker jobs in deploy path\n+      - uses: docker/setup-buildx-action@v3\n+      - name: Build with layer cache\n+        uses: docker/build-push-action@v6\n+        with:\n+          cache-from: type=registry,ref=registry.internal.corp:5000/monorepo/cache\n+          cache-to: type=registry,ref=registry.internal.corp:5000/monorepo/cache,mode=max\n", tool_name="write_file"))
    t.append(T("tool", _remote_cache_log(), tool_name="bash"))
    t.append(T("assistant", "Remote cache + layer cache 之后 main 全流程 21m19s → 16m02s，docker 两镜像 build 时间掉了六成。再往下就要动测试并行度了，收益边际递减。"))
    t.append(T("user", "可以了，别过度优化，16 分钟完全够用。"))
    t.append(T("assistant", "同意，性能优化到此为止。最终数字：PR 12 分钟、main 16 分钟，均已稳定复现三轮。"))
    # ---- segment 6: 收尾 (72-79) ----
    t.append(T("user", "收尾吧。Jenkins 那边怎么处理？记住开头说的，先并行观察，别急着下线。"))
    t.append(T("assistant", "按 M4 执行：只关掉 monorepo-pr 的 SCM 轮询触发（PR 侧已完全由 Actions 接管，留着轮询纯浪费 executor），monorepo-main 保持并行跑两周做对照；nightly-e2e、release-tag、dependency-audit 原样不动。两周后确认无回归再正式下线。"))
    t.append(T("tool", "$ java -jar jenkins-cli.jar -s https://jenkins.internal.corp disable-job monorepo-pr\nDisabled job 'monorepo-pr'\n$ java -jar jenkins-cli.jar -s https://jenkins.internal.corp get-job monorepo-pr | grep -c '<disabled>true</disabled>'\n1\n$ java -jar jenkins-cli.jar -s https://jenkins.internal.corp list-jobs\nmonorepo-pr (disabled)\nmonorepo-main\nnightly-e2e\nrelease-tag\ndependency-audit\n", tool_name="bash"))
    t.append(T("assistant", "monorepo-pr 已禁用，monorepo-main 继续并行。Jenkins 侧现在是纯观察模式。"))
    t.append(T("user", "更新一下 CONTRIBUTING 文档，告诉大家新 CI 怎么用、报告去哪里看。"))
    t.append(T("tool", _CONTRIB_DIFF, tool_name="write_file"))
    t.append(T("assistant", "CONTRIBUTING 更新完毕：新 CI 的入口、单 shard 重跑、审批流程、以及过渡期 Jenkins 并行状态都写清楚了。"))
    t.append(T("assistant", "迁移总结：M1-M3 全部落地（build matrix / 4-shard 测试含 3 个 flaky 根修 / staging 自动 + production 审批部署），性能 PR -62%、main -56%（优化后 16 分钟），secrets 全部 environment-scoped。遗留事项：两周并行观察后下线 monorepo-main；nightly-e2e 与 dependency-audit 下一期迁移。"))
    return t


_turn_list = _turns()

CASE = Case(
    case_id="c4",
    title="Jenkins 迁移 GitHub Actions（超长 CI 会话）",
    turns=_turn_list,
    segments=[
        Segment("现状调研", 0, 10),
        Segment("迁移方案设计", 11, 20),
        Segment("build job 迁移", 21, 32),
        Segment("test job 迁移", 33, 49),
        Segment("deploy job 迁移", 50, 61),
        Segment("性能对比", 62, 71),
        Segment("收尾", 72, 79),
    ],
    constraints=[
        GoldConstraint(0, "迁移期间 Jenkins 必须保持可用，不要提前下线"),
        GoldConstraint(13, "所有 secrets 必须走 GitHub Environments，禁止写进 workflow 文件"),
        GoldConstraint(50, "生产环境部署必须保留人工审批环节"),
    ],
    backtracks=[],
)
