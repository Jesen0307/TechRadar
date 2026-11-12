pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '30'))
    }

    environment {
        TOOLS_DIR = "${WORKSPACE}/.tools"
        DT_URL = "${params.DT_URL}"
        RUN_AGENT = "${params.RUN_AGENT}"
    }

    parameters {
        string(name: 'DT_URL', defaultValue: 'http://dependency-track-apiserver-1:8080', description: 'URL API server Dependency-Track, harus terjangkau dari Jenkins (bukan dari browser)')
        string(name: 'TAG', defaultValue: '', description: 'Opsional: hanya project dengan tag ini')
        booleanParam(name: 'RUN_AGENT', defaultValue: true, description: 'Jalankan AI agent. Bila dimatikan, radar dibuat dari blips.json di repo')
        booleanParam(name: 'REQUIRE_APPROVAL', defaultValue: false, description: 'Minta persetujuan manusia sebelum radar.json dibuat')
        booleanParam(name: 'ARCHIVE_RAW', defaultValue: false, description: 'Arsipkan juga data mentah semua project (besar)')
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                sh 'rm -rf dump radar.json blips.previous.json'
            }
        }

        stage('Siapkan tool') {
            steps {
                timeout(time: 10, unit: 'MINUTES') {
                    sh '''
                        set -e
                        python3 --version
                        command -v curl >/dev/null 2>&1 || { echo "curl tidak ditemukan di node"; exit 1; }
                        mkdir -p "$TOOLS_DIR/bin"
                        export PATH="$TOOLS_DIR/bin:$PATH"
                        if [ "$RUN_AGENT" = "true" ]; then
                            if ! command -v opencode >/dev/null 2>&1; then
                                echo "OpenCode belum ada, memasang ke $TOOLS_DIR/bin"
                                OPENCODE_INSTALL_DIR="$TOOLS_DIR/bin" curl -fsSL https://opencode.ai/install | bash
                            fi
                            opencode --version
                        fi
                    '''
                }
            }
        }

        stage('Ambil semua component') {
            steps {
                script {
                    def args = ''
                    if (params.TAG?.trim()) {
                        if (!(params.TAG.trim() ==~ /[A-Za-z0-9_.-]+/)) { error 'TAG tidak valid' }
                        args = "--tag ${params.TAG.trim()}"
                    }
                    env.DUMP_ARGS = args
                }
                withCredentials([string(credentialsId: 'dtrack-api-key', variable: 'DT_KEY')]) {
                    sh 'python3 dtrack_dump.py --url "$DT_URL" --out dump $DUMP_ARGS'
                }
            }
        }

        stage('Agent menentukan blip') {
            when { expression { params.RUN_AGENT } }
            steps {
                sh 'cp blips.json blips.previous.json || echo \'{"blips": [], "dikecualikan": []}\' > blips.previous.json'
                catchError(buildResult: 'SUCCESS', stageResult: 'FAILURE', message: 'AI agent tidak selesai') {
                    timeout(time: 30, unit: 'MINUTES') {
                        withEnv(["PATH+TOOLS=${env.TOOLS_DIR}/bin"]) {
                            aiAgent agent: openCode(),
                                    apiCredentialsId: 'OpenCode',
                                    failOnAgentError: false,
                                    model: 'opencode/deepseek-v4.1-flash-free',
                                    prompt: '''Baca radar-playbook.md dan ikuti persis.
Input: dump/components.json dan blips.previous.json.

Langkah 1: tentukan blip, quadrant, ring, dan component yang dikecualikan, lalu tulis ke blips.json memakai format di playbook.
Setiap id di dump/components.json harus muncul tepat satu kali.
Berkas harus berisi hanya JSON yang valid, tanpa markdown, tanpa code fence, dan tanpa teks sebelum atau sesudahnya.

Langkah 2: setelah berkas tertulis, balasan akhirmu berupa ringkasan singkat yang bisa dibaca manusia.
Susun dari blips.json yang baru kamu tulis, jangan menganalisis ulang dan jangan menempel JSON. Pakai layout ini:
## Hasil Penentuan Blip
**Jumlah blip:** angka, dan jumlah component yang dikecualikan
**Keyakinan rendah:** nama blip dipisah koma
**Perubahan dari keputusan sebelumnya:** satu bullet per perubahan, atau "tidak ada"
**Perlu perhatian manusia:** satu bullet per hal

Jangan mengubah berkas lain.''',
                                    yoloMode: true
                        }
                    }
                }
            }
        }

        stage('Validasi blips') {
            steps {
                script {
                    def rc = sh(
                        script: 'python3 build_radar.py --blips blips.json --components dump/components.json --check',
                        returnStatus: true
                    )
                    env.BLIPS_OK = (rc == 0) ? 'true' : 'false'
                    if (rc != 0) {
                        unstable('blips.json tidak valid atau tidak lengkap, radar.json tidak dibuat')
                    }
                }
            }
        }

        stage('Persetujuan manusia') {
            when { expression { params.REQUIRE_APPROVAL && env.BLIPS_OK == 'true' } }
            steps {
                timeout(time: 2, unit: 'DAYS') {
                    input message: 'Setujui blips.json (lihat artifact) untuk dijadikan radar?', ok: 'Setujui'
                }
            }
        }

        stage('Bangun radar') {
            when { expression { env.BLIPS_OK == 'true' } }
            steps {
                sh 'python3 build_radar.py --blips blips.json --components dump/components.json --out radar.json'
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: 'radar.json, blips.json, blips.previous.json, dump/components.json, dump/projects.json', allowEmptyArchive: true
            script {
                if (params.ARCHIVE_RAW) {
                    archiveArtifacts artifacts: 'dump/**', allowEmptyArchive: true
                }
            }
        }
    }
}
