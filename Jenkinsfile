pipeline {
    agent any

    options {
        timeout(time: 90, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '50'))
        timestamps()
        ansiColor('xterm')
    }

    parameters {
        choice(
            name: 'TEST_STRATEGY',
            choices: [
                'standard',
                'smoke_only',
                'deep',
                'full_stress'
            ],
            description: '''选择用例耗时分级策略 (由快到慢梯度执行)：
standard: [推荐日常CI] Tier 1 极速冒烟 + Tier 2 标准兼容30例 (~ 1分钟)
smoke_only: [PR/极速拦截] 仅 Tier 1 极速冒烟探活 (< 10秒)
deep: [发版准入] Tier 1~3 包含模型自认知真实性测评 (~ 3分钟)
full_stress: [夜间压测] Tier 1~4 全量梯度执行，含33k超长文本与并发压测 (~ 10分钟)'''
        )
        choice(
            name: 'CHANNELS',
            choices: [
                'xunlitec,pindu',
                'xunlitec',
                'pindu',
                'xunlitec,pindu,volcano',
                'custom'
            ],
            description: '待测试渠道集合 (预设或自定义)'
        )
        string(
            name: 'CUSTOM_CHANNELS',
            defaultValue: '',
            description: '自定义渠道 (当 CHANNELS 选 custom 时生效)，格式: ch1=https://url1/v1,ch2=https://url2/v1'
        )
        string(
            name: 'MODELS',
            defaultValue: 'kimi-k3,glm-5.3',
            description: '待测试模型标识 (英文逗号分隔，如: kimi-k3,glm-5.3)'
        )
        string(
            name: 'MIN_PASS_RATE',
            defaultValue: '90.0',
            description: '质量门禁：最低全局用例通过率百分比阈值'
        )
        booleanParam(
            name: 'FAIL_ON_ERROR',
            defaultValue: true,
            description: '是否在任一阶段用例失败时立即阻断流水线 (Fail-Fast)'
        )
        booleanParam(
            name: 'SELF_TEST_DRY_RUN',
            defaultValue: false,
            description: '离线自测模拟执行 (不消耗 Token 与网络，用于校验流水线流程与看板)'
        )
        string(
            name: 'CONCURRENCY',
            defaultValue: '2',
            description: '测试并发进程数'
        )
        string(
            name: 'TEST_TIMEOUT',
            defaultValue: '120.0',
            description: '单个用例超时时间 (秒)'
        )
    }

    environment {
        PYTHONUNBUFFERED = '1'
        // 通用兜底 API Key (在 Jenkins 凭据中添加 ID 为 "kimi-k3-api-key" 的 Secret text)
        DEFAULT_KEY = credentials('kimi-k3-api-key')
    }

    stages {
        stage('环境检出与依赖预检') {
            steps {
                echo "========================================================="
                echo "🚀 启动多渠道多模型测试集成流水线 (按耗时梯度分层)"
                echo "⏱️ 耗时策略: ${params.TEST_STRATEGY}"
                echo "🌐 目标渠道: ${params.CHANNELS == 'custom' ? params.CUSTOM_CHANNELS : params.CHANNELS}"
                echo "🤖 待测模型: ${params.MODELS}"
                echo "📊 门禁阈值: 最低通过率 ${params.MIN_PASS_RATE}%"
                echo "========================================================="

                script {
                    def isWin = isUnix() ? false : true
                    def pyCmd = isWin ? 'python' : 'python3'

                    if (isUnix()) {
                        sh """
                            ${pyCmd} -m pip install requests pytest pytest-xdist allure-pytest || true
                        """
                    } else {
                        bat """
                            ${pyCmd} -m pip install requests pytest pytest-xdist allure-pytest || exit 0
                        """
                    }
                }
            }
        }

        stage('梯度阶段执行 · 耗时分级测试矩阵') {
            steps {
                echo "⚙️ 启动耗时分级调度引擎 (matrix_tier_runner.py)..."
                script {
                    def channelsToRun = params.CHANNELS == 'custom' ? params.CUSTOM_CHANNELS : params.CHANNELS
                    def isWin = isUnix() ? false : true
                    def pyCmd = isWin ? 'python' : 'python3'

                    def cmd = "${pyCmd} matrix_tier_runner.py"
                    if (params.SELF_TEST_DRY_RUN) {
                        cmd += " --self-test"
                    } else {
                        cmd += " --channels \"${channelsToRun}\""
                        cmd += " --models \"${params.MODELS}\""
                        cmd += " --strategy \"${params.TEST_STRATEGY}\""
                        cmd += " --concurrency ${params.CONCURRENCY}"
                        cmd += " --timeout ${params.TEST_TIMEOUT}"
                        cmd += " --min-pass-rate ${params.MIN_PASS_RATE}"
                        if (params.FAIL_ON_ERROR) {
                            cmd += " --fail-on-error"
                        }
                    }

                    echo "执行指令: ${cmd}"

                    if (isUnix()) {
                        sh """
                            set +e
                            ${cmd}
                            echo \$? > matrix_exit_code.txt
                            exit 0
                        """
                    } else {
                        bat """
                            ${cmd}
                            echo %ERRORLEVEL% > matrix_exit_code.txt
                            exit 0
                        """
                    }
                }
            }
        }

        stage('多维度综合质量门禁评估 (Quality Gate)') {
            steps {
                script {
                    def exitCode = readFile('matrix_exit_code.txt').trim()
                    echo "执行器退出状态码: ${exitCode}"

                    def isWin = isUnix() ? false : true
                    def pyCmd = isWin ? 'python' : 'python3'

                    def gateScript = """
import json, sys
from pathlib import Path

sum_file = Path('results/matrix_results/matrix_summary.json')
if not sum_file.exists():
    print('❌ 错误：未找到矩阵测试汇总文件 results/matrix_results/matrix_summary.json！')
    sys.exit(1)

records = json.loads(sum_file.read_text(encoding='utf-8'))
total_cells = len(records)
pass_cells = sum(1 for r in records if r.get('status') == 'PASS')
total_cases = sum(r.get('total_cases', 0) for r in records)
passed_cases = sum(r.get('passed_cases', 0) for r in records)
overall_rate = round(passed_cases / total_cases * 100, 2) if total_cases > 0 else 0.0

print('=' * 65)
print('🎯 耗时分级测试流水线门禁统计:')
print(f'  - 矩阵单元通过率: {pass_cells}/{total_cells} ({round(pass_cells/total_cells*100, 1) if total_cells else 0}%)')
print(f'  - 测试用例通过率: {passed_cases}/{total_cases} ({overall_rate}%)')
print('=' * 65)

min_rate = float('${params.MIN_PASS_RATE}')
fail_on_error = ${params.FAIL_ON_ERROR ? 'True' : 'False'}

if fail_on_error and pass_cells < total_cells:
    print('🚨 门禁阻断：检测到部分耗时梯度测试单元未通过！')
    sys.exit(2)

if overall_rate < min_rate:
    print(f'🚨 门禁阻断：全局通过率 {overall_rate}% 低于门禁基线 {min_rate}%！')
    sys.exit(3)

print('✅ 质量门禁校验全部通过！多渠道多模型达标准入！')
"""
                    if (isUnix()) {
                        sh """${pyCmd} -c "${gateScript}" """
                    } else {
                        writeFile file: '_temp_gate.py', text: gateScript, encoding: 'UTF-8'
                        bat """${pyCmd} _temp_gate.py"""
                    }
                }
            }
        }
    }

    post {
        always {
            echo "📦 收集并归档多渠道耗时分级测试大盘产物..."

            archiveArtifacts artifacts: 'matrix_report.html, matrix_summary.md, results/matrix_results/**', allowEmptyArchive: true

            publishHTML([
                allowMissing: true,
                alwaysLinkToLastBuild: true,
                keepAll: true,
                reportDir: 'results/matrix_results',
                reportFiles: 'matrix_report.html',
                reportName: '多渠道多模型测试对比大盘 (HTML)',
                reportTitles: 'Multi-Channel Multi-Model Matrix Dashboard'
            ])

            allure([
                includeProperties: false,
                jdk: '',
                properties: [],
                reportBuildPolicy: 'ALWAYS',
                results: [[path: 'kimi-k3准入测试/allure-results']]
            ])
        }
        success {
            echo "🎉 耗时梯度准入流水线测试达标通过！"
        }
        failure {
            echo "❌ 测试未达标或触发 Fail-Fast 质量门禁阻断！"
        }
    }
}
